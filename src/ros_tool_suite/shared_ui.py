#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import tkinter as tk
from tkinter import ttk


def apply_suite_theme(root):
    style = ttk.Style()
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    bg = "#171c28"
    panel = "#1d2230"
    surface = "#202635"
    line = "#30384d"
    text = "#e6edf8"
    subtext = "#9ba7c0"
    accent = "#3b82f6"
    accent_dark = "#2563eb"
    soft = "#2a3142"

    try:
        root.configure(bg=bg)
    except tk.TclError:
        pass

    style.configure(".", background=bg, foreground=text, font=("Microsoft YaHei UI", 10))
    style.configure("App.TFrame", background=bg)
    style.configure("Card.TFrame", background=surface, borderwidth=0)
    style.configure("Panel.TFrame", background=panel)
    style.configure("Section.TLabelframe", background=surface, borderwidth=1, relief="solid")
    style.configure("Section.TLabelframe.Label", background=surface, foreground=text, font=("Microsoft YaHei UI", 11, "bold"))
    style.configure("Title.TLabel", background=bg, foreground=text, font=("Microsoft YaHei UI", 16, "bold"))
    style.configure("SubTitle.TLabel", background=bg, foreground=subtext, font=("Microsoft YaHei UI", 10))
    style.configure("CardTitle.TLabel", background=surface, foreground=text, font=("Microsoft YaHei UI", 11, "bold"))
    style.configure("Body.TLabel", background=surface, foreground=subtext)
    style.configure("Primary.TButton", background=accent, foreground="#ffffff", borderwidth=0, padding=(14, 8))
    style.map("Primary.TButton", background=[("active", accent_dark), ("pressed", accent_dark)])
    style.configure("Secondary.TButton", background=soft, foreground=text, borderwidth=0, padding=(12, 8))
    style.map("Secondary.TButton", background=[("active", "#323b50"), ("pressed", "#38445c")])
    style.configure("Soft.TButton", background=surface, foreground=text, borderwidth=1, padding=(10, 7))
    style.map("Soft.TButton", background=[("active", "#2a3142")])
    style.configure("Suite.TEntry", fieldbackground="#171c28", foreground=text, padding=6)
    style.map("Suite.TEntry", fieldbackground=[("readonly", "#171c28")], foreground=[("readonly", text)])
    style.configure("Suite.TCombobox", fieldbackground="#171c28", foreground=text, padding=4)
    style.map("Suite.TCombobox", fieldbackground=[("readonly", "#171c28")], foreground=[("readonly", text)])
    style.configure("Suite.Horizontal.TProgressbar", troughcolor="#111621", background=accent, bordercolor="#111621", lightcolor=accent, darkcolor=accent)
    style.configure("Suite.Vertical.TScrollbar", background=soft, troughcolor="#111621", arrowcolor=text, bordercolor="#111621", darkcolor=soft, lightcolor=soft)
    style.configure("Suite.Horizontal.TScrollbar", background=soft, troughcolor="#111621", arrowcolor=text, bordercolor="#111621", darkcolor=soft, lightcolor=soft)
    style.map("Suite.Vertical.TScrollbar", background=[("active", "#3b445b"), ("pressed", "#46516b")])
    style.map("Suite.Horizontal.TScrollbar", background=[("active", "#3b445b"), ("pressed", "#46516b")])
    style.configure("Suite.Treeview", background=surface, fieldbackground=surface, foreground=text, rowheight=28)
    style.configure("Suite.Treeview.Heading", background=soft, foreground=text, relief="flat", font=("Microsoft YaHei UI", 10, "bold"))
    style.map("Suite.Treeview", background=[("selected", "#2b4f96")], foreground=[("selected", "#ffffff")])
    style.configure("Suite.TCheckbutton", background=surface, foreground=text)
    style.configure("Suite.TRadiobutton", background=surface, foreground=text)
    return style


def make_card(parent, padding=14):
    outer = tk.Frame(parent, bg="#2c3448", bd=0, highlightthickness=0)
    inner = ttk.Frame(outer, style="Card.TFrame", padding=padding)
    inner.pack(fill="both", expand=True, padx=3, pady=3)
    return outer, inner


def style_text_widget(widget, height=None):
    widget.configure(
        bg="#171c28",
        fg="#d9e6ff",
        insertbackground="#d9e6ff",
        relief="flat",
        bd=0,
        highlightthickness=1,
        highlightbackground="#30384d",
        highlightcolor="#4a74c9",
        font=("Consolas", 10),
        padx=10,
        pady=8,
    )
    if height is not None:
        widget.configure(height=height)


def apply_log_tags(widget):
    widget.tag_configure("info", foreground="#8ec5ff")
    widget.tag_configure("warn", foreground="#ffd166")
    widget.tag_configure("error", foreground="#ff7b72")
    widget.tag_configure("success", foreground="#7ee787")
    widget.tag_configure("dim", foreground="#93a4c3")
    widget.tag_configure("heading", foreground="#e6edf8", font=("Consolas", 10, "bold"))


def append_tagged_text(widget, text):
    upper = text.upper()
    tag = None
    if "[ERROR]" in upper or "错误" in text:
        tag = "error"
    elif "[WARN]" in upper or "警告" in text:
        tag = "warn"
    elif "[INFO]" in upper:
        tag = "info"
    elif "[OK]" in upper or "完成" in text or "成功" in text:
        tag = "success"
    widget.insert("end", text, tag)
