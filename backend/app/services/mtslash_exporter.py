import re
import time
import uuid
import base64
from http.cookiejar import CookieJar
from dataclasses import dataclass, field
from datetime import datetime
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, Iterable, List, Optional
from urllib import robotparser
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen

from app.models import ToolRunResponse


ALLOWED_HOSTS = {"mtslash.life", "www.mtslash.life"}
DEFAULT_USER_AGENT = "TreeMoonBox/1.0 personal thread exporter"
SKIP_TEXT_TAGS = {"script", "style", "noscript", "template"}
CHAPTER_PATTERN = re.compile(r"(第\s*[0-9一二三四五六七八九十百千万零〇两]+\s*[章节回幕卷篇]|chapter\s*\d+)", re.I)
RELOAD_TITLE_PATTERN = re.compile(r"页面重载开启|&#x9875;&#x9762;&#x91cd;&#x8f7d;&#x5f00;&#x542f;", re.I)
LOGIN_URL = "https://www.mtslash.life/member.php?mod=logging&action=login"
BASE_URL = "https://www.mtslash.life/"
LOGIN_COOLDOWN_SECONDS = 60.0


@dataclass
class LoginSession:
    session_id: str
    fetch_client: "FetchClient"
    formhash: str
    loginhash: str
    seccodehash: str
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


class FetchClient:
    def __init__(self, cookie: str, user_agent: str) -> None:
        self.cookie = cookie.strip()
        self.user_agent = user_agent
        self.cookie_jar = CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(self.cookie_jar))

    def fetch(self, url: str, timeout: int = 20, reload_retry: bool = True) -> str:
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5",
            "Referer": "https://www.mtslash.life/",
        }
        if self.cookie:
            headers["Cookie"] = self.cookie
        request = Request(url, headers=headers)
        try:
            with self.opener.open(request, timeout=timeout) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                html = response.read().decode(charset, errors="replace")
        except HTTPError as exc:
            raise RuntimeError(f"请求失败 HTTP {exc.code}: {url}") from exc
        except URLError as exc:
            raise RuntimeError(f"请求失败: {exc.reason}") from exc

        if reload_retry and is_reload_page(html):
            time.sleep(1.2)
            return self.fetch(url, timeout=timeout, reload_retry=False)
        return html

    def fetch_bytes(self, url: str, timeout: int = 20) -> tuple:
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5",
            "Referer": BASE_URL,
        }
        request = Request(url, headers=headers)
        try:
            with self.opener.open(request, timeout=timeout) as response:
                content_type = response.headers.get("Content-Type", "image/png").split(";")[0]
                return response.read(), content_type
        except HTTPError as exc:
            raise RuntimeError(f"验证码请求失败 HTTP {exc.code}") from exc
        except URLError as exc:
            raise RuntimeError(f"验证码请求失败: {exc.reason}") from exc

    def post(self, url: str, data: Dict[str, str], timeout: int = 20) -> str:
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5",
            "Referer": LOGIN_URL,
            "Content-Type": "application/x-www-form-urlencoded",
        }
        encoded = urlencode(data, encoding="gbk", errors="ignore").encode("ascii", errors="ignore")
        request = Request(url, data=encoded, headers=headers)
        try:
            with self.opener.open(request, timeout=timeout) as response:
                charset = response.headers.get_content_charset() or "gbk"
                html = response.read().decode(charset, errors="replace")
        except HTTPError as exc:
            raise RuntimeError(f"登录请求失败 HTTP {exc.code}") from exc
        except URLError as exc:
            raise RuntimeError(f"登录请求失败: {exc.reason}") from exc
        if is_reload_page(html):
            time.sleep(1.2)
            html = self.fetch(BASE_URL, timeout=timeout, reload_retry=False)
        return html

    def cookie_header(self) -> str:
        return "; ".join(f"{cookie.name}={cookie.value}" for cookie in self.cookie_jar)


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


def extract_login_error(root: HtmlNode) -> str:
    priority_tokens = ["验证码", "密码", "登录失败", "错误", "抱歉", "安全提问"]
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
            if not line or line == "请 登录 后使用快捷导航":
                continue
            if any(token in line for token in priority_tokens):
                return line
    return ""


def extract_login_error_text(html: str) -> str:
    unescaped = unescape(html)
    cdata_match = re.search(r"<!\[CDATA\[(.*?)\]\]>", unescaped, re.S)
    if cdata_match:
        unescaped = cdata_match.group(1)
    unescaped = re.sub(r"<script\b.*?</script>", "", unescaped, flags=re.I | re.S)
    unescaped = re.sub(r"<[^>]+>", "\n", unescaped)
    for line in clean_text(unescaped).splitlines():
        line = line.strip()
        if not line or line == "请 登录 后使用快捷导航":
            continue
        if any(token in line for token in ["验证码", "密码", "登录", "抱歉", "错误", "失败", "安全提问", "不存在"]):
            return line
    return ""


def _match_required(pattern: str, text: str, label: str) -> str:
    match = re.search(pattern, text, re.I)
    if not match:
        raise RuntimeError(f"登录页缺少 {label}，可能页面结构已变化")
    return match.group(1)


def start_mtslash_login_session() -> Dict[str, str]:
    fetch_client = FetchClient(cookie="", user_agent=DEFAULT_USER_AGENT)
    login_html = fetch_client.fetch(LOGIN_URL)
    formhash = _match_required(r'name="formhash"\s+value="([A-Za-z0-9]+)"', login_html, "formhash")
    loginhash = _match_required(r"loginhash=([A-Za-z0-9]+)", login_html, "loginhash")
    seccodehash = _match_required(r"updateseccode\('([^']+)'", login_html, "seccodehash")

    update_url = (
        f"{BASE_URL}misc.php?mod=seccode&action=update&idhash={seccodehash}"
        f"&inajax=1&ajaxtarget=seccode_{seccodehash}"
    )
    update_html = fetch_client.fetch(update_url, reload_retry=False)
    image_src = _match_required(r'src="([^"]*misc\.php\?mod=seccode[^"]+)"', update_html, "验证码图片")
    image_url = urljoin(BASE_URL, image_src.replace("&amp;", "&"))
    image_bytes, content_type = fetch_client.fetch_bytes(image_url)
    captcha_image = f"data:{content_type};base64,{base64.b64encode(image_bytes).decode('ascii')}"

    session_id = uuid.uuid4().hex
    LOGIN_SESSIONS[session_id] = LoginSession(
        session_id=session_id,
        fetch_client=fetch_client,
        formhash=formhash,
        loginhash=loginhash,
        seccodehash=seccodehash,
        captcha_image=captcha_image,
    )
    return {
        "session_id": session_id,
        "captcha_image": captcha_image,
        "message": "验证码已获取，请人工输入图片中的字符。",
    }


def login_with_session(session_id: str, username: str, password: str, captcha_code: str, question_id: str = "0", answer: str = "") -> FetchClient:
    session = LOGIN_SESSIONS.get(session_id.strip())
    if session is None:
        raise RuntimeError("登录会话不存在或已过期，请重新获取验证码")
    if session.authenticated:
        return session.fetch_client

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
    html = session.fetch_client.post(
        login_url,
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
            "cookietime": "2592000",
            "loginsubmit": "true",
        },
    )
    root = parse_html(html)
    cookie_header = session.fetch_client.cookie_header()
    if "auth" in cookie_header:
        session.authenticated = True
        return session.fetch_client

    message = extract_login_error_text(html) or extract_login_error(root) or extract_site_message(root)
    if not message:
        message = "登录未成功，未收到站点登录 Cookie。请重新获取验证码后再试"
    raise RuntimeError(message)


def submit_mtslash_login(values: Dict[str, str]) -> Dict[str, str]:
    session_id = values.get("login_session_id", "").strip()
    username = values.get("login_username", "").strip()
    password = values.get("login_password", "")
    captcha_code = values.get("captcha_code", "").strip()
    question_id = values.get("question_id", "0")
    answer = values.get("answer", "")
    login_with_session(
        session_id=session_id,
        username=username,
        password=password,
        captcha_code=captcha_code,
        question_id=question_id,
        answer=answer,
    )
    return {
        "status": "success",
        "message": "登录成功，后续导出会复用本次内存会话。",
        "session_id": session_id,
    }


def authenticated_fetch_client(session_id: str) -> Optional[FetchClient]:
    session = LOGIN_SESSIONS.get(session_id.strip())
    if session and session.authenticated:
        return session.fetch_client
    return None


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


def extract_posts(root: HtmlNode, source_url: str) -> List[Post]:
    candidates: List[HtmlNode] = []
    seen_ids = set()
    for node in root.iter_nodes():
        node_id = node.attrs.get("id", "")
        if re.fullmatch(r"(post_|pid)\d+", node_id) or has_class(node, "plhin"):
            key = node_id or str(id(node))
            if key not in seen_ids:
                candidates.append(node)
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
    output_dir = Path(values.get("output_dir", "").strip() or "output/mtslash")
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

    if cookie.strip():
        fetch_client = FetchClient(cookie=cookie, user_agent=user_agent)
        logs.append("[INFO] 使用手动 Cookie 访问，不执行账号登录")
    elif authenticated_fetch_client(login_session_id) is not None:
        fetch_client = authenticated_fetch_client(login_session_id)
        logs.append("[INFO] 使用已登录的内存会话访问，不重复提交登录")
    elif login_username or login_password or captcha_code:
        logs.append("[INFO] 使用一次性登录会话访问，登录失败不会自动重试")
        try:
            fetch_client = login_with_session(
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
        logs.append("[INFO] 登录成功，后续请求复用本次内存会话 Cookie")
    else:
        fetch_client = FetchClient(cookie="", user_agent=user_agent)
        logs.append("[INFO] 未提供 Cookie 或登录信息，将以游客身份访问")

    first_html = fetch_client.fetch(thread_url)
    first_root = parse_html(first_html)
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
        if page > 1:
            time.sleep(delay_seconds)
            if not robots_allowed(current_url, user_agent):
                logs.append(f"[WARN] robots.txt disallow: {current_url}")
                break
            html = fetch_client.fetch(current_url)
            root = parse_html(html)
        else:
            root = first_root

        site_message = extract_site_message(root)
        if site_message:
            logs.append(f"[WARN] 第 {page} 页站点提示: {site_message}")
            break

        posts = extract_posts(root, current_url)
        if not posts:
            logs.append(f"[WARN] 第 {page} 页没有解析到正文，停止。")
            break

        if not thread_author_key:
            first_post = posts[0]
            thread_author_key = first_post.uid or first_post.author

        accepted = 0
        for post in posts:
            if post.pid in seen_pids:
                continue
            author_key = post.uid or post.author
            if only_thread_author and thread_author_key and author_key and author_key != thread_author_key:
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
    write_txt(output_path, title, thread_url, all_posts)
    summary = f"已导出 {len(all_posts)} 段正文到 TXT。"
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
