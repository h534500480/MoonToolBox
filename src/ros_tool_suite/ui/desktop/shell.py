#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""旧 Tkinter 桌面壳。

该模块负责按 `tools/registry.py` 动态加载早期桌面工具页面。它是兼容入口，
不是当前 Web 主线的页面框架。
"""

import importlib
import tkinter as tk
from tkinter import ttk

from ros_tool_suite.services.system import detect_local_ip
from ros_tool_suite.shared_ui import apply_suite_theme, style_text_widget
from ros_tool_suite.tools.registry import GROUP_ORDER, TOOLS


class ToolSuiteApp:
    """旧桌面版主窗口。

    输入为 Tk 根窗口，内部按注册表创建左侧导航和右侧工具容器。页面加载失败
    时只在当前卡片显示错误，避免单个旧工具依赖缺失导致整个桌面壳不可用。
    """

    def __init__(self, root):
        self.root = root
        self.root.title("ROS Tool Suite")
        self.root.geometry("1480x940")
        self.root.minsize(1240, 800)
        apply_suite_theme(root)

        self.pages = {}
        self.page_specs = {tool["key"]: tool for tool in TOOLS}
        self.tool_instances = {}
        self.current_page_key = None
        self.nav_buttons = {}
        self.page_path_var = tk.StringVar(value="/tools/pcd_slam_map_tool")
        self.status_var = tk.StringVar(value="Running")
        self.host_var = tk.StringVar(value=detect_local_ip())

        self._build_shell()
        self.show_page("slam")

    def _build_shell(self):
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        shell = tk.Frame(self.root, bg="#171c28")
        shell.grid(row=0, column=0, sticky="nsew")
        shell.grid_columnconfigure(1, weight=1)
        shell.grid_rowconfigure(1, weight=1)

        self._build_topbar(shell)
        self._build_sidebar(shell)
        self._build_content_host(shell)

    def _build_topbar(self, parent):
        topbar = tk.Frame(parent, bg="#1a2030", height=70, bd=0, highlightthickness=1, highlightbackground="#2b3244")
        topbar.grid(row=0, column=0, columnspan=2, sticky="ew")
        topbar.grid_propagate(False)
        topbar.columnconfigure(1, weight=1)

        tk.Label(
            topbar,
            text="□  ROS Tool Suite",
            bg="#1a2030",
            fg="#e8eefb",
            font=("Microsoft YaHei UI", 16, "bold"),
        ).grid(row=0, column=0, sticky="w", padx=18)

        center = tk.Frame(topbar, bg="#1a2030")
        center.grid(row=0, column=1)
        tk.Label(
            center,
            textvariable=self.page_path_var,
            bg="#1a2030",
            fg="#dfe7f7",
            font=("Consolas", 14, "bold"),
        ).pack()

        right = tk.Frame(topbar, bg="#1a2030")
        right.grid(row=0, column=2, sticky="e", padx=18)
        tk.Label(right, text="●", bg="#1a2030", fg="#61d04f", font=("Segoe UI", 18)).pack(side="left", padx=(0, 8))
        tk.Label(right, textvariable=self.status_var, bg="#1a2030", fg="#f4f8ff", font=("Microsoft YaHei UI", 12, "bold")).pack(side="left")
        tk.Label(right, text="  |  ", bg="#1a2030", fg="#73809b", font=("Microsoft YaHei UI", 12)).pack(side="left")
        tk.Label(right, textvariable=self.host_var, bg="#1a2030", fg="#d9e2f2", font=("Microsoft YaHei UI", 12)).pack(side="left")

    def _build_sidebar(self, parent):
        sidebar = tk.Frame(parent, bg="#171c28", width=290, bd=0, highlightthickness=1, highlightbackground="#2b3244")
        sidebar.grid(row=1, column=0, sticky="nsw")
        sidebar.grid_propagate(False)

        tk.Label(
            sidebar,
            text="TOOLS",
            bg="#171c28",
            fg="#9eabc5",
            font=("Microsoft YaHei UI", 16, "bold"),
        ).pack(anchor="w", padx=28, pady=(24, 18))

        by_group = {}
        for tool in TOOLS:
            by_group.setdefault(tool["group"], []).append(tool)

        for group_key, group_label in GROUP_ORDER:
            tools = by_group.get(group_key, [])
            if not tools:
                continue
            tk.Label(
                sidebar,
                text=f"▾  {group_label}",
                bg="#171c28",
                fg="#c8d2e6",
                font=("Consolas", 12, "bold"),
            ).pack(anchor="w", padx=22, pady=(0, 6))

            for tool in tools:
                btn = tk.Button(
                    sidebar,
                    text=f"   {tool['title']}",
                    command=lambda k=tool["key"]: self.show_page(k),
                    relief="flat",
                    bd=0,
                    anchor="w",
                    padx=18,
                    pady=10,
                    bg="#171c28",
                    fg="#e6edf8",
                    activebackground="#29478d",
                    activeforeground="#ffffff",
                    font=("Consolas", 12, "bold"),
                    cursor="hand2",
                )
                btn.pack(fill="x", padx=2, pady=2)
                self.nav_buttons[tool["key"]] = btn

            divider = tk.Frame(sidebar, bg="#2b3244", height=1)
            divider.pack(fill="x", padx=20, pady=(8, 12))

    def _build_content_host(self, parent):
        self.container = tk.Frame(parent, bg="#1b2130")
        self.container.grid(row=1, column=1, sticky="nsew")
        self.container.grid_rowconfigure(0, weight=1)
        self.container.grid_columnconfigure(0, weight=1)

    def show_page(self, key):
        if self.current_page_key == key:
            return

        if self.current_page_key in self.pages:
            self.pages[self.current_page_key].grid_remove()
            old_btn = self.nav_buttons.get(self.current_page_key)
            if old_btn is not None:
                old_btn.configure(bg="#171c28", fg="#e6edf8")

        if key not in self.pages:
            self.pages[key] = self._build_tool_page(self.page_specs[key])

        self.pages[key].grid()
        self.pages[key].tkraise()
        self.current_page_key = key

        tool = self.page_specs[key]
        self.page_path_var.set(f"/tools/{tool['module']}")
        btn = self.nav_buttons.get(key)
        if btn is not None:
            btn.configure(bg="#29478d", fg="#ffffff")

    def _new_page(self):
        page = tk.Frame(self.container, bg="#1b2130")
        page.grid(row=0, column=0, sticky="nsew")
        return page

    def _build_tool_page(self, tool):
        page = self._new_page()
        page.grid_rowconfigure(0, weight=1)
        page.grid_columnconfigure(0, weight=1)

        outer = tk.Frame(page, bg="#2c3448", bd=0, highlightthickness=0)
        outer.grid(row=0, column=0, sticky="nsew", padx=18, pady=14)
        outer.grid_rowconfigure(0, weight=1)
        outer.grid_columnconfigure(0, weight=1)

        content = ttk.Frame(outer, style="Card.TFrame", padding=8)
        content.grid(row=0, column=0, sticky="nsew", padx=3, pady=3)
        content.grid_rowconfigure(0, weight=1)
        content.grid_columnconfigure(0, weight=1)

        self.tool_instances[tool["key"]] = self._load_tool(content, tool)
        return page

    def _load_tool(self, parent, tool):
        try:
            module = importlib.import_module(tool["module"])
            page_cls = getattr(module, tool["class_name"])
            instance = page_cls(parent, **tool.get("kwargs", {}))
            if tool.get("pack_widget") and hasattr(instance, "pack"):
                instance.pack(fill=tk.BOTH, expand=True)
            return instance
        except Exception as exc:
            # 旧桌面工具依赖差异较大，加载失败时降级为错误卡片，保留其它工具可用。
            self._build_error_card(parent, tool["title"], tool["module"], exc)
            return None

    def _build_error_card(self, parent, title, module_name, exc):
        wrap = ttk.Frame(parent, style="Card.TFrame", padding=24)
        wrap.grid(row=0, column=0, sticky="nsew")
        wrap.columnconfigure(0, weight=1)
        wrap.rowconfigure(3, weight=1)

        ttk.Label(wrap, text=f"{title} 页面加载失败", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            wrap,
            text="该页面依赖未满足或初始化失败，不影响其它页面继续使用。",
            style="SubTitle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

        hint = "请根据下面的错误补齐依赖后重启。"
        if module_name.endswith("costmap_player"):
            hint = "Costmap 页面通常需要安装: numpy matplotlib pyyaml"
        ttk.Label(wrap, text=hint, style="SubTitle.TLabel").grid(row=2, column=0, sticky="w", pady=(12, 10))

        msg = tk.Text(wrap, height=12, wrap="word")
        msg.grid(row=3, column=0, sticky="nsew")
        style_text_widget(msg, height=12)
        msg.insert("1.0", f"{type(exc).__name__}: {exc}\n")
        msg.configure(state="disabled")


def main():
    root = tk.Tk()
    ToolSuiteApp(root)
    root.mainloop()
