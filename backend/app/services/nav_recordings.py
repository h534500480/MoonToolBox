"""功能说明：管理 ROS 导航测试页的小卡片录制文件。"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re

from app.models import (
    NavRecordingFileItem,
    NavRecordingFileListResponse,
    NavRecordingSaveRequest,
)


ROOT_DIR = Path(__file__).resolve().parents[3]
RECORDINGS_DIR = ROOT_DIR / "output_nav" / "recordings"
ALLOWED_SUFFIXES = {".txt", ".png", ".jpg", ".jpeg", ".webp"}
JSON_BEGIN_MARKER = "--- NAV_RECORDING_JSON BEGIN ---"
JSON_END_MARKER = "--- NAV_RECORDING_JSON END ---"


def ensure_recordings_dir() -> Path:
    """确保录制文件目录存在。"""
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    return RECORDINGS_DIR


def sanitize_file_stem(value: str) -> str:
    """把面板标题和话题名转成稳定的文件名前缀。"""
    cleaned = re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]+", "_", value).strip("_")
    return cleaned or "recording"


def build_recording_base_name(payload: NavRecordingSaveRequest) -> str:
    """生成一组录制文件共用的基础文件名。"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    title = sanitize_file_stem(payload.title or payload.panel_id or "recording")
    topic = sanitize_file_stem(payload.topic.replace("/", "_"))
    return f"{timestamp}_{title}_{topic}"


def build_recording_text(payload: NavRecordingSaveRequest) -> str:
    """拼接录制文本内容，并附带结构化数据块供前端还原图表。"""
    structured_payload = {
        "panel_id": payload.panel_id,
        "title": payload.title,
        "topic": payload.topic,
        "message_type": payload.message_type,
        "started_at_ms": payload.started_at_ms,
        "started_at": payload.started_at,
        "stopped_at": payload.stopped_at,
        "duration_ms": payload.duration_ms,
        "entries": payload.entries,
        "metric_series": [
            {
                "label": metric.label,
                "unit": metric.unit,
                "color": metric.color,
                "samples": [
                    {
                        "offset_ms": sample.offset_ms,
                        "value": sample.value,
                    }
                    for sample in metric.samples
                ],
            }
            for metric in payload.metric_series
        ],
    }
    lines = [
        f"标题: {payload.title}",
        f"Topic: {payload.topic}",
        f"消息类型: {payload.message_type}",
        f"开始时间戳(ms): {payload.started_at_ms}",
        f"开始时间: {payload.started_at}",
        f"结束时间: {payload.stopped_at}",
        f"录制时长(ms): {payload.duration_ms}",
        "",
        "消息记录:",
        *payload.entries,
        "",
        JSON_BEGIN_MARKER,
        json.dumps(structured_payload, ensure_ascii=False, indent=2),
        JSON_END_MARKER,
    ]
    return "\n".join(lines).strip() + "\n"


def save_nav_recording(payload: NavRecordingSaveRequest) -> NavRecordingFileListResponse:
    """保存录制文本文件。"""
    directory = ensure_recordings_dir()
    base_name = build_recording_base_name(payload)

    text_path = directory / f"{base_name}.txt"
    text_path.write_text(build_recording_text(payload), encoding="utf-8")

    return list_nav_recording_files()


def list_nav_recording_files() -> NavRecordingFileListResponse:
    """列出固定录制目录中的文本和图片文件。"""
    directory = ensure_recordings_dir()
    items: list[NavRecordingFileItem] = []
    for path in sorted(directory.iterdir(), key=lambda item: item.stat().st_mtime, reverse=True):
        if not path.is_file() or path.suffix.lower() not in ALLOWED_SUFFIXES:
            continue
        kind = "image" if path.suffix.lower() in {".svg", ".png", ".jpg", ".jpeg", ".webp"} else "text"
        items.append(
            NavRecordingFileItem(
                name=path.name,
                path=str(path),
                kind=kind,
                size_bytes=path.stat().st_size,
                modified_at=datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            )
        )
    return NavRecordingFileListResponse(directory=str(directory), items=items)


def read_nav_recording_text(path: str) -> str:
    """读取录制文本文件内容。"""
    file_path = Path(path)
    if not file_path.exists() or not file_path.is_file():
        raise RuntimeError(f"录制文件不存在: {path}")
    if file_path.suffix.lower() != ".txt":
        raise RuntimeError(f"不支持读取的文本文件类型: {path}")
    return file_path.read_text(encoding="utf-8")


def delete_nav_recording_file(path: str) -> NavRecordingFileListResponse:
    """删除录制文件。"""
    file_path = Path(path)
    if not file_path.exists() or not file_path.is_file():
        raise RuntimeError(f"录制文件不存在: {path}")
    file_path.unlink()
    return list_nav_recording_files()
