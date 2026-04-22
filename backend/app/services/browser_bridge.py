"""通过浏览器 DevTools 协议读取已登录网页内容。

本模块只启动由工具管理的 Edge/Chrome 独立 profile，并限制读取 mtslash.life
站内标签页。这样可以复用浏览器里的登录态，同时避免扫描用户日常浏览器窗口。
"""

import json
import subprocess
import time
from pathlib import Path
from typing import Optional
from urllib.error import URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from websockets.sync.client import connect


ROOT_DIR = Path(__file__).resolve().parents[3]
BASE_URL = "https://www.mtslash.life/"
ALLOWED_HOSTS = {"mtslash.life", "www.mtslash.life"}
BROWSER_PORTS = {"edge": 9222, "chrome": 9223}


def browser_port(browser: str) -> int:
    return BROWSER_PORTS.get(browser.lower(), BROWSER_PORTS["edge"])


def browser_debug_base(browser: str) -> str:
    return f"http://127.0.0.1:{browser_port(browser)}"


def browser_paths(browser: str) -> list:
    if browser.lower() == "chrome":
        return [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ]
    return [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]


def find_browser_exe(browser: str) -> str:
    for path in browser_paths(browser):
        if Path(path).exists():
            return path
    raise RuntimeError(f"未找到 {browser} 浏览器，请先安装或改用另一个浏览器")


def fetch_json(url: str, timeout: int = 3, method: str = "GET") -> object:
    request = Request(url, method=method)
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def devtools_available(browser: str) -> bool:
    try:
        fetch_json(f"{browser_debug_base(browser)}/json/version", timeout=1)
        return True
    except Exception:
        return False


def start_browser(browser: str) -> dict:
    """启动或复用浏览器模式窗口。

    输入为浏览器类型，当前支持 edge/chrome。函数会使用固定调试端口和独立
    user-data-dir，避免污染用户默认浏览器 profile。
    """
    browser = browser.lower()
    port = browser_port(browser)
    if not devtools_available(browser):
        exe = find_browser_exe(browser)
        profile_dir = ROOT_DIR / "backend" / "data" / "browser_profiles" / browser
        profile_dir.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(
            [
                exe,
                f"--remote-debugging-port={port}",
                f"--user-data-dir={profile_dir}",
                "--no-first-run",
                "--new-window",
                BASE_URL,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(20):
            if devtools_available(browser):
                break
            time.sleep(0.25)

    if not devtools_available(browser):
        raise RuntimeError(f"{browser} 调试端口未启动，请关闭该窗口后重试")
    return {"status": "success", "browser": browser, "port": port, "message": f"{browser} 浏览器模式已就绪"}


def is_mtslash_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.hostname in ALLOWED_HOSTS


def list_tabs(browser: str) -> list:
    """列出浏览器模式窗口里的站内页面。

    返回值只包含 mtslash.life 域名下的 page 类型标签页，供前端生成可点击 URL
    列表；其他页面不会暴露给工具界面。
    """
    try:
        raw_tabs = fetch_json(f"{browser_debug_base(browser)}/json", timeout=2)
    except URLError as exc:
        raise RuntimeError(f"浏览器调试端口不可用，请先启动浏览器模式: {exc}") from exc

    tabs = []
    for tab in raw_tabs:
        url = tab.get("url", "")
        if tab.get("type") != "page" or not is_mtslash_url(url):
            continue
        tabs.append(
            {
                "id": tab.get("id", ""),
                "title": tab.get("title", "") or url,
                "url": url,
            }
        )
    return tabs


def find_or_open_tab(browser: str, url: str) -> dict:
    """查找目标标签页，必要时打开一个新标签页。

    优先复用同 URL 标签页，其次复用任意站内标签页。这样翻页导出时会留在
    同一个受控窗口中，站点登录态和风控状态更接近用户手动浏览。
    """
    tabs = fetch_json(f"{browser_debug_base(browser)}/json", timeout=2)
    for tab in tabs:
        if tab.get("type") == "page" and tab.get("url", "").split("#", 1)[0] == url.split("#", 1)[0]:
            return tab
    for tab in tabs:
        if tab.get("type") == "page" and is_mtslash_url(tab.get("url", "")):
            return tab

    try:
        return fetch_json(f"{browser_debug_base(browser)}/json/new?{quote(url, safe='')}", timeout=3, method="PUT")
    except Exception as exc:
        raise RuntimeError(f"没有可用的 mtslash 浏览器标签页，请先在浏览器模式窗口打开该页面: {exc}") from exc


def cdp_call(ws, counter: dict, method: str, params: Optional[dict] = None) -> dict:
    """发送一次 Chrome DevTools Protocol 调用并等待对应响应。"""
    counter["id"] += 1
    message_id = counter["id"]
    ws.send(json.dumps({"id": message_id, "method": method, "params": params or {}}))
    while True:
        message = json.loads(ws.recv())
        if message.get("id") == message_id:
            if "error" in message:
                raise RuntimeError(str(message["error"]))
            return message.get("result", {})


def get_page_html(browser: str, url: str, wait_seconds: float = 2.0) -> str:
    """导航到指定 URL 并返回当前页面 HTML。

    该函数依赖浏览器真实加载页面，适合处理 Python 请求被重置、但浏览器可访问
    的场景。调用方仍需要解析返回 HTML 并判断是否为站点中间页。
    """
    start_browser(browser)
    tab = find_or_open_tab(browser, url)
    websocket_url = tab.get("webSocketDebuggerUrl")
    if not websocket_url:
        raise RuntimeError("浏览器标签页没有调试 WebSocket")

    counter = {"id": 0}
    with connect(websocket_url, open_timeout=5) as ws:
        cdp_call(ws, counter, "Page.enable")
        cdp_call(ws, counter, "Runtime.enable")
        cdp_call(ws, counter, "Page.navigate", {"url": url})
        deadline = time.time() + max(8.0, wait_seconds + 6.0)
        while time.time() < deadline:
            time.sleep(0.4)
            result = cdp_call(ws, counter, "Runtime.evaluate", {"expression": "document.readyState", "returnByValue": True})
            if result.get("result", {}).get("value") == "complete":
                break
        time.sleep(wait_seconds)
        result = cdp_call(
            ws,
            counter,
            "Runtime.evaluate",
            {
                "expression": "document.documentElement ? document.documentElement.outerHTML : ''",
                "returnByValue": True,
            },
        )
        return result.get("result", {}).get("value", "")
