from pathlib import Path
import tkinter as tk
from tkinter import filedialog


def browse_local_path(mode: str, title: str, initial_path: str) -> str:
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)

    path = Path(initial_path).expanduser() if initial_path else None
    initial_dir = ""
    initial_file = ""
    if path:
        if path.is_dir():
            initial_dir = str(path)
        else:
            initial_dir = str(path.parent) if str(path.parent) != "." else ""
            initial_file = path.name

    if mode == "open_dir":
        selected = filedialog.askdirectory(
            title=title,
            initialdir=initial_dir or None,
            mustexist=False,
            parent=root,
        )
    elif mode == "save_file":
        selected = filedialog.asksaveasfilename(
            title=title,
            initialdir=initial_dir or None,
            initialfile=initial_file or None,
            parent=root,
        )
    else:
        selected = filedialog.askopenfilename(
            title=title,
            initialdir=initial_dir or None,
            initialfile=initial_file or None,
            parent=root,
        )

    root.destroy()
    return selected or ""
