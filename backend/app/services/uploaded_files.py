# 功能说明：接收前端上传的本地文件，并保存为后端可直接读取的临时工具输入文件。
from pathlib import Path
from time import strftime
from uuid import uuid4


UPLOAD_ROOT = Path(__file__).resolve().parents[2] / "data" / "uploads"
ALLOWED_UPLOAD_SUFFIXES = {".pcd", ".yaml", ".yml", ".pgm"}


def _safe_filename(name: str) -> str:
    """将用户文件名收敛为可保存的普通文件名，避免路径穿越或奇怪空名。"""
    source_name = Path(name or "upload.bin").name
    cleaned = "".join(char if char.isalnum() or char in "._-" else "_" for char in source_name)
    return cleaned.strip("._") or "upload.bin"


def save_uploaded_tool_file(content: bytes, filename: str, content_type: str = "", purpose: str = "tool") -> dict:
    """
    功能说明：
    把手机或浏览器选择的文件复制到后端 data/uploads 下，并返回后端本机路径。

    注意事项：
    现有 PCD/YAML/PGM 处理流程都基于后端本机文件路径工作，因此这里不能把
    Android 的 content:// URI 直接传给预览算法，必须先落盘到后端可访问位置。
    """
    if not content:
        raise ValueError("上传文件为空")

    original_name = filename or ""
    safe_name = _safe_filename(original_name)
    suffix = Path(safe_name).suffix.lower()
    if suffix not in ALLOWED_UPLOAD_SUFFIXES:
        raise ValueError(f"不支持的文件类型: {suffix or '无扩展名'}")

    purpose_dir = _safe_filename(purpose or "tool")
    target_dir = UPLOAD_ROOT / purpose_dir / strftime("%Y%m%d")
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"{uuid4().hex[:10]}-{safe_name}"

    target_path.write_bytes(content)

    return {
        "path": str(target_path.resolve()),
        "original_name": original_name,
        "size_bytes": target_path.stat().st_size,
        "content_type": content_type or "",
    }
