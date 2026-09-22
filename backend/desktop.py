"""功能说明：发行版单进程入口，管理本机端口、实例身份、浏览器与托盘生命周期。"""
from __future__ import annotations

import argparse
import atexit
import json
import logging
import os
from pathlib import Path
import secrets
import socket
import sys
import threading
import time
from urllib.request import ProxyHandler, build_opener
import webbrowser


def reserve_socket(preferred: int) -> socket.socket:
    """直接保留监听套接字交给服务器，避免探测后释放导致端口再次被抢占。"""
    for port in dict.fromkeys((preferred, 0)):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if os.name == "nt":
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            listener.bind(("127.0.0.1", port))
            listener.listen(128)
            listener.setblocking(False)
            return listener
        except OSError:
            listener.close()
            if port == 0:
                raise
    raise RuntimeError("无法分配本机监听端口")


def lock_instance(directory: Path):
    """使用用户数据目录的文件锁，不占用固定端口；进程退出后系统自动释放。"""
    import msvcrt
    stream = (directory / "instance.lock").open("a+b")
    stream.seek(0, 2)
    if stream.tell() == 0:
        stream.write(b"0")
        stream.flush()
    stream.seek(0)
    try:
        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        return stream
    except OSError:
        stream.close()
        return None


def open_existing(state_path: Path, browser: bool) -> bool:
    """仅信任本机地址且校验实例随机标识，不打开碰巧占用旧端口的其他网站。"""
    opener = build_opener(ProxyHandler({}))
    for _ in range(80):
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            port = int(state["port"])
            if not 1 <= port <= 65535:
                return False
            url = f"http://127.0.0.1:{port}"
            with opener.open(f"{url}/api/desktop/instance", timeout=0.5) as response:
                actual = json.load(response)
            if actual.get("instance") == state["instance"]:
                if browser:
                    webbrowser.open(url)
                return True
        except (OSError, ValueError, KeyError):
            pass
        time.sleep(0.25)
    return False


def create_tray(server, url: str, data_dir: Path):
    """托盘与服务器同进程，退出时优雅停止监听，不通过端口查杀其他程序。"""
    import pystray
    from PIL import Image, ImageDraw
    picture = Image.new("RGBA", (64, 64), "#d6cdbc")
    draw = ImageDraw.Draw(picture)
    for x in (16, 29, 42):
        for y in (16, 29, 42):
            draw.rounded_rectangle((x, y, x + 7, y + 7), radius=2, fill="#554e43")

    def stop(icon, item):
        server.should_exit = True
        icon.stop()

    return pystray.Icon("ROSPlatform", picture, f"ROS 测试平台 · {url}", menu=pystray.Menu(
        pystray.MenuItem("打开平台", lambda: webbrowser.open(url), default=True),
        pystray.MenuItem("打开数据与日志", lambda: os.startfile(str(data_dir))),
        pystray.MenuItem("退出平台", stop),
    ))


def serve(args, data_dir: Path, state_path: Path) -> int:
    """导入业务前配置发行路径，将已绑定套接字交给 Uvicorn 并记录实际地址。"""
    resources = Path(sys.argv[0]).resolve().parent if "__compiled__" in globals() else Path(__file__).resolve().parents[1]
    os.environ["ROS_PLATFORM_RESOURCES"] = str(resources)
    os.environ["ROS_PLATFORM_DATA"] = str(data_dir)
    os.environ["ROS_PLATFORM_PACKAGED"] = "1"
    os.chdir(data_dir)
    previous = {}
    try:
        previous = json.loads((data_dir / "endpoint.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    preferred = args.port if args.port is not None else previous.get("port", 8100)
    if not isinstance(preferred, int) or not 0 <= preferred <= 65535:
        preferred = 8100
    listener = reserve_socket(preferred)
    port = listener.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    instance = secrets.token_hex(24)
    os.environ["ROS_PLATFORM_INSTANCE"] = instance
    os.environ["ROS_PLATFORM_PORT"] = str(port)
    from app.main import app
    import uvicorn
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_config=None, access_log=False))
    thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 40
        while not server.started:
            if not thread.is_alive() or time.monotonic() >= deadline:
                raise RuntimeError("本机服务启动失败，请查看 desktop.log")
            time.sleep(0.05)
        state_path.write_text(json.dumps({"pid": os.getpid(), "port": port, "instance": instance}), encoding="utf-8")
        (data_dir / "endpoint.json").write_text(json.dumps({"port": port}), encoding="utf-8")
        logging.info("平台已启动：%s；资源目录：%s；数据目录：%s", url, resources, data_dir)
        if not args.no_browser:
            webbrowser.open(url)
        if args.headless:
            while thread.is_alive():
                thread.join(0.5)
        else:
            create_tray(server, url, data_dir).run()
        return 0
    finally:
        server.should_exit = True
        thread.join(10)
        listener.close()
        state_path.unlink(missing_ok=True)


def main() -> int:
    """命令行测试模式和安装快捷方式共用入口，依赖与个人数据均不写入安装目录。"""
    parser = argparse.ArgumentParser(description="ROS 测试平台本机服务")
    parser.add_argument("--headless", action="store_true", help="不显示托盘，用于部署验证")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--port", type=int, help="首选本机端口，被占用时自动分配")
    parser.add_argument("--data-dir", type=Path, help="独立用户数据目录，用于隔离测试")
    args = parser.parse_args()
    if args.port is not None and not 0 <= args.port <= 65535:
        parser.error("端口必须在 0 至 65535 之间")
    data_dir = (args.data_dir or Path(os.environ["LOCALAPPDATA"]) / "ROSPlatform" / "UserData").resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    from logging.handlers import RotatingFileHandler
    logging.basicConfig(level=logging.INFO, handlers=[RotatingFileHandler(data_dir / "desktop.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8")])
    state_path = data_dir / "instance.json"
    guard = lock_instance(data_dir)
    if guard is None:
        if open_existing(state_path, not args.no_browser):
            return 0
        raise RuntimeError("平台进程仍持有数据目录锁，但服务未就绪；请查看 desktop.log")
    try:
        return serve(args, data_dir, state_path)
    finally:
        guard.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        logging.exception("平台启动异常")
        if "--headless" not in sys.argv:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, str(error), "ROS 测试平台启动失败", 0x10)
        raise SystemExit(1)
