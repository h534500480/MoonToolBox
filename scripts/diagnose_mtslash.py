import hashlib
import os
import re
import socket
import subprocess
import sys
import time
from datetime import datetime
from html import unescape
from pathlib import Path
from shutil import which
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener


DEFAULT_URL = "https://www.mtslash.life/thread-442199-1-1.html"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
BASE_URL = "https://www.mtslash.life/"


def root_dir() -> Path:
    return Path(__file__).resolve().parents[1]


def log_dir() -> Path:
    path = root_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def clean_text(html: str) -> str:
    html = re.sub(r"<script\b.*?</script>", "", html, flags=re.I | re.S)
    html = re.sub(r"<style\b.*?</style>", "", html, flags=re.I | re.S)
    html = re.sub(r"<[^>]+>", "\n", html)
    lines = [re.sub(r"\s+", " ", unescape(line)).strip() for line in html.splitlines()]
    return "\n".join(line for line in lines if line)


def title_of(html: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    if not match:
        return ""
    return clean_text(match.group(1))


def is_reload_page(html: str) -> bool:
    return "页面重载开启" in html or "document.location.reload" in html


def markers(html: str) -> dict:
    return {
        "postmessage": len(re.findall(r'id=["\']postmessage_\d+', html, re.I)),
        "post": len(re.findall(r'id=["\']post_\d+', html, re.I)),
        "pid": len(re.findall(r'id=["\']pid\d+', html, re.I)),
        "plhin": len(re.findall(r'class=["\'][^"\']*\bplhin\b', html, re.I)),
        "t_f": len(re.findall(r'class=["\'][^"\']*\bt_f\b', html, re.I)),
        "reload": 1 if is_reload_page(html) else 0,
    }


def save_html(name: str, html: str) -> Path:
    digest = hashlib.sha256(html.encode("utf-8", errors="replace")).hexdigest()[:10]
    path = log_dir() / f"mtslash_diag_{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{digest}.html"
    path.write_text(html, encoding="utf-8", errors="replace")
    return path


def report_html(name: str, html: str, status: str = "") -> None:
    text = clean_text(html)
    path = save_html(name, html)
    marker_text = ", ".join(f"{key}={value}" for key, value in markers(html).items())
    print(f"[{name}] status: {status or 'ok'}")
    print(f"[{name}] bytes: {len(html.encode('utf-8', errors='replace'))}, title: {title_of(html) or '(empty)'}, text_len: {len(text)}")
    print(f"[{name}] markers: {marker_text}")
    print(f"[{name}] snippet: {(text[:180] or '(empty)').replace(chr(10), ' ')}")
    print(f"[{name}] saved: {path}")


def request_headers() -> dict:
    return {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5",
        "Cache-Control": "no-cache",
        "Connection": "close",
        "Referer": BASE_URL,
    }


def fetch_python_direct(url: str, attempt: int) -> str:
    opener = build_opener(ProxyHandler({}))
    request = Request(url, headers=request_headers())
    try:
        with opener.open(request, timeout=35) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            html = response.read().decode(charset, errors="replace")
            report_html(f"python_direct_{attempt}", html, f"HTTP {response.status}")
            return html
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        report_html(f"python_direct_{attempt}_http_error", body, f"HTTP {exc.code}")
        return body
    except URLError as exc:
        print(f"[python_direct_{attempt}] error: {exc.reason}")
        return ""


def run_curl(url: str, name: str, no_proxy: bool) -> str:
    curl = which("curl.exe") or which("curl")
    if not curl:
        print(f"[{name}] skipped: curl.exe not found")
        return ""

    body_path = log_dir() / f"mtslash_diag_{name}_body.tmp"
    header_path = log_dir() / f"mtslash_diag_{name}_headers.tmp"
    args = [
        curl,
        "--silent",
        "--show-error",
        "--location",
        "--http1.1",
        "--connect-timeout",
        "35",
        "--max-time",
        "35",
        "--user-agent",
        USER_AGENT,
        "--header",
        "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "--header",
        "Accept-Language: zh-CN,zh;q=0.9,en;q=0.5",
        "--header",
        "Cache-Control: no-cache",
        "--header",
        "Connection: close",
        "--referer",
        BASE_URL,
        "--dump-header",
        str(header_path),
        "--output",
        str(body_path),
    ]
    if no_proxy:
        args.extend(["--noproxy", "*"])
    args.append(url)

    result = subprocess.run(args, capture_output=True, text=True, timeout=45)
    if result.returncode != 0:
        print(f"[{name}] error: curl exit {result.returncode}: {result.stderr.strip() or result.stdout.strip()}")
        return ""

    html = body_path.read_text(encoding="utf-8", errors="replace")
    status_lines = [
        line.strip()
        for line in header_path.read_text(encoding="iso-8859-1", errors="replace").splitlines()
        if line.startswith("HTTP/")
    ]
    report_html(name, html, status_lines[-1] if status_lines else "ok")
    for path in [body_path, header_path]:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
    return html


def print_environment() -> None:
    print(f"Python: {sys.executable}")
    print(f"Working dir: {Path.cwd()}")
    print(f"Tool root: {root_dir()}")
    for host in ["www.mtslash.life", "mtslash.life"]:
        try:
            addresses = sorted({item[4][0] for item in socket.getaddrinfo(host, 443)})
            print(f"DNS {host}: {', '.join(addresses)}")
        except OSError as exc:
            print(f"DNS {host}: ERROR {exc}")

    for key in ["ROS_TOOL_MTSLASH_PROXY", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY"]:
        print(f"ENV {key}: {os.environ.get(key, '(unset)')}")
    print("")


def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL
    print_environment()
    print(f"URL: {url}")
    print("")

    first = fetch_python_direct(url, 1)
    if first and is_reload_page(first):
        print("[python_direct] reload page detected; retrying same URL after 1.5s")
        time.sleep(1.5)
        fetch_python_direct(url, 2)

    print("")
    first_curl_direct = run_curl(url, "curl_direct_1", no_proxy=True)
    if first_curl_direct and is_reload_page(first_curl_direct):
        print("[curl_direct] reload page detected; retrying same URL after 1.5s")
        time.sleep(1.5)
        run_curl(url, "curl_direct_2", no_proxy=True)

    print("")
    first_curl_default = run_curl(url, "curl_default_1", no_proxy=False)
    if first_curl_default and is_reload_page(first_curl_default):
        print("[curl_default] reload page detected; retrying same URL after 1.5s")
        time.sleep(1.5)
        run_curl(url, "curl_default_2", no_proxy=False)

    print("")
    print("Done. Compare saved HTML files under logs\\. A normal thread page should have nonzero text_len and post markers.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
