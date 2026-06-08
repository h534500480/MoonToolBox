#!/usr/bin/env python
# 功能说明：提供 MoonToolBox 的系统托盘启动入口，负责拉起后端、打开页面并在退出时关闭后台进程。

from __future__ import annotations

import atexit
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

import pystray
from PIL import Image, ImageDraw


BACKEND_URL = "http://127.0.0.1:8000"
HEALTH_URL = f"{BACKEND_URL}/api/health"
HEALTH_TIMEOUT_SECONDS = 1.0
READY_RETRY_INTERVAL_SECONDS = 0.5
READY_MAX_ATTEMPTS = 60
STATE_FILENAME = "tray_state.json"
ICON_FILENAME = "MoonToolBox.ico"
BACKEND_OUT_LOG = "backend.out.log"
BACKEND_ERR_LOG = "backend.err.log"
_SINGLE_INSTANCE_GUARD: socket.socket | None = None


class TrayApplication:
    """托盘应用入口。"""

    def __init__(self) -> None:
        self.root_dir = Path(__file__).resolve().parent.parent
        self.backend_dir = self.root_dir / "backend"
        self.logs_dir = self.root_dir / "logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.logs_dir / STATE_FILENAME
        self.backend_process: subprocess.Popen[str] | None = None
        self.backend_stdout = None
        self.backend_stderr = None
        self.attached_to_existing_backend = False
        self.browser_opened = False
        self.stop_event = threading.Event()
        self.icon = pystray.Icon(
            "MoonToolBox",
            self._load_icon(),
            "MoonToolBox",
            menu=pystray.Menu(
                pystray.MenuItem("打开界面", self.on_open_interface, default=True),
                pystray.MenuItem("查看日志目录", self.on_open_logs),
                pystray.MenuItem("退出程序", self.on_exit_program),
            ),
        )
        self.monitor_thread = threading.Thread(target=self.monitor_backend, name="moon-backend-monitor", daemon=True)
        atexit.register(self.cleanup)

    def run(self) -> None:
        if self._backend_is_ready():
            self.attached_to_existing_backend = True
            self.browser_opened = True
            self._write_state(None)
            webbrowser.open(BACKEND_URL)
        else:
            self.start_backend()
            self.monitor_thread.start()
        self.icon.run()

    def start_backend(self) -> None:
        self.backend_stdout = open(self.logs_dir / BACKEND_OUT_LOG, "a", encoding="utf-8")
        self.backend_stderr = open(self.logs_dir / BACKEND_ERR_LOG, "a", encoding="utf-8")
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        env = os.environ.copy()
        env["ROS_TOOL_RELOAD"] = "0"
        self.backend_process = subprocess.Popen(
            [sys.executable, "run.py"],
            cwd=self.backend_dir,
            stdout=self.backend_stdout,
            stderr=self.backend_stderr,
            creationflags=creation_flags,
            env=env,
            text=True,
        )
        self._write_state(self.backend_process.pid)

    def monitor_backend(self) -> None:
        for _ in range(READY_MAX_ATTEMPTS):
            if self.stop_event.is_set():
                return
            if self.backend_process and self.backend_process.poll() is not None:
                self.icon.title = "MoonToolBox（后端启动失败）"
                self.icon.notify("后端启动失败，请查看 logs 目录中的日志。", "MoonToolBox")
                return
            if self._backend_is_ready():
                self.icon.title = "MoonToolBox"
                if not self.browser_opened:
                    self.browser_opened = True
                    webbrowser.open(BACKEND_URL)
                    self.icon.notify("MoonToolBox 已启动，可通过托盘再次打开界面。", "MoonToolBox")
                return
            time.sleep(READY_RETRY_INTERVAL_SECONDS)
        self.icon.title = "MoonToolBox（等待后端超时）"
        self.icon.notify("后端启动超时，请查看 logs 目录中的日志。", "MoonToolBox")

    def on_open_interface(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        webbrowser.open(BACKEND_URL)

    def on_open_logs(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        os.startfile(str(self.logs_dir))

    def on_exit_program(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        self.stop_event.set()
        self.cleanup()
        icon.stop()

    def cleanup(self) -> None:
        if getattr(self, "_cleaned", False):
            return
        self._cleaned = True
        self.stop_event.set()
        if self.backend_process and self.backend_process.poll() is None:
            self._terminate_process(self.backend_process)
        for stream in (self.backend_stdout, self.backend_stderr):
            if stream:
                stream.close()
        self._clear_state()

    def _backend_is_ready(self) -> bool:
        try:
            with urlopen(HEALTH_URL, timeout=HEALTH_TIMEOUT_SECONDS) as response:
                return response.status == 200
        except (URLError, TimeoutError, OSError):
            return False

    def _write_state(self, backend_pid: int | None) -> None:
        payload: dict[str, Any] = {
            "tray_pid": os.getpid(),
            "backend_pid": backend_pid,
            "url": BACKEND_URL,
            "updated_at": time.time(),
            "attached_to_existing_backend": self.attached_to_existing_backend,
        }
        self.state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _clear_state(self) -> None:
        if self.state_path.exists():
            self.state_path.unlink()

    def _terminate_process(self, process: subprocess.Popen[str]) -> None:
        process.terminate()
        try:
            process.wait(timeout=5)
            return
        except subprocess.TimeoutExpired:
            pass

        if os.name == "nt":
            process.kill()
        else:
            os.kill(process.pid, signal.SIGKILL)

    def _load_icon(self) -> Image.Image:
        candidate_paths = (
            self.root_dir / ICON_FILENAME,
            self.root_dir / "assets" / "icons" / "runtime" / "setup.ico",
            self.root_dir / "assets" / "icons" / "runtime" / "moontoolbox.ico",
            self.root_dir / "release" / "MoonToolBox" / ICON_FILENAME,
        )
        for icon_path in candidate_paths:
            if not icon_path.exists():
                continue
            try:
                return Image.open(icon_path)
            except OSError:
                continue
        return self._build_fallback_icon()

    def _build_fallback_icon(self) -> Image.Image:
        image = Image.new("RGBA", (64, 64), "#12344d")
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((6, 6, 58, 58), radius=14, fill="#163f5f")
        draw.polygon(((18, 20), (32, 44), (46, 20)), fill="#7fd1b9")
        draw.rectangle((28, 20, 36, 48), fill="#dff5ee")
        return image


def ensure_single_instance() -> bool:
    global _SINGLE_INSTANCE_GUARD
    port_guard = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        port_guard.bind(("127.0.0.1", 38547))
    except OSError:
        return False
    _SINGLE_INSTANCE_GUARD = port_guard
    return True


def main() -> int:
    if not ensure_single_instance():
        webbrowser.open(BACKEND_URL)
        return 0
    app = TrayApplication()
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
