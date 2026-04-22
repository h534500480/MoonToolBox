#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""旧桌面版 Costmap 回放工具。

该模块解析 ROS costmap YAML，使用 Tkinter + Matplotlib 回放并导出图像。当前
Web 主线已有后端 Costmap 处理服务，后续新增回放或导出能力应优先放到
`backend/app/services/costmap_playback.py` 或 C++ 感知模块。
"""

import sys
import traceback
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from ros_tool_suite.shared_ui import apply_suite_theme, make_card

import matplotlib
matplotlib.use("TkAgg")

from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.animation import FuncAnimation, PillowWriter
from matplotlib.patches import Rectangle


@dataclass
class CostmapFrame:
    """单帧 Costmap 数据。

    `grid` 保存二维代价值矩阵，其余字段来自 ROS OccupancyGrid/Costmap YAML。
    """

    source: str
    index: int
    stamp_sec: int
    stamp_nanosec: int
    frame_id: str
    width: int
    height: int
    resolution: float
    origin_x: float
    origin_y: float
    grid: np.ndarray

    @property
    def stamp_float(self) -> float:
        return float(self.stamp_sec) + float(self.stamp_nanosec) * 1e-9


def parse_one_doc(doc: dict, source: str, index: int):
    if not isinstance(doc, dict):
        return None
    if "info" not in doc or "data" not in doc:
        return None

    info = doc["info"]
    header = doc.get("header", {})
    stamp = header.get("stamp", {})
    origin = info.get("origin", {}).get("position", {})

    width = int(info["width"])
    height = int(info["height"])
    resolution = float(info["resolution"])
    data = np.array(doc["data"], dtype=float)

    expected = width * height
    if data.size != expected:
        raise ValueError(
            f"{source} 第 {index + 1} 帧尺寸不对: data={data.size}, width*height={expected}"
        )

    grid = data.reshape((height, width))

    return CostmapFrame(
        source=source,
        index=index,
        stamp_sec=int(stamp.get("sec", 0)),
        stamp_nanosec=int(stamp.get("nanosec", 0)),
        frame_id=str(header.get("frame_id", "")),
        width=width,
        height=height,
        resolution=resolution,
        origin_x=float(origin.get("x", 0.0)),
        origin_y=float(origin.get("y", 0.0)),
        grid=grid,
    )


def load_frames_from_yaml(path: Path):
    """从 YAML 文件读取一组 Costmap 帧。"""
    frames = []
    with open(path, "r", encoding="utf-8") as f:
        docs = list(yaml.safe_load_all(f))
    for i, doc in enumerate(docs):
        frame = parse_one_doc(doc, str(path), i)
        if frame is not None:
            frames.append(frame)
    return frames


class CostmapPlayerPage(ttk.Frame):
    """旧桌面版 Costmap 回放页面。

    负责加载 YAML、播放帧序列、显示统计信息并导出 GIF/PNG。Web 主线的处理
    逻辑位于 `backend/app/services/costmap_playback.py`。
    """

    def __init__(self, master, embedded=False):
        super().__init__(master)
        self.root = master
        self.embedded = embedded
        if not embedded and isinstance(master, (tk.Tk, tk.Toplevel)):
            master.title("Costmap GUI Player")
            master.geometry("1320x920")

        self.frames = []
        self.current_idx = 0
        self.playing = False
        self.play_job = None

        self.file_var = tk.StringVar()
        self.status_var = tk.StringVar(value="请选择 costmap YAML 文件")
        self.info_var = tk.StringVar(value="尚未加载")
        self.fps_var = tk.StringVar(value="2.0")

        self.lethal_threshold_var = tk.StringVar(value="99")
        self.fp_len_var = tk.StringVar(value="0.70")
        self.fp_wid_var = tk.StringVar(value="0.40")

        self.show_lethal_var = tk.BooleanVar(value=True)
        self.show_fp_var = tk.BooleanVar(value=True)

        self.lethal_overlay = None
        self.footprint_patch = None

        apply_suite_theme(master)
        self.build_ui()
        self.build_plot()

    def build_ui(self):
        self.shell = ttk.Frame(self, style="App.TFrame", padding=12)
        self.shell.pack(fill=tk.BOTH, expand=True)

        ttk.Label(self.shell, text="Costmap 播放器", style="Title.TLabel").pack(anchor="w")
        ttk.Label(self.shell, text="统一卡片风格外观，保留回放和导出逻辑。", style="SubTitle.TLabel").pack(anchor="w", pady=(2, 12))

        top_card, top = make_card(self.shell, padding=14)
        top_card.pack(side=tk.TOP, fill=tk.X, pady=(0, 10))

        ttk.Label(top, text="文件:").pack(side=tk.LEFT)
        ttk.Entry(top, textvariable=self.file_var, width=90, style="Suite.TEntry").pack(
            side=tk.LEFT, padx=6, fill=tk.X, expand=True
        )
        ttk.Button(top, text="选择文件", command=self.choose_file, style="Secondary.TButton").pack(side=tk.LEFT, padx=4)
        ttk.Button(top, text="加载", command=self.load_file, style="Primary.TButton").pack(side=tk.LEFT, padx=4)

        ctrl_card, ctrl = make_card(self.shell, padding=14)
        ctrl_card.pack(side=tk.TOP, fill=tk.X, pady=(0, 10))

        ttk.Button(ctrl, text="播放", command=self.play, style="Primary.TButton").pack(side=tk.LEFT, padx=3)
        ttk.Button(ctrl, text="暂停", command=self.pause, style="Secondary.TButton").pack(side=tk.LEFT, padx=3)
        ttk.Button(ctrl, text="上一帧", command=self.prev_frame, style="Soft.TButton").pack(side=tk.LEFT, padx=3)
        ttk.Button(ctrl, text="下一帧", command=self.next_frame, style="Soft.TButton").pack(side=tk.LEFT, padx=3)
        ttk.Button(ctrl, text="导出 GIF", command=self.export_gif, style="Secondary.TButton").pack(side=tk.LEFT, padx=10)
        ttk.Button(ctrl, text="导出 PNG 序列", command=self.export_pngs, style="Soft.TButton").pack(side=tk.LEFT, padx=3)

        ttk.Label(ctrl, text="FPS:").pack(side=tk.LEFT, padx=(20, 4))
        ttk.Entry(ctrl, textvariable=self.fps_var, width=6, style="Suite.TEntry").pack(side=tk.LEFT)

        ttk.Label(ctrl, text="Lethal阈值:").pack(side=tk.LEFT, padx=(12, 4))
        ttk.Entry(ctrl, textvariable=self.lethal_threshold_var, width=6, style="Suite.TEntry").pack(side=tk.LEFT)

        ttk.Checkbutton(
            ctrl, text="显示Lethal",
            variable=self.show_lethal_var,
            command=self.refresh_current,
            style="Suite.TCheckbutton",
        ).pack(side=tk.LEFT, padx=(12, 4))

        ttk.Checkbutton(
            ctrl, text="显示Footprint",
            variable=self.show_fp_var,
            command=self.refresh_current,
            style="Suite.TCheckbutton",
        ).pack(side=tk.LEFT, padx=(4, 4))

        ttk.Label(ctrl, text="长(m):").pack(side=tk.LEFT, padx=(12, 4))
        ttk.Entry(ctrl, textvariable=self.fp_len_var, width=6, style="Suite.TEntry").pack(side=tk.LEFT)

        ttk.Label(ctrl, text="宽(m):").pack(side=tk.LEFT, padx=(8, 4))
        ttk.Entry(ctrl, textvariable=self.fp_wid_var, width=6, style="Suite.TEntry").pack(side=tk.LEFT)

        self.scale = ttk.Scale(ctrl, from_=0, to=0, orient=tk.HORIZONTAL, command=self.on_scale)
        self.scale.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=12)

        self.frame_label = ttk.Label(ctrl, text="0 / 0")
        self.frame_label.pack(side=tk.LEFT, padx=8)

        info_card, info = make_card(self.shell, padding=14)
        info_card.pack(side=tk.TOP, fill=tk.X, pady=(0, 10))

        ttk.Label(info, textvariable=self.status_var).pack(side=tk.TOP, anchor="w")
        ttk.Label(info, textvariable=self.info_var, justify=tk.LEFT).pack(side=tk.TOP, anchor="w")

    def build_plot(self):
        self.fig = Figure(figsize=(8.5, 8.2), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.ax.set_title("Costmap")
        self.ax.set_xlabel("x (m)")
        self.ax.set_ylabel("y (m)")

        dummy = np.zeros((10, 10), dtype=float)
        self.im = self.ax.imshow(dummy, origin="lower", interpolation="nearest", vmin=0, vmax=100)
        self.robot_dot, = self.ax.plot(
            [5], [5], marker="x", markersize=10, markeredgewidth=2, linestyle="None"
        )
        self.fig.colorbar(self.im, ax=self.ax, label="cost")

        plot_card, plot_host = make_card(self.shell, padding=10)
        plot_card.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.canvas = FigureCanvasTkAgg(self.fig, master=plot_host)
        self.canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.canvas.draw()

    def choose_file(self):
        path = filedialog.askopenfilename(
            title="选择 costmap YAML 文件",
            filetypes=[("YAML files", "*.yaml *.yml"), ("All files", "*.*")]
        )
        if path:
            self.file_var.set(path)

    def load_file(self):
        path_str = self.file_var.get().strip()
        if not path_str:
            messagebox.showwarning("提示", "请先选择文件")
            return

        path = Path(path_str)
        if not path.exists():
            messagebox.showerror("错误", f"文件不存在:\n{path}")
            return

        try:
            self.pause()
            self.frames = load_frames_from_yaml(path)
            if not self.frames:
                raise ValueError("没有解析到任何有效帧")

            self.current_idx = 0
            self.scale.configure(from_=0, to=len(self.frames) - 1)
            self.scale.set(0)

            self.status_var.set(f"已加载 {len(self.frames)} 帧: {path}")
            self.update_view(0)

        except Exception as e:
            traceback.print_exc()
            messagebox.showerror("加载失败", str(e))

    def refresh_current(self):
        if self.frames:
            self.update_view(self.current_idx)

    def update_view(self, idx: int):
        if not self.frames:
            return

        idx = max(0, min(idx, len(self.frames) - 1))
        self.current_idx = idx
        frame = self.frames[idx]

        x0 = frame.origin_x
        y0 = frame.origin_y
        x1 = frame.origin_x + frame.width * frame.resolution
        y1 = frame.origin_y + frame.height * frame.resolution

        self.im.set_data(frame.grid)
        self.im.set_extent((x0, x1, y0, y1))
        self.ax.set_xlim(x0, x1)
        self.ax.set_ylim(y0, y1)
        self.ax.set_title(f"Costmap  Frame {idx + 1}/{len(self.frames)}")

        robot_x = frame.origin_x + 0.5 * frame.width * frame.resolution
        robot_y = frame.origin_y + 0.5 * frame.height * frame.resolution
        self.robot_dot.set_data([robot_x], [robot_y])

        if self.lethal_overlay is not None:
            self.lethal_overlay.remove()
            self.lethal_overlay = None

        if self.footprint_patch is not None:
            self.footprint_patch.remove()
            self.footprint_patch = None

        try:
            lethal_threshold = float(self.lethal_threshold_var.get())
        except ValueError:
            lethal_threshold = 99.0
            self.lethal_threshold_var.set("99")

        if self.show_lethal_var.get():
            mask = np.where(frame.grid >= lethal_threshold, 1.0, np.nan)
            self.lethal_overlay = self.ax.imshow(
                mask,
                origin="lower",
                interpolation="nearest",
                extent=(x0, x1, y0, y1),
                alpha=0.35,
                cmap="autumn",
                vmin=0,
                vmax=1,
            )

        if self.show_fp_var.get():
            try:
                fp_len = max(0.01, float(self.fp_len_var.get()))
                fp_wid = max(0.01, float(self.fp_wid_var.get()))
            except ValueError:
                fp_len, fp_wid = 0.70, 0.40
                self.fp_len_var.set("0.70")
                self.fp_wid_var.set("0.40")

            self.footprint_patch = Rectangle(
                (robot_x - fp_len / 2.0, robot_y - fp_wid / 2.0),
                fp_len,
                fp_wid,
                fill=False,
                linewidth=2.0,
                edgecolor="cyan",
            )
            self.ax.add_patch(self.footprint_patch)

        dt = 0.0
        if idx > 0:
            dt = frame.stamp_float - self.frames[idx - 1].stamp_float

        nonzero = int(np.count_nonzero(frame.grid > 0))
        lethal = int(np.count_nonzero(frame.grid >= lethal_threshold))

        self.info_var.set(
            f"frame_id: {frame.frame_id}\n"
            f"stamp: {frame.stamp_sec}.{frame.stamp_nanosec:09d}\n"
            f"dt_from_prev: {dt:.3f} s\n"
            f"size: {frame.width} x {frame.height}\n"
            f"resolution: {frame.resolution:.3f} m/cell\n"
            f"origin: ({frame.origin_x:.3f}, {frame.origin_y:.3f})\n"
            f"nonzero cells: {nonzero}\n"
            f"lethal cells (>={lethal_threshold:.0f}): {lethal}\n"
            f"footprint: {self.fp_len_var.get()} x {self.fp_wid_var.get()} m\n"
            f"robot center: map middle (visual only)"
        )

        self.frame_label.config(text=f"{idx + 1} / {len(self.frames)}")
        self.canvas.draw_idle()

    def on_scale(self, value):
        if not self.frames:
            return
        idx = int(float(value))
        self.update_view(idx)

    def play(self):
        if not self.frames:
            messagebox.showwarning("提示", "请先加载文件")
            return
        self.playing = True
        self.schedule_next()

    def schedule_next(self):
        if not self.playing or not self.frames:
            return

        try:
            fps = max(0.1, float(self.fps_var.get()))
        except ValueError:
            fps = 2.0
            self.fps_var.set("2.0")

        interval = int(1000.0 / fps)
        next_idx = (self.current_idx + 1) % len(self.frames)

        self.update_view(next_idx)
        self.scale.set(next_idx)
        self.play_job = self.after(interval, self.schedule_next)

    def pause(self):
        self.playing = False
        if self.play_job is not None:
            self.after_cancel(self.play_job)
            self.play_job = None

    def prev_frame(self):
        self.pause()
        if self.frames:
            idx = max(0, self.current_idx - 1)
            self.scale.set(idx)
            self.update_view(idx)

    def next_frame(self):
        self.pause()
        if self.frames:
            idx = min(len(self.frames) - 1, self.current_idx + 1)
            self.scale.set(idx)
            self.update_view(idx)

    def export_gif(self):
        if not self.frames:
            messagebox.showwarning("提示", "请先加载文件")
            return

        out_path = filedialog.asksaveasfilename(
            title="保存 GIF",
            defaultextension=".gif",
            filetypes=[("GIF files", "*.gif")]
        )
        if not out_path:
            return

        def worker():
            try:
                self.status_var.set("正在导出 GIF，请稍等...")

                fig = Figure(figsize=(8, 8), dpi=100)
                ax = fig.add_subplot(111)
                first = self.frames[0]
                im = ax.imshow(first.grid, origin="lower", interpolation="nearest", vmin=0, vmax=100)

                def update(i):
                    frame = self.frames[i]
                    x0 = frame.origin_x
                    y0 = frame.origin_y
                    x1 = frame.origin_x + frame.width * frame.resolution
                    y1 = frame.origin_y + frame.height * frame.resolution
                    im.set_data(frame.grid)
                    im.set_extent((x0, x1, y0, y1))
                    ax.set_xlim(x0, x1)
                    ax.set_ylim(y0, y1)
                    ax.set_title(f"Costmap Frame {i + 1}/{len(self.frames)}")
                    return [im]

                try:
                    fps = max(0.1, float(self.fps_var.get()))
                except ValueError:
                    fps = 2.0

                anim = FuncAnimation(
                    fig, update, frames=len(self.frames), interval=int(1000 / fps), blit=False
                )
                writer = PillowWriter(fps=fps)
                anim.save(out_path, writer=writer)

                self.after(0, lambda: self.status_var.set(f"GIF 已保存: {out_path}"))
                self.after(0, lambda: messagebox.showinfo("完成", f"GIF 已保存:\n{out_path}"))

            except Exception as e:
                traceback.print_exc()
                self.after(0, lambda: messagebox.showerror("导出失败", str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def export_pngs(self):
        if not self.frames:
            messagebox.showwarning("提示", "请先加载文件")
            return

        out_dir = filedialog.askdirectory(title="选择 PNG 导出目录")
        if not out_dir:
            return

        def worker():
            try:
                out_path = Path(out_dir)
                out_path.mkdir(parents=True, exist_ok=True)

                total = len(self.frames)
                for i, frame in enumerate(self.frames):
                    fig = Figure(figsize=(8, 8), dpi=100)
                    ax = fig.add_subplot(111)

                    x0 = frame.origin_x
                    y0 = frame.origin_y
                    x1 = frame.origin_x + frame.width * frame.resolution
                    y1 = frame.origin_y + frame.height * frame.resolution

                    im = ax.imshow(frame.grid, origin="lower", interpolation="nearest", vmin=0, vmax=100)
                    ax.set_xlim(x0, x1)
                    ax.set_ylim(y0, y1)
                    ax.set_title(f"Costmap Frame {i + 1}/{total}")
                    ax.set_xlabel("x (m)")
                    ax.set_ylabel("y (m)")
                    fig.colorbar(im, ax=ax, label="cost")

                    png_file = out_path / f"costmap_frame_{i + 1:04d}.png"
                    fig.savefig(png_file, bbox_inches="tight")
                    self.after(0, lambda i=i, total=total: self.status_var.set(f"正在导出 PNG: {i + 1}/{total}"))

                self.after(0, lambda: self.status_var.set(f"PNG 已导出到: {out_dir}"))
                self.after(0, lambda: messagebox.showinfo("完成", f"PNG 已导出到:\n{out_dir}"))

            except Exception as e:
                traceback.print_exc()
                self.after(0, lambda: messagebox.showerror("导出失败", str(e)))

        threading.Thread(target=worker, daemon=True).start()


def main():
    root = tk.Tk()
    page = CostmapPlayerPage(root, embedded=False)
    page.pack(fill=tk.BOTH, expand=True)
    root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # 独立运行时保留 traceback，方便没有控制台日志的 Windows 环境定位问题。
        traceback.print_exc()
        input("程序报错，按回车退出...")
