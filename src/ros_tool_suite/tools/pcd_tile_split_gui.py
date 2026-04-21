#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
PCD tile splitter with GUI
Features:
- Select input PCD by dialog
- Select output directory by dialog
- Optional zip output
- Choose output tile format: ascii / binary
- Generate Autoware-style pointcloud_data_metadata.yaml
- Progress bar
- Preview point cloud bounds and estimated tile count
- Optional auto-clean output directory

Windows:
    python pcd_tile_split_gui.py

Linux:
    python3 pcd_tile_split_gui.py
"""

import argparse
import math
import os
import shutil
import struct
import threading
import zlib
import zipfile
from typing import Dict, List, Tuple, Any, Optional, Callable

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from ros_tool_suite.shared_ui import (
    apply_suite_theme,
    make_card,
    style_text_widget,
    apply_log_tags,
    append_tagged_text,
)


# =========================
# PCD core
# =========================

def parse_pcd_header(f) -> Tuple[Dict[str, Any], int]:
    header = {}
    lines = []
    while True:
        line = f.readline()
        if not line:
            raise RuntimeError("PCD header ended unexpectedly")
        try:
            s = line.decode("utf-8", errors="ignore").strip()
        except Exception:
            s = str(line).strip()
        lines.append(s)
        if s.startswith("DATA"):
            data_offset = f.tell()
            break

    def get_list(key: str) -> List[str]:
        for l in lines:
            if l.startswith(key + " "):
                return l.split()[1:]
        return []

    def get_value(key: str, default=None):
        for l in lines:
            if l.startswith(key + " "):
                return l.split()[1:]
        return default

    header["FIELDS"] = get_list("FIELDS") or get_list("FIELD")
    header["SIZE"] = list(map(int, get_list("SIZE")))
    header["TYPE"] = get_list("TYPE")
    header["COUNT"] = list(map(int, get_list("COUNT"))) if get_list("COUNT") else [1] * len(header["FIELDS"])
    header["WIDTH"] = int(get_value("WIDTH")[0])
    header["HEIGHT"] = int(get_value("HEIGHT")[0])
    header["POINTS"] = int(get_value("POINTS")[0]) if get_value("POINTS") else header["WIDTH"] * header["HEIGHT"]
    header["DATA"] = get_value("DATA")[0].lower()

    if not header["FIELDS"]:
        raise RuntimeError("PCD missing FIELDS")
    if len(header["FIELDS"]) != len(header["SIZE"]) or len(header["FIELDS"]) != len(header["TYPE"]) or len(header["FIELDS"]) != len(header["COUNT"]):
        raise RuntimeError("PCD header malformed (FIELDS/SIZE/TYPE/COUNT length mismatch)")

    return header, data_offset


def build_struct_fmt(header: Dict[str, Any]) -> Tuple[str, List[Tuple[str, int, str, int]]]:
    fields = header["FIELDS"]
    sizes = header["SIZE"]
    types = header["TYPE"]
    counts = header["COUNT"]

    def type_to_struct(t: str, sz: int) -> str:
        if t == "F":
            return {4: "f", 8: "d"}[sz]
        if t == "I":
            return {1: "b", 2: "h", 4: "i", 8: "q"}[sz]
        if t == "U":
            return {1: "B", 2: "H", 4: "I", 8: "Q"}[sz]
        raise ValueError(f"Unsupported TYPE/SIZE: {t}/{sz}")

    fmt = "<"
    desc = []
    offset = 0
    for name, sz, t, c in zip(fields, sizes, types, counts):
        code = type_to_struct(t, sz)
        fmt += code * c
        desc.append((name, offset, code, c))
        offset += sz * c
    return fmt, desc


def read_points(
    header: Dict[str, Any],
    f,
    data_offset: int,
    progress_cb: Optional[Callable[[float, str], None]] = None
) -> List[Dict[str, float]]:
    f.seek(data_offset)
    fields = header["FIELDS"]
    data_type = header["DATA"]
    n = header["POINTS"]

    idx = {name: i for i, name in enumerate(fields)}
    points = []

    def get_field(row: List[float], name: str) -> Optional[float]:
        if name in idx:
            return float(row[idx[name]])
        return None

    def maybe_progress(i: int, total: int, stage: str):
        if progress_cb and total > 0 and (i % max(1, total // 200) == 0 or i == total - 1):
            progress_cb((i + 1) / total, stage)

    if data_type == "ascii":
        for i in range(n):
            line = f.readline()
            if not line:
                break
            s = line.decode("utf-8", errors="ignore").strip()
            if not s:
                maybe_progress(i, n, "读取 ASCII 点云")
                continue
            vals = list(map(float, s.split()))
            row = vals
            px = get_field(row, "x")
            py = get_field(row, "y")
            pz = get_field(row, "z")
            if px is not None and py is not None and pz is not None:
                inten = get_field(row, "intensity")
                if inten is None:
                    inten = get_field(row, "reflectivity")
                points.append({
                    "x": px,
                    "y": py,
                    "z": pz,
                    "intensity": float(inten) if inten is not None else 0.0
                })
            maybe_progress(i, n, "读取 ASCII 点云")

    elif data_type == "binary":
        fmt, _ = build_struct_fmt(header)
        rec_size = struct.calcsize(fmt)
        blob = f.read(n * rec_size)
        if len(blob) < n * rec_size:
            n = len(blob) // rec_size

        unpack = struct.Struct(fmt).unpack_from
        for i in range(n):
            row = unpack(blob, i * rec_size)
            px = float(row[idx["x"]]) if "x" in idx else None
            py = float(row[idx["y"]]) if "y" in idx else None
            pz = float(row[idx["z"]]) if "z" in idx else None
            if px is not None and py is not None and pz is not None:
                inten = None
                if "intensity" in idx:
                    inten = float(row[idx["intensity"]])
                elif "reflectivity" in idx:
                    inten = float(row[idx["reflectivity"]])
                points.append({
                    "x": px,
                    "y": py,
                    "z": pz,
                    "intensity": float(inten) if inten is not None else 0.0
                })
            maybe_progress(i, n, "读取 Binary 点云")

    elif data_type == "binary_compressed":
        head = f.read(8)
        if len(head) != 8:
            raise RuntimeError("binary_compressed header too short")
        comp_size, uncomp_size = struct.unpack("<II", head)
        comp = f.read(comp_size)
        raw = zlib.decompress(comp)

        fmt, _ = build_struct_fmt(header)
        rec_size = struct.calcsize(fmt)
        n = min(n, len(raw) // rec_size)

        unpack = struct.Struct(fmt).unpack_from
        for i in range(n):
            row = unpack(raw, i * rec_size)
            px = float(row[idx["x"]]) if "x" in idx else None
            py = float(row[idx["y"]]) if "y" in idx else None
            pz = float(row[idx["z"]]) if "z" in idx else None
            if px is not None and py is not None and pz is not None:
                inten = None
                if "intensity" in idx:
                    inten = float(row[idx["intensity"]])
                elif "reflectivity" in idx:
                    inten = float(row[idx["reflectivity"]])
                points.append({
                    "x": px,
                    "y": py,
                    "z": pz,
                    "intensity": float(inten) if inten is not None else 0.0
                })
            maybe_progress(i, n, "读取 Compressed 点云")

    else:
        raise RuntimeError(f"Unsupported PCD DATA type: {data_type}")

    if progress_cb:
        progress_cb(1.0, "点云读取完成")

    return points


def write_pcd_ascii(path: str, pts: List[Dict[str, float]]):
    with open(path, "w", encoding="utf-8", newline="\n") as w:
        w.write("# .PCD v0.7 - Point Cloud Data file format\n")
        w.write("VERSION 0.7\n")
        w.write("FIELDS x y z intensity\n")
        w.write("SIZE 4 4 4 4\n")
        w.write("TYPE F F F F\n")
        w.write("COUNT 1 1 1 1\n")
        w.write(f"WIDTH {len(pts)}\n")
        w.write("HEIGHT 1\n")
        w.write("VIEWPOINT 0 0 0 1 0 0 0\n")
        w.write(f"POINTS {len(pts)}\n")
        w.write("DATA ascii\n")
        for p in pts:
            w.write(f"{p['x']} {p['y']} {p['z']} {p['intensity']}\n")


def write_pcd_binary(path: str, pts: List[Dict[str, float]]):
    with open(path, "wb") as w:
        header = (
            "# .PCD v0.7 - Point Cloud Data file format\n"
            "VERSION 0.7\n"
            "FIELDS x y z intensity\n"
            "SIZE 4 4 4 4\n"
            "TYPE F F F F\n"
            "COUNT 1 1 1 1\n"
            f"WIDTH {len(pts)}\n"
            "HEIGHT 1\n"
            "VIEWPOINT 0 0 0 1 0 0 0\n"
            f"POINTS {len(pts)}\n"
            "DATA binary\n"
        )
        w.write(header.encode("utf-8"))
        packer = struct.Struct("<ffff")
        for p in pts:
            w.write(packer.pack(
                float(p["x"]),
                float(p["y"]),
                float(p["z"]),
                float(p["intensity"])
            ))


def tile_key(x: float, y: float, tile_size: float) -> Tuple[float, float]:
    tx = math.floor(x / tile_size) * tile_size
    ty = math.floor(y / tile_size) * tile_size
    return (tx, ty)


def format_tile_coord(v: float) -> str:
    if float(v).is_integer():
        return str(int(v))
    return str(v)


def format_yaml_number(v: float) -> str:
    if float(v).is_integer():
        return str(int(v))
    return str(v)


def write_metadata_yaml(path: str, tile_size: float, tile_entries: List[Tuple[str, float, float]]):
    with open(path, "w", encoding="utf-8", newline="\n") as w:
        w.write(f"x_resolution: {format_yaml_number(tile_size)}\n")
        w.write(f"y_resolution: {format_yaml_number(tile_size)}\n")
        for name, tx, ty in tile_entries:
            w.write(f"{name}: [{format_yaml_number(tx)}, {format_yaml_number(ty)}]\n")


def scan_point_stats(points: List[Dict[str, float]], tile_size: float) -> Dict[str, Any]:
    xs = [p["x"] for p in points]
    ys = [p["y"] for p in points]
    zs = [p["z"] for p in points]

    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    zmin, zmax = min(zs), max(zs)

    tile_keys = set()
    for p in points:
        tile_keys.add(tile_key(p["x"], p["y"], tile_size))

    return {
        "xmin": xmin, "xmax": xmax,
        "ymin": ymin, "ymax": ymax,
        "zmin": zmin, "zmax": zmax,
        "estimated_tiles": len(tile_keys),
    }


def clean_output_dir(out_dir: str, metadata_name: str, logger=None):
    def log(msg: str):
        if logger:
            logger(msg)
        else:
            print(msg)

    if not os.path.isdir(out_dir):
        return

    removed = 0
    for fn in os.listdir(out_dir):
        full = os.path.join(out_dir, fn)
        if os.path.isfile(full) and (fn.endswith(".pcd") or fn.endswith(".yaml") or fn.endswith(".zip")):
            try:
                os.remove(full)
                removed += 1
            except Exception:
                pass
        elif os.path.isdir(full):
            # 不主动删子目录，避免误删
            pass

    log(f"[INFO] 已清空输出目录中的旧文件: {removed} 个")


def split_pcd(
    input_path: str,
    out_dir: str,
    tile_size: float,
    prefix: str,
    metadata_name: str,
    min_points_per_tile: int,
    output_format: str,
    zip_path: str = "",
    auto_clean_output: bool = False,
    logger=None,
    progress_cb: Optional[Callable[[float, str], None]] = None,
):
    def log(msg: str):
        if logger:
            logger(msg)
        else:
            print(msg)

    os.makedirs(out_dir, exist_ok=True)

    if auto_clean_output:
        clean_output_dir(out_dir, metadata_name, logger=log)

    if progress_cb:
        progress_cb(0.0, "开始读取文件")

    log(f"[INFO] Reading: {input_path}")
    with open(input_path, "rb") as f:
        header, data_off = parse_pcd_header(f)
        pts = read_points(
            header,
            f,
            data_off,
            progress_cb=lambda p, s: progress_cb(0.0 + p * 0.35, s) if progress_cb else None
        )

    if not pts:
        raise RuntimeError("No points read from PCD")

    stats = scan_point_stats(pts, tile_size)
    log(f"[INFO] Points loaded: {len(pts)}")
    log(f"[INFO] Bounds X: {stats['xmin']:.3f} ~ {stats['xmax']:.3f}")
    log(f"[INFO] Bounds Y: {stats['ymin']:.3f} ~ {stats['ymax']:.3f}")
    log(f"[INFO] Bounds Z: {stats['zmin']:.3f} ~ {stats['zmax']:.3f}")
    log(f"[INFO] Estimated tile count: {stats['estimated_tiles']}")
    log(f"[INFO] Tiling with tile_size = {tile_size}")

    if progress_cb:
        progress_cb(0.38, "按 tile 分桶")

    tiles: Dict[Tuple[float, float], List[Dict[str, float]]] = {}
    total_pts = len(pts)
    step = max(1, total_pts // 200)

    for i, p in enumerate(pts):
        k = tile_key(p["x"], p["y"], tile_size)
        tiles.setdefault(k, []).append(p)
        if progress_cb and (i % step == 0 or i == total_pts - 1):
            progress_cb(0.38 + ((i + 1) / total_pts) * 0.12, "按 tile 分桶")

    written = 0
    tile_entries: List[Tuple[str, float, float]] = []
    sorted_tiles = sorted(tiles.items(), key=lambda kv: (kv[0][0], kv[0][1]))
    total_tiles = len(sorted_tiles)

    for i, ((tx, ty), plist) in enumerate(sorted_tiles):
        if len(plist) < min_points_per_tile:
            if progress_cb and total_tiles > 0:
                progress_cb(0.50 + ((i + 1) / total_tiles) * 0.40, "写出 tile 文件")
            continue

        name = f"{prefix}{format_tile_coord(tx)}_{format_tile_coord(ty)}.pcd"
        out_path = os.path.join(out_dir, name)

        if output_format == "ascii":
            write_pcd_ascii(out_path, plist)
        elif output_format == "binary":
            write_pcd_binary(out_path, plist)
        else:
            raise RuntimeError(f"Unsupported output format: {output_format}")

        tile_entries.append((name, tx, ty))
        written += 1

        if progress_cb and total_tiles > 0:
            progress_cb(0.50 + ((i + 1) / total_tiles) * 0.40, "写出 tile 文件")

    meta_path = os.path.join(out_dir, metadata_name)
    write_metadata_yaml(meta_path, tile_size, tile_entries)

    if progress_cb:
        progress_cb(0.92, "写出 metadata")

    log(f"[OK] Read points: {len(pts)}")
    log(f"[OK] Tiles written: {written}")
    log(f"[OK] Metadata: {meta_path}")

    final_zip = ""
    if zip_path:
        final_zip = zip_path
        log(f"[INFO] Writing zip: {final_zip}")
        files_to_zip = [fn for fn in os.listdir(out_dir) if fn.endswith(".pcd") or fn == metadata_name]
        total_zip = len(files_to_zip)
        with zipfile.ZipFile(final_zip, "w", compression=zipfile.ZIP_DEFLATED) as z:
            for i, fn in enumerate(files_to_zip):
                z.write(os.path.join(out_dir, fn), arcname=fn)
                if progress_cb and total_zip > 0:
                    progress_cb(0.93 + ((i + 1) / total_zip) * 0.07, "打包 zip")
        log(f"[OK] Zip written: {final_zip}")

    if progress_cb:
        progress_cb(1.0, "完成")

    return {
        "points": len(pts),
        "tiles_written": written,
        "metadata_path": meta_path,
        "zip_path": final_zip,
        "output_dir": out_dir,
        "stats": stats,
    }


def preview_pcd(
    input_path: str,
    tile_size: float,
    logger=None,
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> Dict[str, Any]:
    def log(msg: str):
        if logger:
            logger(msg)
        else:
            print(msg)

    if progress_cb:
        progress_cb(0.0, "开始预扫描")

    with open(input_path, "rb") as f:
        header, data_off = parse_pcd_header(f)
        pts = read_points(
            header,
            f,
            data_off,
            progress_cb=lambda p, s: progress_cb(p, "预扫描中") if progress_cb else None
        )

    if not pts:
        raise RuntimeError("No points read from PCD")

    stats = scan_point_stats(pts, tile_size)
    log(f"[INFO] 预扫描完成，点数: {len(pts)}")
    log(f"[INFO] X: {stats['xmin']:.3f} ~ {stats['xmax']:.3f}")
    log(f"[INFO] Y: {stats['ymin']:.3f} ~ {stats['ymax']:.3f}")
    log(f"[INFO] Z: {stats['zmin']:.3f} ~ {stats['zmax']:.3f}")
    log(f"[INFO] 预计 tile 数: {stats['estimated_tiles']}")

    if progress_cb:
        progress_cb(1.0, "预扫描完成")

    return {
        "points": len(pts),
        "stats": stats,
    }


# =========================
# GUI
# =========================

class App:
    def __init__(self, root, embedded: bool = False):
        self.root = root
        self.embedded = embedded
        if not embedded and isinstance(root, (tk.Tk, tk.Toplevel)):
            self.root.title("PCD Tile Splitter")
            self.root.geometry("980x760")

        self.input_path = tk.StringVar()
        self.out_dir = tk.StringVar()
        self.zip_path = tk.StringVar()
        self.tile_size = tk.StringVar(value="20")
        self.prefix = tk.StringVar(value="tile_")
        self.metadata_name = tk.StringVar(value="pointcloud_data_metadata.yaml")
        self.min_points = tk.StringVar(value="50")
        self.output_format = tk.StringVar(value="ascii")
        self.enable_zip = tk.BooleanVar(value=False)
        self.auto_clean_output = tk.BooleanVar(value=True)

        self.status_text = tk.StringVar(value="就绪")
        self.progress_value = tk.DoubleVar(value=0.0)

        self.preview_text = tk.StringVar(value="未预扫描")

        apply_suite_theme(root)
        self.build_ui()

    def build_ui(self):
        pad = {"padx": 8, "pady": 6}

        viewport = ttk.Frame(self.root, style="App.TFrame")
        viewport.pack(fill="both", expand=True)
        viewport.columnconfigure(0, weight=1)
        viewport.rowconfigure(0, weight=1)

        canvas = tk.Canvas(viewport, bg="#171c28", highlightthickness=0)
        canvas.grid(row=0, column=0, sticky="nsew")

        vbar = ttk.Scrollbar(viewport, orient="vertical", command=canvas.yview, style="Suite.Vertical.TScrollbar")
        vbar.grid(row=0, column=1, sticky="ns")
        hbar = ttk.Scrollbar(viewport, orient="horizontal", command=canvas.xview, style="Suite.Horizontal.TScrollbar")
        hbar.grid(row=1, column=0, sticky="ew")
        canvas.configure(yscrollcommand=vbar.set, xscrollcommand=hbar.set)

        frm = ttk.Frame(canvas, style="App.TFrame", padding=(10, 10, 10, 10))
        frm.columnconfigure(0, weight=1)
        shell_window = canvas.create_window((0, 0), window=frm, anchor="nw")

        def on_frame_configure(_event):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def on_canvas_configure(event):
            canvas.itemconfigure(shell_window, width=max(event.width - 4, 980))

        frm.bind("<Configure>", on_frame_configure)
        canvas.bind("<Configure>", on_canvas_configure)

        ttk.Label(frm, text="PCD Tile Splitter", style="Title.TLabel").grid(row=0, column=0, columnspan=4, sticky="w", padx=8, pady=(4, 2))
        ttk.Label(frm, text="统一卡片风格布局，保留切图和预扫描逻辑。", style="SubTitle.TLabel").grid(row=1, column=0, columnspan=4, sticky="w", padx=8, pady=(0, 12))

        form_card, form = make_card(frm, padding=14)
        form_card.grid(row=2, column=0, columnspan=4, sticky="ew", padx=8, pady=(0, 10))
        form.columnconfigure(1, weight=1)

        row = 0
        ttk.Label(form, text="输入 PCD", style="CardTitle.TLabel").grid(row=row, column=0, sticky="w", **pad)
        ttk.Entry(form, textvariable=self.input_path, width=82, style="Suite.TEntry").grid(row=row, column=1, sticky="ew", **pad)
        ttk.Button(form, text="选择文件", command=self.select_input, style="Secondary.TButton").grid(row=row, column=2, **pad)

        row += 1
        ttk.Label(form, text="输出目录", style="CardTitle.TLabel").grid(row=row, column=0, sticky="w", **pad)
        ttk.Entry(form, textvariable=self.out_dir, width=82, style="Suite.TEntry").grid(row=row, column=1, sticky="ew", **pad)
        ttk.Button(form, text="选择目录", command=self.select_out_dir, style="Secondary.TButton").grid(row=row, column=2, **pad)

        row += 1
        ttk.Checkbutton(form, text="输出 zip", variable=self.enable_zip, style="Suite.TCheckbutton").grid(row=row, column=0, sticky="w", **pad)
        ttk.Entry(form, textvariable=self.zip_path, width=82, style="Suite.TEntry").grid(row=row, column=1, sticky="ew", **pad)
        ttk.Button(form, text="选择 zip", command=self.select_zip, style="Secondary.TButton").grid(row=row, column=2, **pad)

        row += 1
        ttk.Checkbutton(form, text="开始前自动清空输出目录中的旧 .pcd/.yaml/.zip", variable=self.auto_clean_output, style="Suite.TCheckbutton").grid(
            row=row, column=0, columnspan=3, sticky="w", **pad
        )

        row += 1
        setting_frame = ttk.Frame(form, style="Card.TFrame")
        setting_frame.grid(row=row, column=0, columnspan=3, sticky="ew", **pad)

        ttk.Label(setting_frame, text="tile_size").grid(row=0, column=0, sticky="w", padx=6)
        ttk.Entry(setting_frame, textvariable=self.tile_size, width=12, style="Suite.TEntry").grid(row=0, column=1, sticky="w", padx=6)

        ttk.Label(setting_frame, text="文件前缀").grid(row=0, column=2, sticky="w", padx=6)
        ttk.Entry(setting_frame, textvariable=self.prefix, width=16, style="Suite.TEntry").grid(row=0, column=3, sticky="w", padx=6)

        ttk.Label(setting_frame, text="metadata 文件名").grid(row=0, column=4, sticky="w", padx=6)
        ttk.Entry(setting_frame, textvariable=self.metadata_name, width=30, style="Suite.TEntry").grid(row=0, column=5, sticky="w", padx=6)

        ttk.Label(setting_frame, text="最少点数").grid(row=0, column=6, sticky="w", padx=6)
        ttk.Entry(setting_frame, textvariable=self.min_points, width=12, style="Suite.TEntry").grid(row=0, column=7, sticky="w", padx=6)

        row += 1
        format_frame = ttk.LabelFrame(form, text="输出格式", style="Section.TLabelframe")
        format_frame.grid(row=row, column=0, columnspan=3, sticky="w", **pad)
        ttk.Radiobutton(format_frame, text="ASCII", variable=self.output_format, value="ascii", style="Suite.TRadiobutton").pack(side="left", padx=10, pady=6)
        ttk.Radiobutton(format_frame, text="Binary", variable=self.output_format, value="binary", style="Suite.TRadiobutton").pack(side="left", padx=10, pady=6)

        row += 1
        btn_frame = ttk.Frame(form, style="Card.TFrame")
        btn_frame.grid(row=row, column=0, columnspan=3, sticky="w", **pad)
        ttk.Button(btn_frame, text="预扫描", command=self.start_preview, style="Secondary.TButton").pack(side="left", padx=5)
        ttk.Button(btn_frame, text="开始切图", command=self.start_split, style="Primary.TButton").pack(side="left", padx=5)
        ttk.Button(btn_frame, text="打开输出目录", command=self.open_out_dir, style="Soft.TButton").pack(side="left", padx=5)
        ttk.Button(btn_frame, text="清空日志", command=self.clear_log, style="Soft.TButton").pack(side="left", padx=5)

        preview_card, preview_inner = make_card(frm, padding=14)
        preview_card.grid(row=3, column=0, columnspan=4, sticky="ew", padx=8, pady=(0, 10))
        preview_inner.columnconfigure(0, weight=1)
        ttk.Label(preview_inner, text="预扫描信息", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 8))
        preview_label = ttk.Label(
            preview_inner,
            textvariable=self.preview_text,
            justify="left",
            anchor="w",
            padding=8
        )
        preview_label.grid(row=1, column=0, sticky="ew")

        progress_card, progress_inner = make_card(frm, padding=14)
        progress_card.grid(row=4, column=0, columnspan=4, sticky="ew", padx=8, pady=(0, 10))
        ttk.Label(progress_inner, text="进度", style="CardTitle.TLabel").pack(anchor="w", pady=(0, 8))
        progress_frame = ttk.Frame(progress_inner, style="Card.TFrame")
        progress_frame.pack(fill="x")
        self.progress_bar = ttk.Progressbar(progress_frame, variable=self.progress_value, maximum=100, style="Suite.Horizontal.TProgressbar")
        self.progress_bar.pack(fill="x", expand=True, side="left", padx=(0, 10))
        ttk.Label(progress_frame, textvariable=self.status_text, width=28).pack(side="right")

        log_card, log_inner = make_card(frm, padding=14)
        log_card.grid(row=5, column=0, columnspan=4, sticky="nsew", padx=8, pady=(0, 8))
        log_inner.columnconfigure(0, weight=1)
        log_inner.rowconfigure(1, weight=1)
        ttk.Label(log_inner, text="日志", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 8))
        self.log_text = tk.Text(log_inner, height=20, wrap="word")
        self.log_text.grid(row=1, column=0, sticky="nsew")
        style_text_widget(self.log_text, height=20)
        apply_log_tags(self.log_text)

        scrollbar = ttk.Scrollbar(log_inner, orient="vertical", command=self.log_text.yview, style="Suite.Vertical.TScrollbar")
        scrollbar.grid(row=1, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scrollbar.set)

        frm.columnconfigure(0, weight=1)
        frm.rowconfigure(5, weight=1)

        def _on_mousewheel(event):
            if event.state & 0x1:
                canvas.xview_scroll(int(-1 * (event.delta / 120)), "units")
            else:
                canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        def _bind_mousewheel(_event):
            canvas.bind_all("<MouseWheel>", _on_mousewheel)

        def _unbind_mousewheel(_event):
            canvas.unbind_all("<MouseWheel>")

        canvas.bind("<Enter>", _bind_mousewheel)
        canvas.bind("<Leave>", _unbind_mousewheel)

    def log(self, msg: str):
        append_tagged_text(self.log_text, msg + "\n")
        self.log_text.see("end")
        self.root.update_idletasks()

    def clear_log(self):
        self.log_text.delete("1.0", "end")

    def set_progress(self, value: float, status: str):
        value = max(0.0, min(1.0, value))
        self.progress_value.set(value * 100.0)
        self.status_text.set(status)
        self.root.update_idletasks()

    def reset_progress(self):
        self.set_progress(0.0, "就绪")

    def select_input(self):
        path = filedialog.askopenfilename(
            title="选择输入 PCD",
            filetypes=[("PCD files", "*.pcd"), ("All files", "*.*")]
        )
        if path:
            self.input_path.set(path)
            base = os.path.splitext(os.path.basename(path))[0]
            if not self.out_dir.get():
                self.out_dir.set(os.path.join(os.path.dirname(path), f"{base}_tiles"))
            if not self.zip_path.get():
                self.zip_path.set(os.path.join(os.path.dirname(path), f"{base}_tiles.zip"))

    def select_out_dir(self):
        path = filedialog.askdirectory(title="选择输出目录")
        if path:
            self.out_dir.set(path)

    def select_zip(self):
        path = filedialog.asksaveasfilename(
            title="选择 zip 输出路径",
            defaultextension=".zip",
            filetypes=[("ZIP files", "*.zip"), ("All files", "*.*")]
        )
        if path:
            self.zip_path.set(path)

    def open_out_dir(self):
        path = self.out_dir.get().strip()
        if not path:
            messagebox.showwarning("提示", "输出目录为空")
            return
        if not os.path.isdir(path):
            messagebox.showwarning("提示", "输出目录不存在")
            return
        try:
            if os.name == "nt":
                os.startfile(path)
            else:
                messagebox.showinfo("提示", f"输出目录：{path}")
        except Exception as e:
            messagebox.showerror("错误", str(e))

    def validate_inputs(self):
        input_path = self.input_path.get().strip()
        out_dir = self.out_dir.get().strip()
        zip_path = self.zip_path.get().strip() if self.enable_zip.get() else ""

        if not input_path:
            raise RuntimeError("请选择输入 PCD 文件")
        if not os.path.isfile(input_path):
            raise RuntimeError("输入 PCD 文件不存在")
        if not out_dir:
            raise RuntimeError("请选择输出目录")

        try:
            tile_size = float(self.tile_size.get().strip())
            min_points = int(self.min_points.get().strip())
        except ValueError:
            raise RuntimeError("tile_size 或 最少点数 格式不正确")

        prefix = self.prefix.get().strip() or "tile_"
        metadata_name = self.metadata_name.get().strip() or "pointcloud_data_metadata.yaml"
        output_format = self.output_format.get().strip()

        return {
            "input_path": input_path,
            "out_dir": out_dir,
            "zip_path": zip_path,
            "tile_size": tile_size,
            "min_points": min_points,
            "prefix": prefix,
            "metadata_name": metadata_name,
            "output_format": output_format,
            "auto_clean_output": self.auto_clean_output.get(),
        }

    def start_preview(self):
        try:
            cfg = self.validate_inputs()
        except Exception as e:
            messagebox.showwarning("提示", str(e))
            return

        self.log("=" * 60)
        self.log(f"[INFO] 开始预扫描: {cfg['input_path']}")
        self.set_progress(0.0, "预扫描中")

        def worker():
            try:
                result = preview_pcd(
                    input_path=cfg["input_path"],
                    tile_size=cfg["tile_size"],
                    logger=lambda m: self.root.after(0, self.log, m),
                    progress_cb=lambda p, s: self.root.after(0, self.set_progress, p, s),
                )
                stats = result["stats"]
                preview_str = (
                    f"点数: {result['points']}\n"
                    f"X 范围: {stats['xmin']:.3f} ~ {stats['xmax']:.3f}\n"
                    f"Y 范围: {stats['ymin']:.3f} ~ {stats['ymax']:.3f}\n"
                    f"Z 范围: {stats['zmin']:.3f} ~ {stats['zmax']:.3f}\n"
                    f"预计 tile 数: {stats['estimated_tiles']}"
                )
                self.root.after(0, self.preview_text.set, preview_str)
                self.root.after(0, self.set_progress, 1.0, "预扫描完成")
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("错误", str(e)))
                self.root.after(0, self.reset_progress)

        threading.Thread(target=worker, daemon=True).start()

    def start_split(self):
        try:
            cfg = self.validate_inputs()
        except Exception as e:
            messagebox.showwarning("提示", str(e))
            return

        self.log("=" * 60)
        self.log(f"[INFO] 输入文件: {cfg['input_path']}")
        self.log(f"[INFO] 输出目录: {cfg['out_dir']}")
        self.log(f"[INFO] 输出格式: {cfg['output_format']}")
        self.log(f"[INFO] tile_size: {cfg['tile_size']}")
        self.log(f"[INFO] 最少点数: {cfg['min_points']}")
        self.log(f"[INFO] 自动清空输出目录: {cfg['auto_clean_output']}")
        if cfg["zip_path"]:
            self.log(f"[INFO] zip路径: {cfg['zip_path']}")

        self.set_progress(0.0, "开始处理")

        def worker():
            try:
                result = split_pcd(
                    input_path=cfg["input_path"],
                    out_dir=cfg["out_dir"],
                    tile_size=cfg["tile_size"],
                    prefix=cfg["prefix"],
                    metadata_name=cfg["metadata_name"],
                    min_points_per_tile=cfg["min_points"],
                    output_format=cfg["output_format"],
                    zip_path=cfg["zip_path"],
                    auto_clean_output=cfg["auto_clean_output"],
                    logger=lambda m: self.root.after(0, self.log, m),
                    progress_cb=lambda p, s: self.root.after(0, self.set_progress, p, s),
                )

                stats = result["stats"]
                preview_str = (
                    f"点数: {result['points']}\n"
                    f"X 范围: {stats['xmin']:.3f} ~ {stats['xmax']:.3f}\n"
                    f"Y 范围: {stats['ymin']:.3f} ~ {stats['ymax']:.3f}\n"
                    f"Z 范围: {stats['zmin']:.3f} ~ {stats['zmax']:.3f}\n"
                    f"预计 tile 数: {stats['estimated_tiles']}"
                )
                self.root.after(0, self.preview_text.set, preview_str)

                def done_msg():
                    msg = (
                        f"切图完成\n\n"
                        f"输出目录:\n{result['output_dir']}\n\n"
                        f"metadata:\n{result['metadata_path']}\n\n"
                        f"写出 tile 数: {result['tiles_written']}"
                    )
                    if result["zip_path"]:
                        msg += f"\n\nzip:\n{result['zip_path']}"
                    messagebox.showinfo("完成", msg)

                self.root.after(0, done_msg)
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("错误", str(e)))
                self.root.after(0, self.reset_progress)

        threading.Thread(target=worker, daemon=True).start()


# =========================
# CLI entry
# =========================

def run_cli():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", help="input .pcd")
    ap.add_argument("--out_dir", help="output tiles directory")
    ap.add_argument("--tile_size", type=float, default=20.0, help="tile size in meters")
    ap.add_argument("--prefix", default="tile_", help="tile file prefix")
    ap.add_argument("--metadata_name", default="pointcloud_data_metadata.yaml", help="metadata yaml filename")
    ap.add_argument("--zip", default="", help="optional: output zip file path")
    ap.add_argument("--min_points_per_tile", type=int, default=50, help="drop tiles with fewer points")
    ap.add_argument("--output_format", choices=["ascii", "binary"], default="ascii", help="tile output format")
    ap.add_argument("--auto_clean_output", action="store_true", help="auto clean old .pcd/.yaml/.zip in output dir")
    ap.add_argument("--gui", action="store_true", help="launch GUI")
    args = ap.parse_args()

    if args.gui or (not args.input and not args.out_dir):
        root = tk.Tk()
        App(root)
        root.mainloop()
        return

    if not args.input or not args.out_dir:
        raise RuntimeError("CLI 模式下必须提供 --input 和 --out_dir")

    split_pcd(
        input_path=args.input,
        out_dir=args.out_dir,
        tile_size=args.tile_size,
        prefix=args.prefix,
        metadata_name=args.metadata_name,
        min_points_per_tile=args.min_points_per_tile,
        output_format=args.output_format,
        zip_path=args.zip,
        auto_clean_output=args.auto_clean_output,
    )


if __name__ == "__main__":
    run_cli()
