import os
import re
import subprocess
import tempfile
import time
import uuid
import base64
from http.cookiejar import CookieJar
from dataclasses import dataclass, field
from datetime import datetime
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from shutil import which
from typing import Dict, Iterable, List, Optional
from urllib import robotparser
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener, getproxies, urlopen

from app.models import ToolRunResponse


ROOT_DIR = Path(__file__).resolve().parents[3]
ALLOWED_HOSTS = {"mtslash.life", "www.mtslash.life"}
DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
SKIP_TEXT_TAGS = {"script", "style", "noscript", "template"}
CHAPTER_PATTERN = re.compile(r"(第\s*[0-9一二三四五六七八九十百千万零〇两]+\s*[章节回幕卷篇]|chapter\s*\d+)", re.I)
RELOAD_TITLE_PATTERN = re.compile(r"页面重载开启|&#x9875;&#x9762;&#x91cd;&#x8f7d;&#x5f00;&#x542f;", re.I)
LOGIN_URL = "https://www.mtslash.life/member.php?mod=logging&action=login"
BASE_URL = "https://www.mtslash.life/"
FAVORITES_URL = "https://www.mtslash.life/home.php?mod=space&do=favorite&view=me"
LOGIN_COOLDOWN_SECONDS = 8.0


@dataclass
class LoginSession:
    session_id: str
    fetch_client: "FetchClient"
    formhash: str
    loginhash: str
    seccodehash: str
    login_action: str = ""
    login_fields: Dict[str, str] = field(default_factory=dict)
    captcha_image: str = ""
    authenticated: bool = False
    last_login_attempt: float = 0.0
    username: str = ""


LOGIN_SESSIONS: Dict[str, LoginSession] = {}
LAST_LOGIN_ATTEMPTS: Dict[str, float] = {}


@dataclass
class HtmlNode:
    tag: str
    attrs: Dict[str, str] = field(default_factory=dict)
    children: List[object] = field(default_factory=list)
    parent: Optional["HtmlNode"] = None

    def iter_nodes(self) -> Iterable["HtmlNode"]:
        yield self
        for child in self.children:
            if isinstance(child, HtmlNode):
                yield from child.iter_nodes()

    def text(self) -> str:
        chunks: List[str] = []

        def walk(node: "HtmlNode") -> None:
            if node.tag in SKIP_TEXT_TAGS:
                return
            if node.tag in {"br", "p", "div", "tr", "li", "h1", "h2", "h3", "blockquote"}:
                chunks.append("\n")
            for child in node.children:
                if isinstance(child, HtmlNode):
                    walk(child)
                else:
                    chunks.append(str(child))
            if node.tag in {"p", "div", "tr", "li", "h1", "h2", "h3", "blockquote"}:
                chunks.append("\n")

        walk(self)
        return clean_text("".join(chunks))


class TreeParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = HtmlNode("document")
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: List[tuple]) -> None:
        node = HtmlNode(tag.lower(), {str(k).lower(): v or "" for k, v in attrs}, parent=self.stack[-1])
        self.stack[-1].children.append(node)
        if tag.lower() not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            self.stack.append(node)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        if data:
            self.stack[-1].children.append(data)


@dataclass
class Post:
    pid: str
    author: str
    uid: str
    text: str
    source_url: str


@dataclass
class FavoriteThread:
    title: str
    url: str


def clean_text(value: str) -> str:
    value = unescape(value).replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t\u3000]+", " ", line).strip() for line in value.split("\n")]
    cleaned: List[str] = []
    for line in lines:
        if not line:
            if cleaned and cleaned[-1]:
                cleaned.append("")
            continue
        if line in {"收藏", "回复", "发表于", "只看该作者", "本帖最后由"}:
            continue
        cleaned.append(line)
    while cleaned and cleaned[-1] == "":
        cleaned.pop()
    return "\n".join(cleaned)


def _bool_value(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on", "是"}


def _int_value(value: object, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def _float_value(value: object, default: float, minimum: float, maximum: float) -> float:
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def parse_html(html: str) -> HtmlNode:
    parser = TreeParser()
    parser.feed(html)
    return parser.root


def has_class(node: HtmlNode, class_name: str) -> bool:
    return class_name in node.attrs.get("class", "").split()


def class_contains(node: HtmlNode, token: str) -> bool:
    return token in node.attrs.get("class", "")


def first_text(root: HtmlNode, predicate) -> str:
    for node in root.iter_nodes():
        if predicate(node):
            text = node.text()
            if text:
                return text
    return ""


def validate_thread_url(thread_url: str) -> str:
    parsed = urlparse(thread_url.strip())
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("请输入 http/https 帖子地址")
    if parsed.hostname not in ALLOWED_HOSTS:
        raise ValueError("当前模块只允许导出 mtslash.life 的单个帖子")
    return urlunparse(parsed._replace(fragment=""))


def robots_allowed(url: str, user_agent: str) -> bool:
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    rp = robotparser.RobotFileParser()
    rp.set_url(robots_url)
    try:
        rp.read()
    except Exception:
        return True
    return rp.can_fetch(user_agent, url)


def fetch_text(url: str, cookie: str, user_agent: str, timeout: int = 20) -> str:
    return FetchClient(cookie=cookie, user_agent=user_agent).fetch(url, timeout=timeout)


def normalize_proxy_url(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    if "://" not in value:
        return f"http://{value}"
    return value


def proxies_from_windows_settings() -> Dict[str, str]:
    if os.name != "nt":
        return {}
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as key:
            proxy_enabled = int(winreg.QueryValueEx(key, "ProxyEnable")[0])
            if not proxy_enabled:
                return {}
            proxy_server = str(winreg.QueryValueEx(key, "ProxyServer")[0]).strip()
    except OSError:
        return {}

    if not proxy_server:
        return {}

    proxies: Dict[str, str] = {}
    if "=" in proxy_server:
        for part in proxy_server.split(";"):
            if "=" not in part:
                continue
            scheme, address = part.split("=", 1)
            scheme = scheme.strip().lower()
            if scheme in {"http", "https"}:
                proxies[scheme] = normalize_proxy_url(address)
    else:
        proxy_url = normalize_proxy_url(proxy_server)
        proxies = {"http": proxy_url, "https": proxy_url}
    return proxies


def resolve_proxy_config() -> Dict[str, str]:
    mode = os.environ.get("ROS_TOOL_MTSLASH_PROXY", "direct").strip().lower()
    if not mode or mode in {"0", "off", "false", "none", "direct"}:
        return {}

    if mode not in {"1", "on", "true", "auto", "system"}:
        proxy_url = normalize_proxy_url(mode)
        return {"http": proxy_url, "https": proxy_url}

    env_proxies = {key: value for key, value in getproxies().items() if key in {"http", "https"}}
    if env_proxies:
        return env_proxies
    return proxies_from_windows_settings()


def describe_network_error(prefix: str, reason: object) -> str:
    message = str(reason)
    message_lower = message.lower()
    if "10054" in message:
        return (
            f"{prefix}: {message}。远程主机重置了连接。"
            "如果浏览器能访问但工具失败，通常是网络出口、代理/VPN 或站点风控差异导致；"
            "默认直连。只有需要代理时才设置 ROS_TOOL_MTSLASH_PROXY=system 或 ROS_TOOL_MTSLASH_PROXY=host:port。"
        )
    if "unexpected_eof_while_reading" in message_lower or "eof occurred in violation of protocol" in message_lower:
        return (
            f"{prefix}: {message}。TLS 连接被中途关闭。"
            "这常见于代理/VPN 配置不匹配、HTTPS 被中间层拦截，或站点主动断开非浏览器请求。"
            "当前默认直连；如果目标电脑不挂 VPN，请不要设置 ROS_TOOL_MTSLASH_PROXY。"
        )
    if "handshake operation timed out" in message_lower or "timed out" in message_lower:
        return (
            f"{prefix}: {message}。TLS 握手超时。"
            "工具会尝试使用 Windows curl.exe 回退请求；如果仍失败，通常是该电脑到站点的直连链路不可用或被安全软件拦截。"
        )
    return f"{prefix}: {message}"


def should_retry_with_curl(reason: object) -> bool:
    message = str(reason).lower()
    return any(
        token in message
        for token in [
            "10054",
            "unexpected_eof_while_reading",
            "eof occurred in violation of protocol",
            "ssl",
            "_ssl",
            "handshake operation timed out",
            "timed out",
        ]
    )


def parse_header_content_type(header_text: str, default: str) -> str:
    for line in header_text.splitlines():
        if line.lower().startswith("content-type:"):
            return line.split(":", 1)[1].strip().split(";", 1)[0] or default
    return default


class FetchClient:
    def __init__(self, cookie: str, user_agent: str) -> None:
        self.cookie = cookie.strip()
        self.user_agent = user_agent
        self.cookie_jar = CookieJar()
        self.opener = build_opener(ProxyHandler(resolve_proxy_config()), HTTPCookieProcessor(self.cookie_jar))
        self.curl_path = which("curl.exe") or which("curl")
        cookie_file = tempfile.NamedTemporaryFile(prefix="moontoolbox_mtslash_", suffix=".cookies", delete=False)
        cookie_file.close()
        self.curl_cookie_path = Path(cookie_file.name)

    def _curl_base_args(self, url: str, timeout: int, accept: str, referer: str) -> List[str]:
        if not self.curl_path:
            raise RuntimeError("curl.exe not found")

        args = [
            self.curl_path,
            "--silent",
            "--show-error",
            "--location",
            "--http1.1",
            "--connect-timeout",
            str(timeout),
            "--max-time",
            str(timeout),
            "--cookie",
            str(self.curl_cookie_path),
            "--cookie-jar",
            str(self.curl_cookie_path),
            "--user-agent",
            self.user_agent,
            "--header",
            f"Accept: {accept}",
            "--header",
            "Accept-Language: zh-CN,zh;q=0.9,en;q=0.5",
            "--header",
            "Cache-Control: no-cache",
            "--header",
            "Connection: close",
            "--referer",
            referer,
        ]
        if self.cookie:
            args.extend(["--header", f"Cookie: {self.cookie}"])

        proxies = resolve_proxy_config()
        proxy = proxies.get("https") or proxies.get("http")
        if proxy:
            args.extend(["--proxy", proxy])

        args.append(url)
        return args

    def _curl_request(self, url: str, timeout: int, accept: str, referer: str, data: Optional[bytes] = None) -> tuple:
        with tempfile.NamedTemporaryFile(prefix="moontoolbox_mtslash_body_", delete=False) as body_file:
            body_path = Path(body_file.name)
        with tempfile.NamedTemporaryFile(prefix="moontoolbox_mtslash_headers_", delete=False) as header_file:
            header_path = Path(header_file.name)
        data_path = None

        try:
            args = self._curl_base_args(url=url, timeout=timeout, accept=accept, referer=referer)
            if data is not None:
                with tempfile.NamedTemporaryFile(prefix="moontoolbox_mtslash_post_", delete=False) as data_file:
                    data_file.write(data)
                    data_path = Path(data_file.name)
                args.extend(["--request", "POST", "--header", "Content-Type: application/x-www-form-urlencoded", "--data-binary", f"@{data_path}"])

            args.extend(["--dump-header", str(header_path), "--output", str(body_path)])
            result = subprocess.run(args, capture_output=True, text=True, timeout=timeout + 5)
            if result.returncode != 0:
                raise RuntimeError(f"curl.exe request failed ({result.returncode}): {result.stderr.strip() or result.stdout.strip()}")

            body = body_path.read_bytes()
            headers = header_path.read_text(encoding="iso-8859-1", errors="replace")
            return body, headers
        finally:
            for path in [body_path, header_path, data_path]:
                if path:
                    try:
                        path.unlink(missing_ok=True)
                    except OSError:
                        pass

    def fetch(self, url: str, timeout: int = 20, reload_retry: bool = True, reload_attempts: int = 4) -> str:
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5",
            "Cache-Control": "no-cache",
            "Connection": "close",
            "Upgrade-Insecure-Requests": "1",
            "Referer": "https://www.mtslash.life/",
        }
        cookie_header = self.cookie_header()
        if cookie_header:
            headers["Cookie"] = cookie_header
        attempts = max(1, reload_attempts if reload_retry else 1)
        html = ""
        for attempt in range(1, attempts + 1):
            request = Request(url, headers=headers)
            try:
                with self.opener.open(request, timeout=timeout) as response:
                    charset = response.headers.get_content_charset() or "utf-8"
                    html = response.read().decode(charset, errors="replace")
            except HTTPError as exc:
                raise RuntimeError(f"请求失败 HTTP {exc.code}: {url}") from exc
            except URLError as exc:
                if not should_retry_with_curl(exc.reason):
                    raise RuntimeError(describe_network_error("请求失败", exc.reason)) from exc
                try:
                    body, header_text = self._curl_request(
                        url=url,
                        timeout=timeout,
                        accept="text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        referer=BASE_URL,
                    )
                    charset_match = re.search(r"charset=([^;\s]+)", header_text, re.I)
                    charset = charset_match.group(1) if charset_match else "utf-8"
                    html = body.decode(charset, errors="replace")
                except RuntimeError as curl_exc:
                    raise RuntimeError(f"{describe_network_error('请求失败', exc.reason)}；curl 回退也失败: {curl_exc}") from exc

            if not reload_retry or not is_reload_page(html):
                return html
            if attempt < attempts:
                time.sleep(1.2 + attempt * 0.4)
        return html

    def fetch_bytes(self, url: str, timeout: int = 20) -> tuple:
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5",
            "Cache-Control": "no-cache",
            "Connection": "close",
            "Referer": BASE_URL,
        }
        cookie_header = self.cookie_header()
        if cookie_header:
            headers["Cookie"] = cookie_header
        request = Request(url, headers=headers)
        try:
            with self.opener.open(request, timeout=timeout) as response:
                content_type = response.headers.get("Content-Type", "image/png").split(";")[0]
                return response.read(), content_type
        except HTTPError as exc:
            raise RuntimeError(f"验证码请求失败 HTTP {exc.code}") from exc
        except URLError as exc:
            if not should_retry_with_curl(exc.reason):
                raise RuntimeError(describe_network_error("验证码请求失败", exc.reason)) from exc
            try:
                body, header_text = self._curl_request(
                    url=url,
                    timeout=timeout,
                    accept="image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
                    referer=BASE_URL,
                )
                content_type = parse_header_content_type(header_text, "image/png")
                return body, content_type
            except RuntimeError as curl_exc:
                raise RuntimeError(f"{describe_network_error('验证码请求失败', exc.reason)}；curl 回退也失败: {curl_exc}") from exc

    def post(self, url: str, data: Dict[str, str], timeout: int = 20) -> str:
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5",
            "Cache-Control": "no-cache",
            "Connection": "close",
            "Referer": BASE_URL,
            "Content-Type": "application/x-www-form-urlencoded; charset=GBK",
        }
        cookie_header = self.cookie_header()
        if cookie_header:
            headers["Cookie"] = cookie_header
        encoded = urlencode(data, encoding="gbk", errors="ignore").encode("ascii", errors="ignore")
        request = Request(url, data=encoded, headers=headers)
        try:
            with self.opener.open(request, timeout=timeout) as response:
                charset = response.headers.get_content_charset() or "gbk"
                html = response.read().decode(charset, errors="replace")
        except HTTPError as exc:
            raise RuntimeError(f"登录请求失败 HTTP {exc.code}") from exc
        except URLError as exc:
            if not should_retry_with_curl(exc.reason):
                raise RuntimeError(describe_network_error("登录请求失败", exc.reason)) from exc
            try:
                body, header_text = self._curl_request(
                    url=url,
                    timeout=timeout,
                    accept="text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    referer=BASE_URL,
                    data=encoded,
                )
                charset_match = re.search(r"charset=([^;\s]+)", header_text, re.I)
                charset = charset_match.group(1) if charset_match else "gbk"
                html = body.decode(charset, errors="replace")
            except RuntimeError as curl_exc:
                raise RuntimeError(f"{describe_network_error('登录请求失败', exc.reason)}；curl 回退也失败: {curl_exc}") from exc
        if is_reload_page(html):
            time.sleep(1.2)
            html = self.fetch(BASE_URL, timeout=timeout, reload_retry=False)
        return html

    def cookie_header(self) -> str:
        cookies = [f"{cookie.name}={cookie.value}" for cookie in self.cookie_jar]
        try:
            for line in self.curl_cookie_path.read_text(encoding="utf-8", errors="replace").splitlines():
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) >= 7:
                    cookies.append(f"{parts[5]}={parts[6]}")
        except OSError:
            pass
        return "; ".join(dict.fromkeys(cookies))


def is_empty_or_interstitial_page(html: str, root: HtmlNode) -> bool:
    if is_reload_page(html):
        return True
    text = root.text()
    markers = [
        r'id=["\']postmessage_\d+',
        r'id=["\']post_\d+',
        r'id=["\']pid\d+',
        r'class=["\'][^"\']*\bplhin\b',
        r'class=["\'][^"\']*\bt_f\b',
    ]
    if len(html) < 2500 and len(text) < 20 and not any(re.search(pattern, html, re.I) for pattern in markers):
        return True
    return False


def fetch_thread_page(fetch_client: FetchClient, url: str, warm_url: str, delay_seconds: float, attempts: int = 4) -> tuple:
    last_html = ""
    last_root = parse_html("")
    last_error = ""
    for attempt in range(1, attempts + 1):
        if attempt > 1:
            try:
                fetch_client.fetch(BASE_URL, timeout=35, reload_attempts=2)
                if warm_url != BASE_URL:
                    fetch_client.fetch(warm_url, timeout=35, reload_attempts=2)
            except RuntimeError:
                pass
            time.sleep(delay_seconds + attempt * 0.8)

        try:
            html = fetch_client.fetch(url, timeout=35, reload_attempts=6)
        except RuntimeError as exc:
            last_error = str(exc)
            continue

        root = parse_html(html)
        last_html = html
        last_root = root
        site_message = extract_site_message(root)
        if site_message and any(token in site_message for token in ["尚未登录", "请登录", "没有权限"]):
            last_error = site_message
            continue
        if is_empty_or_interstitial_page(html, root):
            last_error = "返回空白页或站点中间页"
            continue
        return html, root, ""

    return last_html, last_root, last_error


def is_reload_page(html: str) -> bool:
    if RELOAD_TITLE_PATTERN.search(html):
        return True
    return "document.location.reload" in html and "setTimeout" in html


def extract_site_message(root: HtmlNode) -> str:
    candidates: List[str] = []
    for node in root.iter_nodes():
        node_id = node.attrs.get("id", "")
        class_name = node.attrs.get("class", "")
        if node_id == "messagetext" or "alert_info" in class_name or "showmessage" in class_name:
            text = node.text()
            if text:
                candidates.append(text)
    if not candidates:
        title = extract_title(root)
        if "提示信息" in title:
            text = root.text()
            if text:
                candidates.append(text)
    for text in candidates:
        for line in text.splitlines():
            line = line.strip()
            if any(token in line for token in ["尚未登录", "没有权限", "请登录", "抱歉", "不存在", "审核"]):
                return line
    return ""


def raw_document_title(html: str) -> str:
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    if not title_match:
        return ""
    return clean_text(re.sub(r"<[^>]+>", "", title_match.group(1)))


def page_diagnostics(html: str, root: HtmlNode) -> List[str]:
    text = root.text()
    snippet = re.sub(r"\s+", " ", text).strip()[:220]
    title = raw_document_title(html) or extract_title(root)
    markers = {
        "postmessage": len(re.findall(r'id=["\']postmessage_\d+', html, re.I)),
        "post": len(re.findall(r'id=["\']post_\d+', html, re.I)),
        "pid": len(re.findall(r'id=["\']pid\d+', html, re.I)),
        "plhin": len(re.findall(r'class=["\'][^"\']*\bplhin\b', html, re.I)),
        "t_f": len(re.findall(r'class=["\'][^"\']*\bt_f\b', html, re.I)),
    }
    hints = []
    lowered = html.lower()
    for label, tokens in [
        ("登录页/未登录", ["member.php?mod=logging", "请登录", "尚未登录", "loginform"]),
        ("权限或审核提示", ["没有权限", "抱歉", "审核", "不存在"]),
        ("安全验证/拦截页", ["cloudflare", "access denied", "just a moment", "captcha", "验证码"]),
        ("重载跳转页", ["document.location.reload", "页面重载开启"]),
    ]:
        if any(token.lower() in lowered for token in tokens):
            hints.append(label)
    hint_text = "，疑似: " + " / ".join(dict.fromkeys(hints)) if hints else ""
    return [
        f"[DEBUG] 页面标题: {title or '(空)'}；HTML 长度: {len(html)}；正文文本长度: {len(text)}{hint_text}",
        "[DEBUG] 关键 DOM 计数: " + ", ".join(f"{key}={value}" for key, value in markers.items()),
        f"[DEBUG] 页面文本片段: {snippet or '(空)'}",
    ]


def write_debug_html(output_dir: Path, html: str, page: int) -> str:
    debug_dir = output_dir / "_debug"
    debug_dir.mkdir(parents=True, exist_ok=True)
    debug_path = debug_dir / f"mtslash_page_{page}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
    debug_path.write_text(html, encoding="utf-8", errors="replace")
    return str(debug_path)


def write_login_debug_html(html: str) -> str:
    debug_dir = ROOT_DIR / "backend" / "data" / "_debug"
    debug_dir.mkdir(parents=True, exist_ok=True)
    debug_path = debug_dir / f"mtslash_login_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
    debug_path.write_text(html, encoding="utf-8", errors="replace")
    return str(debug_path)


def extract_login_error(root: HtmlNode) -> str:
    priority_tokens = ["验证码", "密码", "登录失败", "错误", "抱歉", "安全提问"]
    ignored_lines = {"登录", "立即登录", "登录帐号", "用户名", "密码", "找回密码", "注册", "自动登录"}
    containers: List[str] = []
    for node in root.iter_nodes():
        node_id = node.attrs.get("id", "")
        class_name = node.attrs.get("class", "")
        if node_id.startswith("returnmessage") or node_id == "messagetext" or "alert_" in class_name:
            text = node.text()
            if text:
                containers.append(text)
    containers.append(root.text())
    for text in containers:
        for line in text.splitlines():
            line = line.strip()
            if not line or line == "请 登录 后使用快捷导航" or line in ignored_lines:
                continue
            if any(token in line for token in priority_tokens):
                return line
    return ""


def extract_login_error_text(html: str) -> str:
    unescaped = unescape(html)
    cdata_match = re.search(r"<!\[CDATA\[(.*?)\]\]>", unescaped, re.S)
    if cdata_match:
        unescaped = cdata_match.group(1)
    dialog_match = re.search(r"showDialog\('([^']+)'", unescaped, re.S)
    if dialog_match:
        dialog_text = clean_text(dialog_match.group(1))
        if dialog_text:
            return dialog_text
    succeed_match = re.search(r"succeedhandle_[^(]+\([^,]+,\s*'([^']+)'", unescaped, re.S)
    if succeed_match:
        succeed_text = clean_text(succeed_match.group(1))
        if succeed_text:
            return succeed_text
    unescaped = re.sub(r"<script\b.*?</script>", "", unescaped, flags=re.I | re.S)
    unescaped = re.sub(r"<[^>]+>", "\n", unescaped)
    for line in clean_text(unescaped).splitlines():
        line = line.strip()
        if not line or line == "请 登录 后使用快捷导航":
            continue
        if line in {"登录", "立即登录", "登录帐号", "用户名", "密码", "找回密码", "注册", "自动登录"}:
            continue
        if any(token in line for token in ["验证码", "密码错误", "登录失败", "抱歉", "错误", "失败", "安全提问", "不存在"]):
            return line
    return ""


def login_failure_diagnostics(html: str, root: HtmlNode) -> str:
    title = raw_document_title(html) or extract_title(root)
    text = root.text()
    lines = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line in {"登录", "立即登录", "用户名", "密码", "找回密码", "注册", "自动登录"}:
            continue
        lines.append(line)
        if len(lines) >= 3:
            break
    suffix = f"，页面标题: {title}" if title else ""
    if lines:
        suffix += f"，页面片段: {' / '.join(lines)[:160]}"
    return suffix


def _match_required(pattern: str, text: str, label: str) -> str:
    match = re.search(pattern, text, re.I)
    if not match:
        title_match = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
        title = clean_text(re.sub(r"<[^>]+>", "", title_match.group(1))) if title_match else ""
        hint = f"，页面标题: {title}" if title else ""
        raise RuntimeError(f"登录页缺少 {label}，可能页面结构已变化或当前网络返回了拦截页{hint}")
    return match.group(1)


def _match_optional(pattern: str, text: str) -> str:
    match = re.search(pattern, text, re.I)
    return match.group(1) if match else ""


def extract_login_tokens(html: str) -> Dict[str, str]:
    return {
        "formhash": _match_optional(r'name="formhash"\s+value="([A-Za-z0-9]+)"', html),
        "loginhash": _match_optional(r"loginhash=([A-Za-z0-9]+)", html),
        "seccodehash": _match_optional(r"updateseccode\('([^']+)'", html),
    }


def extract_login_form(html: str, base_url: str) -> tuple:
    root = parse_html(html)
    fallback_action = ""
    fallback_fields: Dict[str, str] = {}

    for form in root.iter_nodes():
        if form.tag != "form":
            continue
        action = form.attrs.get("action", "")
        fields: Dict[str, str] = {}
        for node in form.iter_nodes():
            if node.tag != "input":
                continue
            name = node.attrs.get("name", "")
            if not name:
                continue
            fields[name] = node.attrs.get("value", "")

        merged = " ".join([action, " ".join(fields.keys()), " ".join(fields.values())]).lower()
        absolute_action = urljoin(base_url, unescape(action.replace("&amp;", "&"))) if action else ""
        if "member.php" in merged and ("loginfield" in fields or "username" in fields or "password" in fields):
            return absolute_action, fields
        if not fallback_action and ("login" in merged or "logging" in merged):
            fallback_action = absolute_action
            fallback_fields = fields

    return fallback_action, fallback_fields


def start_mtslash_login_session() -> Dict[str, str]:
    fetch_client = FetchClient(cookie="", user_agent=DEFAULT_USER_AGENT)
    entry_html = fetch_client.fetch(BASE_URL, timeout=35)
    tokens = extract_login_tokens(entry_html)
    login_action, login_fields = extract_login_form(entry_html, BASE_URL)
    login_html = entry_html
    if not all(tokens.values()):
        login_html = fetch_client.fetch(LOGIN_URL, timeout=35)
        tokens = extract_login_tokens(login_html)
        login_action, login_fields = extract_login_form(login_html, LOGIN_URL)

    formhash = tokens["formhash"] or _match_required(r'name="formhash"\s+value="([A-Za-z0-9]+)"', login_html, "formhash")
    loginhash = tokens["loginhash"] or _match_required(r"loginhash=([A-Za-z0-9]+)", login_html, "loginhash")
    seccodehash = tokens["seccodehash"] or _match_required(r"updateseccode\('([^']+)'", login_html, "seccodehash")
    if not login_action:
        login_action = f"{BASE_URL}member.php?mod=logging&action=login&loginsubmit=yes&loginhash={loginhash}&inajax=1"

    update_url = (
        f"{BASE_URL}misc.php?mod=seccode&action=update&idhash={seccodehash}"
        f"&inajax=1&ajaxtarget=seccode_{seccodehash}"
    )
    update_html = fetch_client.fetch(update_url, timeout=35)
    image_src = _match_required(r'src="([^"]*misc\.php\?mod=seccode[^"]+)"', update_html, "验证码图片")
    image_url = urljoin(BASE_URL, image_src.replace("&amp;", "&"))
    image_bytes, content_type = fetch_client.fetch_bytes(image_url, timeout=35)
    captcha_image = f"data:{content_type};base64,{base64.b64encode(image_bytes).decode('ascii')}"

    session_id = uuid.uuid4().hex
    LOGIN_SESSIONS[session_id] = LoginSession(
        session_id=session_id,
        fetch_client=fetch_client,
        formhash=formhash,
        loginhash=loginhash,
        seccodehash=seccodehash,
        login_action=login_action,
        login_fields=login_fields,
        captcha_image=captcha_image,
    )
    return {
        "session_id": session_id,
        "captcha_image": captcha_image,
        "message": "验证码已获取，请人工输入图片中的字符。",
    }


def login_with_session(session_id: str, username: str, password: str, captcha_code: str, question_id: str = "0", answer: str = "") -> tuple:
    session = LOGIN_SESSIONS.get(session_id.strip())
    if session is None:
        raise RuntimeError("登录会话不存在或已过期，请重新获取验证码")
    if session.authenticated:
        return session.fetch_client, "已登录，继续复用本次内存会话。"

    username = username.strip()
    captcha_code = captcha_code.strip()
    if not username or not password:
        raise RuntimeError("未填写账号或密码")
    if not captcha_code:
        raise RuntimeError("未填写验证码")

    now = time.monotonic()
    last_attempt = max(session.last_login_attempt, LAST_LOGIN_ATTEMPTS.get(username, 0.0))
    remaining = LOGIN_COOLDOWN_SECONDS - (now - last_attempt)
    if remaining > 0:
        raise RuntimeError(f"登录请求冷却中，请 {int(remaining) + 1} 秒后再试")

    session.last_login_attempt = now
    session.username = username
    LAST_LOGIN_ATTEMPTS[username] = now

    login_url = f"{BASE_URL}member.php?mod=logging&action=login&loginsubmit=yes&loginhash={session.loginhash}&inajax=1"

    login_payload = dict(session.login_fields)
    login_payload.update(
        {
            "formhash": session.formhash,
            "referer": BASE_URL,
            "handlekey": f"loginform_{session.loginhash}",
            "loginfield": "username",
            "username": username,
            "password": password,
            "questionid": question_id.strip() or "0",
            "answer": answer,
            "seccodehash": session.seccodehash,
            "seccodemodid": "member::logging",
            "seccodeverify": captcha_code,
            "cookietime": login_payload.get("cookietime", "2592000") or "2592000",
            "loginsubmit": "true",
        }
    )
    html = session.fetch_client.post(login_url, login_payload)
    root = parse_html(html)
    cookie_header = session.fetch_client.cookie_header()
    if "auth" in cookie_header:
        session.authenticated = True
        return session.fetch_client, "登录成功，后续导出会复用本次内存会话。"

    message = extract_login_error_text(html) or extract_login_error(root) or extract_site_message(root)
    if "欢迎您回来" in message:
        session.authenticated = True
        return session.fetch_client, f"{message}。已保留本次会话，收藏夹和导出权限以后续页面实际返回为准。"
    if not message:
        message = "登录未成功，未收到站点登录 Cookie。请重新获取验证码后再试"
    message = f"{message}{login_failure_diagnostics(html, root)}"
    try:
        debug_path = write_login_debug_html(html)
        message = f"{message}，登录返回页已保存: {debug_path}"
    except OSError:
        pass
    raise RuntimeError(message)


def submit_mtslash_login(values: Dict[str, str]) -> Dict[str, str]:
    session_id = values.get("login_session_id", "").strip()
    username = values.get("login_username", "").strip()
    password = values.get("login_password", "")
    captcha_code = values.get("captcha_code", "").strip()
    question_id = values.get("question_id", "0")
    answer = values.get("answer", "")
    _, message = login_with_session(
        session_id=session_id,
        username=username,
        password=password,
        captcha_code=captcha_code,
        question_id=question_id,
        answer=answer,
    )
    return {
        "status": "success",
        "message": message,
        "session_id": session_id,
    }


def authenticated_fetch_client(session_id: str) -> Optional[FetchClient]:
    session = LOGIN_SESSIONS.get(session_id.strip())
    if session and session.authenticated:
        return session.fetch_client
    return None


def fetch_mtslash_favorites(session_id: str, max_pages: int = 50) -> Dict[str, object]:
    fetch_client = authenticated_fetch_client(session_id)
    if fetch_client is None:
        raise RuntimeError("尚未登录或登录会话已过期，请先获取验证码并登录")

    all_threads: List[FavoriteThread] = []
    seen_urls = set()
    first_html = fetch_client.fetch(FAVORITES_URL, timeout=35)
    first_root = parse_html(first_html)
    site_message = extract_site_message(first_root)
    if site_message:
        raise RuntimeError(f"收藏夹页面不可用: {site_message}")

    total_pages = extract_favorite_max_page(first_root, FAVORITES_URL, max_pages=max_pages)
    for page in range(1, total_pages + 1):
        if page == 1:
            root = first_root
            current_url = FAVORITES_URL
        else:
            current_url = query_page_url(FAVORITES_URL, page)
            html = fetch_client.fetch(current_url, timeout=35)
            root = parse_html(html)

        for item in extract_favorite_threads(root, current_url):
            if item.url in seen_urls:
                continue
            seen_urls.add(item.url)
            all_threads.append(item)

    return {
        "status": "success",
        "page_count": total_pages,
        "items": [{"title": item.title, "url": item.url} for item in all_threads],
    }


def extract_title(root: HtmlNode) -> str:
    title = first_text(root, lambda node: node.attrs.get("id") == "thread_subject")
    if title:
        return title
    h1 = first_text(root, lambda node: node.tag == "h1")
    if h1:
        return h1
    document_title = first_text(root, lambda node: node.tag == "title")
    return re.sub(r"[-_].*$", "", document_title).strip() or "mtslash_thread"


def page_url(base_url: str, page: int) -> str:
    parsed = urlparse(base_url)
    match = re.search(r"thread-(\d+)-(\d+)-(\d+)\.html", parsed.path)
    if match:
        path = re.sub(r"thread-(\d+)-(\d+)-(\d+)\.html", f"thread-{match.group(1)}-{page}-{match.group(3)}.html", parsed.path)
        return urlunparse(parsed._replace(path=path))

    query = parse_qs(parsed.query)
    if "page" in query or "tid" in query:
        query["page"] = [str(page)]
        encoded = "&".join(f"{key}={values[0]}" for key, values in query.items())
        return urlunparse(parsed._replace(query=encoded))

    return base_url


def query_page_url(base_url: str, page: int) -> str:
    parsed = urlparse(base_url)
    query = parse_qs(parsed.query)
    query["page"] = [str(page)]
    encoded = urlencode({key: values[0] for key, values in query.items()})
    return urlunparse(parsed._replace(query=encoded))


def extract_max_page(root: HtmlNode, current_url: str, max_pages: int) -> int:
    pages = {1}
    for node in root.iter_nodes():
        if node.tag != "a":
            continue
        href = node.attrs.get("href", "")
        absolute = urljoin(current_url, href)
        parsed = urlparse(absolute)
        if parsed.hostname not in ALLOWED_HOSTS:
            continue
        match = re.search(r"thread-\d+-(\d+)-\d+\.html", parsed.path)
        if match:
            pages.add(int(match.group(1)))
            continue
        query_page = parse_qs(parsed.query).get("page", [""])[0]
        if query_page.isdigit():
            pages.add(int(query_page))
    return min(max(pages), max_pages)


def extract_favorite_max_page(root: HtmlNode, current_url: str, max_pages: int = 200) -> int:
    pages = {1}
    for node in root.iter_nodes():
        if node.tag != "a":
            continue
        href = node.attrs.get("href", "")
        absolute = urljoin(current_url, href)
        parsed = urlparse(absolute)
        if parsed.hostname not in ALLOWED_HOSTS:
            continue
        query_page = parse_qs(parsed.query).get("page", [""])[0]
        if query_page.isdigit():
            pages.add(int(query_page))
    return min(max(pages), max_pages)


def extract_favorite_threads(root: HtmlNode, current_url: str) -> List[FavoriteThread]:
    threads: List[FavoriteThread] = []
    seen_urls = set()
    for node in root.iter_nodes():
        if node.tag != "a":
            continue
        href = node.attrs.get("href", "")
        absolute = urljoin(current_url, href.replace("&amp;", "&"))
        parsed = urlparse(absolute)
        if parsed.hostname not in ALLOWED_HOSTS:
            continue
        if not (re.search(r"/thread-\d+-\d+-\d+\.html$", parsed.path) or parse_qs(parsed.query).get("tid")):
            continue

        title = node.attrs.get("title", "").strip() or node.text()
        title = clean_text(title).replace("\n", " ").strip()
        if not title or title in {"查看详情", "回复", "删除", "编辑"}:
            continue
        normalized_url = urlunparse(parsed._replace(fragment=""))
        if normalized_url in seen_urls:
            continue
        seen_urls.add(normalized_url)
        threads.append(FavoriteThread(title=title, url=normalized_url))
    return threads


def find_content_node(post_node: HtmlNode) -> HtmlNode:
    for node in post_node.iter_nodes():
        node_id = node.attrs.get("id", "")
        if node_id.startswith("postmessage_"):
            return node
    for node in post_node.iter_nodes():
        if has_class(node, "t_f") or class_contains(node, "postmessage"):
            return node
    return post_node


def extract_author(post_node: HtmlNode) -> tuple:
    for node in post_node.iter_nodes():
        if has_class(node, "authi") or class_contains(node, "pls"):
            for child in node.iter_nodes():
                if child.tag == "a":
                    author = child.text()
                    href = child.attrs.get("href", "")
                    uid_match = re.search(r"(?:uid-|uid=)(\d+)", href)
                    return author, uid_match.group(1) if uid_match else ""
            text = node.text().split("\n")[0].strip()
            if text:
                return text, ""
    return "", ""


def nearest_post_container(node: HtmlNode) -> HtmlNode:
    current: Optional[HtmlNode] = node
    while current is not None:
        node_id = current.attrs.get("id", "")
        if re.fullmatch(r"(post_|pid)\d+", node_id) or has_class(current, "plhin"):
            return current
        current = current.parent
    return node


def extract_posts(root: HtmlNode, source_url: str) -> List[Post]:
    candidates: List[HtmlNode] = []
    seen_ids = set()
    for node in root.iter_nodes():
        node_id = node.attrs.get("id", "")
        content_id = node_id.startswith("postmessage_")
        post_container = re.fullmatch(r"(post_|pid)\d+", node_id) or has_class(node, "plhin")
        if post_container or content_id:
            candidate = nearest_post_container(node) if content_id else node
            key = candidate.attrs.get("id", "") or node_id or str(id(candidate))
            if key not in seen_ids:
                candidates.append(candidate)
                seen_ids.add(key)

    posts: List[Post] = []
    for index, node in enumerate(candidates, start=1):
        pid_match = re.search(r"\d+", node.attrs.get("id", ""))
        pid = pid_match.group(0) if pid_match else f"post-{index}"
        content_node = find_content_node(node)
        text = content_node.text()
        if len(text) < 20:
            continue
        author, uid = extract_author(node)
        posts.append(Post(pid=pid, author=author, uid=uid, text=text, source_url=source_url))
    return posts


def chapter_title(post: Post, index: int) -> str:
    for line in post.text.splitlines():
        if CHAPTER_PATTERN.search(line):
            return line[:80]
    return f"第 {index} 节"


def safe_filename(value: str) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")
    return value[:80] or "mtslash_thread"


def write_txt(output_path: Path, title: str, source_url: str, posts: List[Post]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    chapters = [(chapter_title(post, index), post) for index, post in enumerate(posts, start=1)]
    with open(output_path, "w", encoding="utf-8") as file_obj:
        file_obj.write(f"{title}\n")
        file_obj.write(f"来源: {source_url}\n")
        file_obj.write(f"导出时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        file_obj.write("说明: 仅导出你有权访问的单帖内容，请遵守站点条款和版权要求。\n\n")
        file_obj.write("目录\n")
        for index, (heading, post) in enumerate(chapters, start=1):
            author = f" - {post.author}" if post.author else ""
            file_obj.write(f"{index:02d}. {heading}{author}\n")
        file_obj.write("\n" + "=" * 64 + "\n\n")

        for index, (heading, post) in enumerate(chapters, start=1):
            file_obj.write(f"{index:02d}. {heading}\n")
            if post.author:
                file_obj.write(f"作者: {post.author}\n")
            file_obj.write(f"原帖位置: {post.source_url}#pid{post.pid}\n\n")
            file_obj.write(post.text)
            file_obj.write("\n\n" + "-" * 64 + "\n\n")


def run_mtslash_export(values: Dict[str, str]) -> ToolRunResponse:
    thread_url = validate_thread_url(values.get("thread_url", ""))
    output_dir = Path(values.get("output_dir", "").strip() or (ROOT_DIR / "output"))
    only_thread_author = _bool_value(values.get("only_thread_author"), True)
    max_pages = _int_value(values.get("max_pages"), default=20, minimum=1, maximum=80)
    delay_seconds = _float_value(values.get("delay_seconds"), default=1.5, minimum=1.0, maximum=10.0)
    cookie = values.get("cookie", "")
    user_agent = values.get("user_agent", "").strip() or DEFAULT_USER_AGENT
    login_username = values.get("login_username", "").strip()
    login_password = values.get("login_password", "")
    captcha_code = values.get("captcha_code", "").strip()
    login_session_id = values.get("login_session_id", "").strip()
    question_id = values.get("question_id", "0")
    answer = values.get("answer", "")

    if not robots_allowed(thread_url, user_agent):
        return ToolRunResponse(
            tool="mtslash_export",
            status="blocked",
            summary="robots.txt 不允许抓取该地址，已停止。",
            logs=[f"[WARN] robots.txt disallow: {thread_url}"],
            data={},
        )

    logs = [
        "[INFO] 合规模式: 单帖导出、限页、请求间隔、robots.txt 检查",
        f"[INFO] 起始地址: {thread_url}",
        f"[INFO] 最大页数: {max_pages}",
        f"[INFO] 请求间隔: {delay_seconds:.1f}s",
    ]

    def error_response(message: str) -> ToolRunResponse:
        logs.append(f"[ERROR] {message}")
        return ToolRunResponse(
            tool="mtslash_export",
            status="error",
            summary=message,
            logs=logs,
            data={},
        )

    if cookie.strip():
        fetch_client = FetchClient(cookie=cookie, user_agent=user_agent)
        logs.append("[INFO] 使用手动 Cookie 访问，不执行账号登录")
    elif authenticated_fetch_client(login_session_id) is not None:
        fetch_client = authenticated_fetch_client(login_session_id)
        logs.append("[INFO] 使用已登录的内存会话访问，不重复提交登录")
    elif login_username or login_password or captcha_code:
        logs.append("[INFO] 使用一次性登录会话访问，登录失败不会自动重试")
        try:
            fetch_client, login_message = login_with_session(
                session_id=login_session_id,
                username=login_username,
                password=login_password,
                captcha_code=captcha_code,
                question_id=question_id,
                answer=answer,
            )
        except RuntimeError as exc:
            logs.append(f"[ERROR] 登录失败: {exc}")
            return ToolRunResponse(
                tool="mtslash_export",
                status="error",
                summary=f"登录失败: {exc}",
                logs=logs,
                data={},
            )
        logs.append(f"[INFO] {login_message}")
    else:
        fetch_client = FetchClient(cookie="", user_agent=user_agent)
        logs.append("[INFO] 未提供 Cookie 或登录信息，将以游客身份访问")

    first_html, first_root, first_error = fetch_thread_page(fetch_client, thread_url, BASE_URL, delay_seconds, attempts=5)
    if first_error:
        logs.append(f"[WARN] 帖子首页多次重试后仍异常: {first_error}")
        if first_html:
            logs.extend(page_diagnostics(first_html, first_root))
            try:
                debug_path = write_debug_html(output_dir, first_html, 1)
                logs.append(f"[DEBUG] 已保存返回页 HTML: {debug_path}")
            except OSError as exc:
                logs.append(f"[WARN] 保存返回页 HTML 失败: {exc}")
        return ToolRunResponse(
            tool="mtslash_export",
            status="error",
            summary=f"抓取帖子首页失败: {first_error}",
            logs=logs,
            data={},
        )

    title = extract_title(first_root)
    first_message = extract_site_message(first_root)
    if first_message:
        logs.append(f"[WARN] 站点提示: {first_message}")
        return ToolRunResponse(
            tool="mtslash_export",
            status="blocked",
            summary=f"站点未返回帖子正文: {first_message}",
            logs=logs,
            data={},
        )
    total_pages = extract_max_page(first_root, thread_url, max_pages)
    logs.append(f"[INFO] 帖子标题: {title}")
    logs.append(f"[INFO] 计划抓取页数: {total_pages}")

    all_posts: List[Post] = []
    seen_pids = set()
    thread_author_key = ""

    for page in range(1, total_pages + 1):
        current_url = thread_url if page == 1 else page_url(thread_url, page)
        html = first_html
        if page > 1:
            time.sleep(delay_seconds)
            if not robots_allowed(current_url, user_agent):
                logs.append(f"[WARN] robots.txt disallow: {current_url}")
                break
            html, root, page_error = fetch_thread_page(fetch_client, current_url, thread_url, delay_seconds, attempts=4)
            if page_error:
                logs.append(f"[WARN] 抓取第 {page} 页失败，已停止后续分页: {page_error}")
                if html:
                    logs.extend(page_diagnostics(html, root))
                    try:
                        debug_path = write_debug_html(output_dir, html, page)
                        logs.append(f"[DEBUG] 已保存返回页 HTML: {debug_path}")
                    except OSError as exc:
                        logs.append(f"[WARN] 保存返回页 HTML 失败: {exc}")
                break
        else:
            root = first_root

        site_message = extract_site_message(root)
        if site_message:
            logs.append(f"[WARN] 第 {page} 页站点提示: {site_message}")
            break

        posts = extract_posts(root, current_url)
        if not posts:
            logs.append(f"[WARN] 第 {page} 页没有解析到正文，停止。")
            logs.extend(page_diagnostics(html, root))
            try:
                debug_path = write_debug_html(output_dir, html, page)
                logs.append(f"[DEBUG] 已保存返回页 HTML: {debug_path}")
            except OSError as exc:
                logs.append(f"[WARN] 保存返回页 HTML 失败: {exc}")
            break

        if not thread_author_key:
            first_post = posts[0]
            thread_author_key = first_post.uid or first_post.author

        accepted = 0
        for post in posts:
            if post.pid in seen_pids:
                continue
            author_key = post.uid or post.author
            if only_thread_author and thread_author_key:
                if not author_key or author_key != thread_author_key:
                    continue
            seen_pids.add(post.pid)
            all_posts.append(post)
            accepted += 1
        logs.append(f"[INFO] 第 {page} 页: 解析 {len(posts)} 楼，收录 {accepted} 楼")

    if not all_posts:
        return ToolRunResponse(
            tool="mtslash_export",
            status="error",
            summary="没有导出任何正文。请确认帖子可访问，必要时填写你自己的 Cookie。",
            logs=logs,
            data={},
        )

    output_path = output_dir / f"{safe_filename(title)}.txt"
    try:
        write_txt(output_path, title, thread_url, all_posts)
    except OSError as exc:
        return error_response(f"写入导出文件失败: {exc}")
    summary = f"已导出 {len(all_posts)} 段正文到 TXT。"
    if len(all_posts) > 0 and len(seen_pids) > 0 and total_pages > 1:
        fetched_pages = len({urlparse(post.source_url).path + "?" + urlparse(post.source_url).query for post in all_posts})
        if fetched_pages < total_pages:
            summary = f"已部分导出 {len(all_posts)} 段正文到 TXT，后续分页因网络或站点返回异常已停止。"
    logs.append(f"[INFO] 输出文件: {output_path}")
    return ToolRunResponse(
        tool="mtslash_export",
        status="success",
        summary=summary,
        logs=logs,
        data={
            "output_path": str(output_path),
            "post_count": len(all_posts),
            "title": title,
            "source_url": thread_url,
        },
    )
