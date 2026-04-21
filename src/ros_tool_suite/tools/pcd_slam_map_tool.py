#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import binascii
import math
import multiprocessing
import os
import queue
import struct
import tkinter as tk
import zlib
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from ros_tool_suite.shared_ui import (
    apply_suite_theme,
    make_card,
    style_text_widget,
    apply_log_tags,
    append_tagged_text,
)


UNKNOWN = 0
WALKABLE = 1
OBSTACLE = 2


def clamp(value, low, high):
    return max(low, min(high, value))


def parse_hex_color(text, fallback):
    text = text.strip()
    if not text:
        return fallback
    if text.startswith("#"):
        text = text[1:]
    if len(text) != 6:
        raise ValueError("颜色必须是 6 位十六进制，例如 #39FF14")
    return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))


def report_progress(progress_cb, percent, message):
    if progress_cb is not None:
        progress_cb(int(percent), message)


class ProgressTracker:
    def __init__(self, progress_cb=None):
        self.progress_cb = progress_cb
        self.total_units = 0
        self.completed_units = 0
        self.last_percent = -1
        self.message = ""

    def add_total(self, units):
        self.total_units += max(0, int(units))

    def set_message(self, message):
        self.message = message
        self.flush(force=True)

    def advance(self, units=1, message=None):
        if message is not None:
            self.message = message
        self.completed_units += max(0, int(units))
        self.flush()

    def flush(self, force=False):
        if self.progress_cb is None:
            return
        if self.total_units <= 0:
            percent = 0
        else:
            percent = min(99, int(self.completed_units * 100 / self.total_units))
        if force or percent != self.last_percent:
            self.last_percent = percent
            self.progress_cb(percent, self.message)


@dataclass
class GridParameters:
    resolution: float = 0.05
    clip_min_z: float = -1.0
    clip_max_z: float = 2.0
    walkable_min_z: float = -0.20
    walkable_max_z: float = 0.20
    obstacle_min_z: float = 0.25
    obstacle_max_z: float = 2.00
    ground_tolerance: float = 0.12
    min_points_per_cell: int = 1
    obstacle_inflate_radius: float = 0.10
    hole_fill_neighbors: int = 5
    overlay_smooth_radius: float = 0.00
    free_gray: int = 254
    obstacle_gray: int = 0
    walkable_color: tuple = (0x39, 0xFF, 0x14)
    obstacle_color: tuple = (0xFF, 0x5A, 0x36)
    occupied_thresh: float = 0.65
    free_thresh: float = 0.25
    negate: int = 0


@dataclass
class CellStats:
    count: int = 0
    min_z: float = math.inf
    max_z: float = -math.inf
    walkable_count: int = 0
    walkable_min_z: float = math.inf
    walkable_max_z: float = -math.inf
    obstacle_count: int = 0


@dataclass
class GridResult:
    width: int
    height: int
    origin_x: float
    origin_y: float
    resolution: float
    grid: bytearray
    obstacle_cells: int
    walkable_cells: int
    unknown_cells: int
    point_count: int


class PCDReader:
    def __init__(self, file_path):
        self.file_path = str(file_path)
        self.fields = []
        self.sizes = []
        self.types = []
        self.counts = []
        self.width = 0
        self.height = 0
        self.points = 0
        self.data_type = ""
        self.data_offset = 0
        self.point_step = 0
        self.offsets = {}

    def _read_header(self):
        with open(self.file_path, "rb") as f:
            while True:
                line = f.readline()
                if not line:
                    raise ValueError("PCD 头部不完整")
                decoded = line.decode("ascii", errors="ignore").strip()
                if not decoded or decoded.startswith("#"):
                    continue
                parts = decoded.split()
                key = parts[0].upper()
                values = parts[1:]
                if key == "FIELDS":
                    self.fields = values
                elif key == "SIZE":
                    self.sizes = [int(v) for v in values]
                elif key == "TYPE":
                    self.types = values
                elif key == "COUNT":
                    self.counts = [int(v) for v in values]
                elif key == "WIDTH":
                    self.width = int(values[0])
                elif key == "HEIGHT":
                    self.height = int(values[0])
                elif key == "POINTS":
                    self.points = int(values[0])
                elif key == "DATA":
                    self.data_type = values[0].lower()
                    self.data_offset = f.tell()
                    break

        if not self.fields or not self.sizes:
            raise ValueError("PCD 缺少 FIELDS 或 SIZE")
        if not self.counts:
            self.counts = [1] * len(self.fields)
        if "x" not in self.fields or "y" not in self.fields or "z" not in self.fields:
            raise ValueError("PCD 必须包含 x y z 字段")

        offset = 0
        for name, size, count in zip(self.fields, self.sizes, self.counts):
            self.offsets[name] = offset
            offset += size * count
        self.point_step = offset

    def iter_xyz(self):
        if not self.point_step:
            self._read_header()
        if self.data_type == "binary":
            yield from self._iter_xyz_binary()
        elif self.data_type == "ascii":
            yield from self._iter_xyz_ascii()
        else:
            raise ValueError(f"暂不支持的 PCD DATA 类型: {self.data_type}")

    def _iter_xyz_binary(self):
        x_offset = self.offsets["x"]
        y_offset = self.offsets["y"]
        z_offset = self.offsets["z"]
        step = self.point_step

        with open(self.file_path, "rb") as f:
            f.seek(self.data_offset)
            chunk_points = 32768
            chunk_size = step * chunk_points
            leftover = b""

            while True:
                block = f.read(chunk_size)
                if not block:
                    break
                data = leftover + block
                usable = (len(data) // step) * step
                if usable == 0:
                    leftover = data
                    continue
                for start in range(0, usable, step):
                    x = struct.unpack_from("<f", data, start + x_offset)[0]
                    y = struct.unpack_from("<f", data, start + y_offset)[0]
                    z = struct.unpack_from("<f", data, start + z_offset)[0]
                    yield x, y, z
                leftover = data[usable:]

    def _iter_xyz_ascii(self):
        x_index = self.fields.index("x")
        y_index = self.fields.index("y")
        z_index = self.fields.index("z")

        with open(self.file_path, "rb") as f:
            f.seek(self.data_offset)
            for raw_line in f:
                line = raw_line.decode("ascii", errors="ignore").strip()
                if not line:
                    continue
                parts = line.split()
                yield float(parts[x_index]), float(parts[y_index]), float(parts[z_index])


def compute_extent(reader, params, tracker=None):
    min_x = math.inf
    min_y = math.inf
    max_x = -math.inf
    max_y = -math.inf
    kept_points = 0
    total_points = max(1, reader.points or 1)
    report_step = max(1, total_points // 200)
    if tracker is not None:
        tracker.set_message("正在扫描点云范围")

    for processed, (x, y, z) in enumerate(reader.iter_xyz(), start=1):
        if z < params.clip_min_z or z > params.clip_max_z:
            pass
        else:
            kept_points += 1
            if x < min_x:
                min_x = x
            if y < min_y:
                min_y = y
            if x > max_x:
                max_x = x
            if y > max_y:
                max_y = y
        if tracker is not None and (processed % report_step == 0 or processed == total_points):
            tracker.advance(report_step if processed < total_points else total_points % report_step or report_step)

    if kept_points == 0:
        raise ValueError("截取高度范围内没有点，请调整 clip_min_z / clip_max_z")
    return min_x, min_y, max_x, max_y, kept_points


def build_grid(reader, params, tracker=None):
    min_x, min_y, max_x, max_y, point_count = compute_extent(reader, params, tracker)
    width = max(1, int(math.ceil((max_x - min_x) / params.resolution)) + 1)
    height = max(1, int(math.ceil((max_y - min_y) / params.resolution)) + 1)

    cells = {}
    total_points = max(1, reader.points or 1)
    report_step = max(1, total_points // 200)
    if tracker is not None:
        tracker.set_message("正在统计栅格高度")

    for processed, (x, y, z) in enumerate(reader.iter_xyz(), start=1):
        if z < params.clip_min_z or z > params.clip_max_z:
            pass
        else:
            gx = int((x - min_x) / params.resolution)
            gy = int((y - min_y) / params.resolution)
            gx = clamp(gx, 0, width - 1)
            gy = clamp(gy, 0, height - 1)
            idx = gy * width + gx
            cell = cells.get(idx)
            if cell is None:
                cell = CellStats()
                cells[idx] = cell
            cell.count += 1
            if z < cell.min_z:
                cell.min_z = z
            if z > cell.max_z:
                cell.max_z = z
            if params.walkable_min_z <= z <= params.walkable_max_z:
                cell.walkable_count += 1
                if z < cell.walkable_min_z:
                    cell.walkable_min_z = z
                if z > cell.walkable_max_z:
                    cell.walkable_max_z = z
            if params.obstacle_min_z <= z <= params.obstacle_max_z:
                cell.obstacle_count += 1
        if tracker is not None and (processed % report_step == 0 or processed == total_points):
            tracker.advance(report_step if processed < total_points else total_points % report_step or report_step)

    grid = bytearray([UNKNOWN]) * (width * height)
    walkable_cells = 0
    obstacle_cells = 0
    total_cells = max(1, len(cells))
    report_step = max(1, total_cells // 150)
    if tracker is not None:
        tracker.add_total(total_cells + width * height + height * 2 + 3)
        tracker.set_message("正在分类可行走区域和障碍物")

    for processed, (idx, cell) in enumerate(cells.items(), start=1):
        if cell.count < params.min_points_per_cell:
            pass
        else:
            has_walkable_band = (
                cell.walkable_count >= params.min_points_per_cell
                and (cell.walkable_max_z - cell.walkable_min_z) <= params.ground_tolerance
            )
            has_obstacle_band = cell.obstacle_count >= params.min_points_per_cell

            if has_obstacle_band:
                grid[idx] = OBSTACLE
                obstacle_cells += 1
            elif has_walkable_band:
                grid[idx] = WALKABLE
                walkable_cells += 1
        if tracker is not None and (processed % report_step == 0 or processed == total_cells):
            tracker.advance(report_step if processed < total_cells else total_cells % report_step or report_step)

    if tracker is not None:
        tracker.set_message("正在膨胀障碍物边界")
    obstacle_cells = inflate_obstacles(grid, width, height, params.obstacle_inflate_radius, params.resolution)
    if tracker is not None:
        tracker.advance(width * height)
        tracker.set_message("正在补齐可行走空洞")
    walkable_cells = fill_walkable_holes(grid, width, height, params.hole_fill_neighbors)
    if tracker is not None:
        tracker.advance(width * height)
    unknown_cells = width * height - walkable_cells - obstacle_cells

    return GridResult(
        width=width,
        height=height,
        origin_x=min_x,
        origin_y=min_y,
        resolution=params.resolution,
        grid=grid,
        obstacle_cells=obstacle_cells,
        walkable_cells=walkable_cells,
        unknown_cells=unknown_cells,
        point_count=point_count,
    )


def inflate_obstacles(grid, width, height, radius_m, resolution):
    if radius_m <= 0:
        return sum(1 for v in grid if v == OBSTACLE)
    radius_cells = int(math.ceil(radius_m / resolution))
    if radius_cells <= 0:
        return sum(1 for v in grid if v == OBSTACLE)

    original = [i for i, value in enumerate(grid) if value == OBSTACLE]
    for idx in original:
        x = idx % width
        y = idx // width
        for dy in range(-radius_cells, radius_cells + 1):
            for dx in range(-radius_cells, radius_cells + 1):
                if dx * dx + dy * dy > radius_cells * radius_cells:
                    continue
                nx = x + dx
                ny = y + dy
                if 0 <= nx < width and 0 <= ny < height:
                    nidx = ny * width + nx
                    grid[nidx] = OBSTACLE
    return sum(1 for v in grid if v == OBSTACLE)


def fill_walkable_holes(grid, width, height, min_neighbors):
    if min_neighbors <= 0:
        return sum(1 for v in grid if v == WALKABLE)

    pending = []
    for y in range(1, height - 1):
        for x in range(1, width - 1):
            idx = y * width + x
            if grid[idx] != UNKNOWN:
                continue
            walkable_neighbors = 0
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    value = grid[(y + dy) * width + (x + dx)]
                    if value == WALKABLE:
                        walkable_neighbors += 1
            if walkable_neighbors >= min_neighbors:
                pending.append(idx)
    for idx in pending:
        grid[idx] = WALKABLE
    return sum(1 for v in grid if v == WALKABLE)


def write_pgm(path, result, params, tracker=None):
    with open(path, "wb") as f:
        header = f"P5\n{result.width} {result.height}\n255\n".encode("ascii")
        f.write(header)
        total_rows = max(1, result.height)
        if tracker is not None:
            tracker.set_message("正在写出 PGM 地图")
        for y in range(result.height - 1, -1, -1):
            row_start = y * result.width
            row = bytearray(result.width)
            for x in range(result.width):
                cell = result.grid[row_start + x]
                if cell == OBSTACLE:
                    row[x] = params.obstacle_gray
                else:
                    row[x] = params.free_gray
            f.write(row)
            if tracker is not None:
                tracker.advance(1)


def build_greenway_overlay_mask(result, params):
    width = result.width
    height = result.height
    total = width * height
    smooth_cells = max(0, int(math.ceil(params.overlay_smooth_radius / params.resolution)))

    mask = bytearray(total)
    for idx, cell in enumerate(result.grid):
        if cell != OBSTACLE:
            mask[idx] = 1

    if smooth_cells > 0:
        mask = dilate_mask(mask, width, height, smooth_cells, result.grid)
        mask = erode_mask(mask, width, height, smooth_cells, result.grid)
    return mask


def dilate_mask(mask, width, height, radius_cells, grid):
    output = bytearray(mask)
    for idx, value in enumerate(mask):
        if not value:
            continue
        x = idx % width
        y = idx // width
        for dy in range(-radius_cells, radius_cells + 1):
            for dx in range(-radius_cells, radius_cells + 1):
                if dx * dx + dy * dy > radius_cells * radius_cells:
                    continue
                nx = x + dx
                ny = y + dy
                if 0 <= nx < width and 0 <= ny < height:
                    nidx = ny * width + nx
                    if grid[nidx] != OBSTACLE:
                        output[nidx] = 1
    return output


def erode_mask(mask, width, height, radius_cells, grid):
    output = bytearray(mask)
    for idx, value in enumerate(mask):
        if not value:
            continue
        x = idx % width
        y = idx // width
        keep = True
        for dy in range(-radius_cells, radius_cells + 1):
            if not keep:
                break
            for dx in range(-radius_cells, radius_cells + 1):
                if dx * dx + dy * dy > radius_cells * radius_cells:
                    continue
                nx = x + dx
                ny = y + dy
                if not (0 <= nx < width and 0 <= ny < height):
                    keep = False
                    break
                nidx = ny * width + nx
                if grid[nidx] == OBSTACLE or not mask[nidx]:
                    keep = False
                    break
        if not keep:
            output[idx] = 0
    return output


def _png_chunk(chunk_type, data):
    length = struct.pack(">I", len(data))
    crc = struct.pack(">I", binascii.crc32(chunk_type + data) & 0xFFFFFFFF)
    return length + chunk_type + data + crc


def write_rgba_png(path, width, height, pixel_fn, tracker=None, stage_message=None):
    raw = bytearray()
    total_rows = max(1, height)
    if tracker is not None:
        tracker.set_message(stage_message or "正在生成 PNG")
    for y in range(height - 1, -1, -1):
        raw.append(0)
        for x in range(width):
            raw.extend(pixel_fn(x, y))
        if tracker is not None:
            tracker.advance(1)

    compressed = zlib.compress(bytes(raw), level=9)
    if tracker is not None:
        tracker.set_message("正在压缩 PNG")
        tracker.advance(1)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    png = bytearray(b"\x89PNG\r\n\x1a\n")
    png.extend(_png_chunk(b"IHDR", ihdr))
    png.extend(_png_chunk(b"IDAT", compressed))
    png.extend(_png_chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(png)
    if tracker is not None:
        tracker.advance(1)


def write_walkable_overlay_png(path, result, params, overlay_mask=None, tracker=None):
    if overlay_mask is None:
        overlay_mask = build_greenway_overlay_mask(result, params)
    r, g, b = params.walkable_color

    def pixel_fn(x, y):
        idx = y * result.width + x
        if overlay_mask[idx]:
            return (r, g, b, 255)
        return (0, 0, 0, 0)

    write_rgba_png(
        path,
        result.width,
        result.height,
        pixel_fn,
        tracker=tracker,
        stage_message="正在生成绿道 PNG",
    )


def write_walkable_preview_png(path, result, params, overlay_mask=None, max_side=1200):
    if overlay_mask is None:
        overlay_mask = build_greenway_overlay_mask(result, params)
    scale = max(1, int(math.ceil(max(result.width, result.height) / max_side)))
    preview_width = max(1, int(math.ceil(result.width / scale)))
    preview_height = max(1, int(math.ceil(result.height / scale)))
    r, g, b = params.walkable_color

    def pixel_fn(px, py):
        src_x = min(result.width - 1, px * scale)
        src_y = min(result.height - 1, py * scale)
        idx = src_y * result.width + src_x
        if overlay_mask[idx]:
            return (r, g, b, 255)
        return (0, 0, 0, 0)

    write_rgba_png(path, preview_width, preview_height, pixel_fn)


def write_yaml(path, pgm_name, result, params):
    yaml_text = (
        f"image: {pgm_name}\n"
        f"mode: trinary\n"
        f"resolution: {result.resolution:.12f}\n"
        f"origin: [{result.origin_x:.12f}, {result.origin_y:.12f}, 0.0]\n"
        f"negate: {params.negate}\n"
        f"occupied_thresh: {params.occupied_thresh:.6f}\n"
        f"free_thresh: {params.free_thresh:.6f}\n"
    )
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(yaml_text)


def export_maps(pcd_path, output_dir, base_name, params, progress_cb=None):
    reader = PCDReader(pcd_path)
    tracker = ProgressTracker(progress_cb)
    total_points = max(1, reader.points or 0)
    if total_points <= 0:
        reader._read_header()
        total_points = max(1, reader.points or 1)
    tracker.add_total(total_points * 2)
    tracker.set_message("准备读取点云")
    result = build_grid(reader, params, tracker)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    pgm_path = output_dir / f"{base_name}.pgm"
    yaml_path = output_dir / f"{base_name}.yaml"
    color_path = output_dir / f"{base_name}_walkable.png"
    preview_path = output_dir / f"{base_name}_walkable_preview.png"
    overlay_mask = build_greenway_overlay_mask(result, params)

    write_pgm(pgm_path, result, params, tracker)
    tracker.set_message("正在写出 YAML 配置")
    write_yaml(yaml_path, pgm_path.name, result, params)
    tracker.advance(1)
    tracker.set_message("准备生成绿道 PNG")
    write_walkable_overlay_png(color_path, result, params, overlay_mask=overlay_mask, tracker=tracker)
    tracker.set_message("正在生成预览图")
    write_walkable_preview_png(preview_path, result, params, overlay_mask=overlay_mask)
    tracker.set_message("正在整理输出结果")
    tracker.advance(1)

    return {
        "pgm_path": str(pgm_path),
        "yaml_path": str(yaml_path),
        "color_path": str(color_path),
        "preview_path": str(preview_path),
        "width": result.width,
        "height": result.height,
        "origin_x": result.origin_x,
        "origin_y": result.origin_y,
        "point_count": result.point_count,
        "walkable_cells": result.walkable_cells,
        "obstacle_cells": result.obstacle_cells,
        "unknown_cells": result.unknown_cells,
    }


def export_maps_worker(queue, pcd_path, output_dir, base_name, params):
    def progress_cb(percent, message):
        queue.put(("progress", percent, message))

    try:
        info = export_maps(pcd_path, output_dir, base_name, params, progress_cb)
        queue.put(("ok", info, pcd_path))
    except Exception as exc:
        queue.put(("error", str(exc), pcd_path))


def add_labeled_entry(parent, row, label, var, width=14):
    ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=4, pady=4)
    ttk.Entry(parent, textvariable=var, width=width, style="Suite.TEntry").grid(row=row, column=1, sticky="ew", padx=4, pady=4)


class MapToolApp:
    def __init__(self, root, embedded=False):
        self.root = root
        self.embedded = embedded
        if not embedded and isinstance(root, (tk.Tk, tk.Toplevel)):
            self.root.title("PCD SLAM 地图生成工具")
            self.root.geometry("1180x760")
        self.preview_path = None
        self.preview_image = None
        self.worker_process = None
        self.worker_queue = None
        self.worker_result = None
        self.progress_value = tk.DoubleVar(value=0.0)
        self.progress_message = "进度: 0%"
        self._resize_after_id = None

        self.pcd_path = tk.StringVar()
        self.output_dir = tk.StringVar(value=str(Path.cwd() / "output"))
        self.base_name = tk.StringVar(value="map")

        self.resolution = tk.DoubleVar(value=0.05)
        self.clip_min_z = tk.DoubleVar(value=-1.0)
        self.clip_max_z = tk.DoubleVar(value=2.0)
        self.walkable_min_z = tk.DoubleVar(value=-0.20)
        self.walkable_max_z = tk.DoubleVar(value=0.20)
        self.obstacle_min_z = tk.DoubleVar(value=0.25)
        self.obstacle_max_z = tk.DoubleVar(value=2.0)
        self.ground_tolerance = tk.DoubleVar(value=0.12)
        self.min_points_per_cell = tk.IntVar(value=1)
        self.obstacle_inflate_radius = tk.DoubleVar(value=0.10)
        self.hole_fill_neighbors = tk.IntVar(value=5)
        self.overlay_smooth_radius = tk.DoubleVar(value=0.00)

        self.walkable_color = tk.StringVar(value="#39FF14")
        self.obstacle_color = tk.StringVar(value="#FF5A36")

        self.status_text = tk.StringVar(value="请选择 PCD 文件。")

        apply_suite_theme(root)
        self._build_ui()

    def _build_ui(self):
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

        shell = ttk.Frame(canvas, style="App.TFrame", padding=12)
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(3, weight=1)
        shell_window = canvas.create_window((0, 0), window=shell, anchor="nw")

        def on_shell_configure(_event):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def on_canvas_configure(event):
            if self._resize_after_id is not None:
                canvas.after_cancel(self._resize_after_id)

            def apply_resize():
                target_width = max(event.width - 4, 980)
                canvas.itemconfigure(shell_window, width=target_width)
                self._update_body_layout(target_width)
                canvas.configure(scrollregion=canvas.bbox("all"))
                self._resize_after_id = None

            self._resize_after_id = canvas.after(40, apply_resize)

        shell.bind("<Configure>", on_shell_configure)
        canvas.bind("<Configure>", on_canvas_configure)

        ttk.Label(shell, text="PCD 转 SLAM 地图", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(shell, text="统一视觉风格，保留现有地图生成逻辑。", style="SubTitle.TLabel").grid(row=1, column=0, sticky="w", pady=(2, 12))

        top_card, top = make_card(shell, padding=14)
        top_card.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        top.columnconfigure(1, weight=1)

        ttk.Label(top, text="PCD 文件").grid(row=0, column=0, sticky="w", padx=4, pady=4)
        ttk.Entry(top, textvariable=self.pcd_path, style="Suite.TEntry").grid(row=0, column=1, sticky="ew", padx=4, pady=4)
        ttk.Button(top, text="选择", command=self.choose_pcd, style="Secondary.TButton").grid(row=0, column=2, padx=4, pady=4)

        ttk.Label(top, text="输出目录").grid(row=1, column=0, sticky="w", padx=4, pady=4)
        ttk.Entry(top, textvariable=self.output_dir, style="Suite.TEntry").grid(row=1, column=1, sticky="ew", padx=4, pady=4)
        ttk.Button(top, text="选择", command=self.choose_output_dir, style="Secondary.TButton").grid(row=1, column=2, padx=4, pady=4)

        ttk.Label(top, text="输出名称").grid(row=2, column=0, sticky="w", padx=4, pady=4)
        ttk.Entry(top, textvariable=self.base_name, width=24, style="Suite.TEntry").grid(row=2, column=1, sticky="w", padx=4, pady=4)
        self.generate_button = ttk.Button(top, text="生成地图", command=self.generate, style="Primary.TButton")
        self.generate_button.grid(row=2, column=2, padx=4, pady=4)

        body_card, body = make_card(shell, padding=10)
        body_card.grid(row=3, column=0, sticky="nsew")
        body_card.grid_rowconfigure(0, weight=1)
        body_card.grid_columnconfigure(0, weight=1)
        self.body = body

        left_card, left = make_card(body, padding=12)
        right_card, right = make_card(body, padding=12)
        self.left_card = left_card
        self.right_card = right_card
        self._update_body_layout(1400)

        left.columnconfigure(1, weight=1)
        ttk.Label(left, text="参数", style="CardTitle.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 6)
        )

        add_labeled_entry(left, 1, "分辨率(m)", self.resolution)
        add_labeled_entry(left, 2, "截取最小Z", self.clip_min_z)
        add_labeled_entry(left, 3, "截取最大Z", self.clip_max_z)
        add_labeled_entry(left, 4, "可行走最小Z", self.walkable_min_z)
        add_labeled_entry(left, 5, "可行走最大Z", self.walkable_max_z)
        add_labeled_entry(left, 6, "障碍最小Z", self.obstacle_min_z)
        add_labeled_entry(left, 7, "障碍最大Z", self.obstacle_max_z)
        add_labeled_entry(left, 8, "地面容差", self.ground_tolerance)
        add_labeled_entry(left, 9, "每格最小点数", self.min_points_per_cell)
        add_labeled_entry(left, 10, "障碍膨胀(m)", self.obstacle_inflate_radius)
        add_labeled_entry(left, 11, "孔洞填补邻居数", self.hole_fill_neighbors)
        add_labeled_entry(left, 12, "绿道平滑(m)", self.overlay_smooth_radius)
        add_labeled_entry(left, 13, "可行走颜色", self.walkable_color)
        add_labeled_entry(left, 14, "障碍颜色", self.obstacle_color)

        tips = (
            "分类规则:\n"
            "1. 点先按 clip_min_z ~ clip_max_z 截取。\n"
            "2. 落在 walkable_min_z ~ walkable_max_z 且高度起伏不超过 ground_tolerance 的格子判为可行走。\n"
            "3. 落在 obstacle_min_z ~ obstacle_max_z 的格子判为障碍。\n"
            "4. 当前版本仅区分可行走和障碍，未单独输出未知区域。\n\n"
            "绿道图输出为透明 PNG，默认直接按 PGM 白区生成；如需略微圆滑边缘，可调绿道平滑。"
        )
        ttk.Label(left, text=tips, justify="left", wraplength=320, style="Body.TLabel").grid(
            row=15, column=0, columnspan=2, sticky="w", pady=(12, 0)
        )

        right.rowconfigure(1, weight=0)
        right.rowconfigure(3, weight=1)
        right.columnconfigure(0, weight=1)
        ttk.Label(right, text="输出信息", style="CardTitle.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 6)
        )
        self.result_box = tk.Text(right, height=6, wrap="word")
        self.result_box.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        self.result_box.insert("1.0", "输出信息会显示在这里。\n")
        self.result_box.configure(state="disabled")
        style_text_widget(self.result_box, height=6)
        apply_log_tags(self.result_box)

        ttk.Label(right, text="预览", style="CardTitle.TLabel").grid(
            row=2, column=0, sticky="w", pady=(0, 6)
        )
        self.preview_label = ttk.Label(
            right,
            text="生成后会加载导出的彩色地图预览",
            anchor="center",
            relief="solid",
            padding=12,
        )
        self.preview_label.grid(row=3, column=0, sticky="nsew", pady=(0, 4))

        self.progress = ttk.Progressbar(
            right,
            mode="determinate",
            maximum=100,
            variable=self.progress_value,
            style="Suite.Horizontal.TProgressbar",
        )
        self.progress.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        self.progress_label = ttk.Label(right, text="进度: 0%")
        self.progress_label.grid(row=5, column=0, sticky="w", pady=(6, 0))

        status = ttk.Label(shell, textvariable=self.status_text, anchor="w", style="SubTitle.TLabel")
        status.grid(row=4, column=0, sticky="ew", pady=(8, 0))

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

    def _update_body_layout(self, width):
        body = self.body
        left_card = self.left_card
        right_card = self.right_card

        for col in range(2):
            body.grid_columnconfigure(col, weight=0, minsize=0)
        for row in range(2):
            body.grid_rowconfigure(row, weight=0, minsize=0)

        left_card.grid_forget()
        right_card.grid_forget()

        if width < 1280:
            left_card.grid(row=0, column=0, sticky="ew", padx=0, pady=(0, 8))
            right_card.grid(row=1, column=0, sticky="nsew")
            body.grid_columnconfigure(0, weight=1, minsize=0)
            body.grid_rowconfigure(1, weight=1, minsize=760)
        else:
            left_card.grid(row=0, column=0, sticky="nsw", padx=(0, 8))
            right_card.grid(row=0, column=1, sticky="nsew")
            body.grid_columnconfigure(0, weight=0, minsize=360)
            body.grid_columnconfigure(1, weight=1, minsize=920)
            body.grid_rowconfigure(0, weight=1, minsize=760)

    def choose_pcd(self):
        path = filedialog.askopenfilename(
            title="选择 PCD 文件",
            filetypes=[("PCD Files", "*.pcd"), ("All Files", "*.*")],
        )
        if path:
            self.pcd_path.set(path)
            if not self.base_name.get().strip():
                self.base_name.set(Path(path).stem)
            self.status_text.set("已选择 PCD 文件。")

    def choose_output_dir(self):
        path = filedialog.askdirectory(title="选择输出目录")
        if path:
            self.output_dir.set(path)
            self.status_text.set("已选择输出目录。")

    def collect_params(self):
        return GridParameters(
            resolution=float(self.resolution.get()),
            clip_min_z=float(self.clip_min_z.get()),
            clip_max_z=float(self.clip_max_z.get()),
            walkable_min_z=float(self.walkable_min_z.get()),
            walkable_max_z=float(self.walkable_max_z.get()),
            obstacle_min_z=float(self.obstacle_min_z.get()),
            obstacle_max_z=float(self.obstacle_max_z.get()),
            ground_tolerance=float(self.ground_tolerance.get()),
            min_points_per_cell=int(self.min_points_per_cell.get()),
            obstacle_inflate_radius=float(self.obstacle_inflate_radius.get()),
            hole_fill_neighbors=int(self.hole_fill_neighbors.get()),
            overlay_smooth_radius=float(self.overlay_smooth_radius.get()),
            walkable_color=parse_hex_color(self.walkable_color.get(), (0x39, 0xFF, 0x14)),
            obstacle_color=parse_hex_color(self.obstacle_color.get(), (0xFF, 0x5A, 0x36)),
        )

    def append_result(self, text):
        self.result_box.configure(state="normal")
        self.result_box.delete("1.0", "end")
        lines = text.splitlines(True)
        for line in lines:
            if line.strip() == "输出完成":
                self.result_box.insert("end", line, "heading")
            else:
                append_tagged_text(self.result_box, line)
        self.result_box.configure(state="disabled")

    def load_preview(self, ppm_path):
        image = tk.PhotoImage(file=ppm_path)
        max_side = 840
        factor = max(1, math.ceil(max(image.width(), image.height()) / max_side))
        if factor > 1:
            image = image.subsample(factor, factor)
        self.preview_image = image
        self.preview_label.configure(image=self.preview_image, text="")

    def maybe_load_preview(self, image_path, width, height):
        self.load_preview(image_path)

    def set_busy(self, busy):
        state = "disabled" if busy else "normal"
        self.generate_button.configure(state=state)
        if busy:
            self.progress_message = "进度: 0%"
            self.progress_value.set(0)
            self.progress_label.configure(text=self.progress_message)
        else:
            pass

    def update_progress(self, percent, message):
        percent = max(0, min(99, int(percent)))
        self.progress_value.set(percent)
        self.progress_message = f"进度: {percent}%"
        self.progress_label.configure(text=self.progress_message)
        if message:
            self.status_text.set(message)

    def _poll_worker(self):
        if self.worker_process and self.worker_process.is_alive():
            if self.worker_queue is not None:
                while True:
                    try:
                        message = self.worker_queue.get_nowait()
                    except queue.Empty:
                        break
                    if message[0] == "progress":
                        _, percent, text = message
                        self.update_progress(percent, text)
                    else:
                        self.worker_result = message
            self.root.after(150, self._poll_worker)
            return

        self.set_busy(False)
        if self.worker_queue is not None:
            while True:
                try:
                    message = self.worker_queue.get_nowait()
                except queue.Empty:
                    break
                if message[0] == "progress":
                    _, percent, text = message
                    self.update_progress(percent, text)
                else:
                    self.worker_result = message

        result = self.worker_result
        if self.worker_process is not None:
            self.worker_process.join(timeout=0.1)
        self.worker_process = None
        self.worker_queue = None
        self.worker_result = None
        if not result:
            self.status_text.set("生成失败。")
            messagebox.showerror("生成失败", "后台任务异常结束，没有返回结果。")
            return

        kind, payload, pcd_path = result
        if kind == "error":
            self.status_text.set("生成失败。")
            messagebox.showerror("生成失败", str(payload))
            return

        info = payload
        self.progress_value.set(100)
        self.progress_message = "进度: 100%"
        self.progress_label.configure(text=self.progress_message)
        self.status_text.set("处理完成")
        preview_path = info.get("preview_path") or info["color_path"]
        self.maybe_load_preview(preview_path, info["width"], info["height"])
        result_text = (
            f"输出完成\n"
            f"PCD: {pcd_path}\n"
            f"PGM: {info['pgm_path']}\n"
            f"YAML: {info['yaml_path']}\n"
            f"彩图: {info['color_path']}\n\n"
            f"尺寸: {info['width']} x {info['height']}\n"
            f"origin: [{info['origin_x']:.4f}, {info['origin_y']:.4f}, 0.0]\n"
            f"参与栅格化点数: {info['point_count']}\n"
            f"可行走格: {info['walkable_cells']}\n"
            f"障碍格: {info['obstacle_cells']}\n"
            f"未分类格: {info['unknown_cells']}\n"
        )
        self.append_result(result_text)
        self.status_text.set("地图生成成功。")

    def generate(self):
        if self.worker_process and self.worker_process.is_alive():
            self.status_text.set("地图仍在生成中，请等待当前任务完成。")
            return

        pcd_path = self.pcd_path.get().strip()
        output_dir = self.output_dir.get().strip()
        base_name = self.base_name.get().strip() or "map"

        if not pcd_path:
            messagebox.showerror("缺少文件", "请先选择 PCD 文件。")
            return
        if not os.path.exists(pcd_path):
            messagebox.showerror("文件不存在", f"找不到文件:\n{pcd_path}")
            return

        try:
            params = self.collect_params()
        except Exception as exc:
            messagebox.showerror("参数错误", str(exc))
            return

        self.status_text.set("正在生成地图，请稍候...")
        self.set_busy(True)
        self.worker_result = None
        ctx = multiprocessing.get_context("spawn")
        self.worker_queue = ctx.Queue()
        self.worker_process = ctx.Process(
            target=export_maps_worker,
            args=(self.worker_queue, pcd_path, output_dir, base_name, params),
            daemon=True,
        )
        self.worker_process.start()
        self.root.after(150, self._poll_worker)


def build_arg_parser():
    parser = argparse.ArgumentParser(description="从 PCD 生成 SLAM 用 PGM/YAML 和彩色可行走区域图")
    parser.add_argument("--pcd", help="输入 PCD 文件路径")
    parser.add_argument("--output-dir", default="output", help="输出目录")
    parser.add_argument("--base-name", default="map", help="输出文件名前缀")
    parser.add_argument("--resolution", type=float, default=0.05, help="地图分辨率，单位米")
    parser.add_argument("--clip-min-z", type=float, default=-1.0, help="截取最小高度")
    parser.add_argument("--clip-max-z", type=float, default=2.0, help="截取最大高度")
    parser.add_argument("--walkable-min-z", type=float, default=-0.20, help="可行走区域最小高度")
    parser.add_argument("--walkable-max-z", type=float, default=0.20, help="可行走区域最大高度")
    parser.add_argument("--obstacle-min-z", type=float, default=0.25, help="障碍区域最小高度")
    parser.add_argument("--obstacle-max-z", type=float, default=2.0, help="障碍区域最大高度")
    parser.add_argument("--ground-tolerance", type=float, default=0.12, help="单格地面高度容差")
    parser.add_argument("--min-points-per-cell", type=int, default=1, help="单格最少点数")
    parser.add_argument("--obstacle-inflate-radius", type=float, default=0.10, help="障碍膨胀半径")
    parser.add_argument("--hole-fill-neighbors", type=int, default=5, help="未知格填补为可行走所需邻居数")
    parser.add_argument("--overlay-smooth-radius", type=float, default=0.00, help="绿道平滑半径")
    parser.add_argument("--walkable-color", default="#39FF14", help="可行走区域颜色")
    parser.add_argument("--obstacle-color", default="#FF5A36", help="障碍区域颜色")
    parser.add_argument("--gui", action="store_true", help="启动图形界面")
    return parser


def run_cli(args):
    if not args.pcd:
        raise ValueError("命令行模式下必须提供 --pcd")
    params = GridParameters(
        resolution=args.resolution,
        clip_min_z=args.clip_min_z,
        clip_max_z=args.clip_max_z,
        walkable_min_z=args.walkable_min_z,
        walkable_max_z=args.walkable_max_z,
        obstacle_min_z=args.obstacle_min_z,
        obstacle_max_z=args.obstacle_max_z,
        ground_tolerance=args.ground_tolerance,
        min_points_per_cell=args.min_points_per_cell,
        obstacle_inflate_radius=args.obstacle_inflate_radius,
        hole_fill_neighbors=args.hole_fill_neighbors,
        overlay_smooth_radius=args.overlay_smooth_radius,
        walkable_color=parse_hex_color(args.walkable_color, (0x39, 0xFF, 0x14)),
        obstacle_color=parse_hex_color(args.obstacle_color, (0xFF, 0x5A, 0x36)),
    )
    info = export_maps(args.pcd, args.output_dir, args.base_name, params)
    for key in (
        "pgm_path",
        "yaml_path",
        "color_path",
        "width",
        "height",
        "origin_x",
        "origin_y",
        "point_count",
        "walkable_cells",
        "obstacle_cells",
        "unknown_cells",
    ):
        print(f"{key}: {info[key]}")


def main():
    parser = build_arg_parser()
    args = parser.parse_args()
    if args.gui or not args.pcd:
        root = tk.Tk()
        app = MapToolApp(root)
        if args.pcd:
            app.pcd_path.set(args.pcd)
        root.mainloop()
    else:
        run_cli(args)


if __name__ == "__main__":
    main()
