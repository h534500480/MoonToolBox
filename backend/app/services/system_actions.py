import os
from pathlib import Path
import subprocess


def open_path_in_system(path: str) -> None:
    target = Path(path)
    if not target.exists():
        # For output folders, create the directory on demand.
        if target.suffix:
            raise RuntimeError(f"路径不存在: {path}")
        target.mkdir(parents=True, exist_ok=True)

    if os.name == "nt":
        os.startfile(str(target))
        return

    subprocess.Popen(["xdg-open", str(target)])
