"""功能说明：读取 rosbag2 SQLite3 IMU 数据并计算 Allan 统计。"""

from __future__ import annotations

import math
import sqlite3
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import numpy as np


SUPPORTED_IMU_TYPES = {"sensor_msgs/msg/Imu", "sensor_msgs/Imu"}


@dataclass(frozen=True)
class ImuTopicInfo:
    id: int
    name: str
    type: str
    serialization_format: str
    message_count: int
    start_ns: int
    end_ns: int


class CdrReader:
    """按 ROS2 CDR 封装后的对齐规则读取 sensor_msgs/msg/Imu。"""

    def __init__(self, payload: bytes):
        if len(payload) < 4:
            raise ValueError("CDR 数据太短")
        self.payload = payload
        self.offset = 4
        self.prefix = "<" if payload[1] == 1 else ">"

    def align(self, boundary: int) -> None:
        remainder = (self.offset - 4) % boundary
        if remainder:
            self.offset += boundary - remainder

    def int32(self) -> int:
        self.align(4)
        value = struct.unpack_from(self.prefix + "i", self.payload, self.offset)[0]
        self.offset += 4
        return int(value)

    def uint32(self) -> int:
        self.align(4)
        value = struct.unpack_from(self.prefix + "I", self.payload, self.offset)[0]
        self.offset += 4
        return int(value)

    def float64(self) -> float:
        self.align(8)
        value = struct.unpack_from(self.prefix + "d", self.payload, self.offset)[0]
        self.offset += 8
        return float(value)

    def string(self) -> str:
        length = self.uint32()
        raw = self.payload[self.offset : self.offset + length]
        self.offset += length
        self.align(4)
        if raw.endswith(b"\x00"):
            raw = raw[:-1]
        return raw.decode("utf-8", errors="replace")

    def skip_float64(self, count: int) -> None:
        self.align(8)
        self.offset += 8 * count

    def vector3(self) -> Tuple[float, float, float]:
        return self.float64(), self.float64(), self.float64()


def _safe_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _db_path(path: str) -> Path:
    file_path = Path(path)
    if not file_path.exists() or not file_path.is_file():
        raise RuntimeError(f"rosbag2 db3 文件不存在: {path}")
    if file_path.suffix.lower() != ".db3":
        raise RuntimeError(f"当前只支持 rosbag2 SQLite3 .db3 文件: {path}")
    return file_path


def _connect(path: str) -> sqlite3.Connection:
    try:
        return sqlite3.connect(str(_db_path(path)))
    except sqlite3.Error as exc:
        raise RuntimeError(f"无法打开 db3 文件: {exc}") from exc


def _topic_rows(connection: sqlite3.Connection) -> List[Tuple[int, str, str, str]]:
    try:
        return [
            (int(row[0]), str(row[1]), str(row[2]), str(row[3]))
            for row in connection.execute("select id, name, type, serialization_format from topics order by id")
        ]
    except sqlite3.Error as exc:
        raise RuntimeError(f"读取 topics 表失败: {exc}") from exc


def inspect_imu_bag(path: str) -> Dict[str, Any]:
    """读取 rosbag2 元信息，返回 IMU topic 可用性。"""

    with _connect(path) as connection:
        topics: List[Dict[str, Any]] = []
        for topic_id, name, message_type, serialization_format in _topic_rows(connection):
            count, start_ns, end_ns = connection.execute(
                "select count(*), min(timestamp), max(timestamp) from messages where topic_id = ?",
                (topic_id,),
            ).fetchone()
            start_ns = int(start_ns or 0)
            end_ns = int(end_ns or 0)
            duration_s = max(0.0, (end_ns - start_ns) / 1e9)
            topics.append(
                {
                    "id": topic_id,
                    "name": name,
                    "type": message_type,
                    "serialization_format": serialization_format,
                    "message_count": int(count or 0),
                    "start_ns": start_ns,
                    "end_ns": end_ns,
                    "duration_s": duration_s,
                    "frequency_hz": float(count or 0) / duration_s if duration_s > 0 else 0.0,
                    "supported": message_type in SUPPORTED_IMU_TYPES and serialization_format.lower() == "cdr",
                }
            )
    supported = [topic for topic in topics if topic["supported"]]
    return {
        "path": path,
        "status": "success" if supported else "unsupported",
        "message": f"识别到 {len(supported)} 个可解析 IMU topic。" if supported else "未找到 sensor_msgs/msg/Imu + cdr topic。",
        "topics": topics,
    }


def _read_imu_message(payload: bytes) -> Tuple[float, Tuple[float, float, float], Tuple[float, float, float], str]:
    reader = CdrReader(payload)
    stamp_sec = reader.int32()
    stamp_nsec = reader.uint32()
    frame_id = reader.string()
    reader.skip_float64(4)
    reader.skip_float64(9)
    angular_velocity = reader.vector3()
    reader.skip_float64(9)
    linear_acceleration = reader.vector3()
    return stamp_sec + stamp_nsec / 1e9, angular_velocity, linear_acceleration, frame_id


def _resolve_topic(connection: sqlite3.Connection, topic_name: str) -> ImuTopicInfo:
    rows = _topic_rows(connection)
    selected = next((row for row in rows if row[1] == topic_name), None) if topic_name else None
    if selected is None:
        selected = next((row for row in rows if row[2] in SUPPORTED_IMU_TYPES and row[3].lower() == "cdr"), None)
    if selected is None:
        raise RuntimeError("未找到可解析的 sensor_msgs/msg/Imu topic")
    topic_id, name, message_type, serialization_format = selected
    if message_type not in SUPPORTED_IMU_TYPES:
        raise RuntimeError(f"{name} 的消息类型不是 sensor_msgs/msg/Imu: {message_type}")
    if serialization_format.lower() != "cdr":
        raise RuntimeError(f"{name} 的序列化格式不是 cdr: {serialization_format}")
    count, start_ns, end_ns = connection.execute(
        "select count(*), min(timestamp), max(timestamp) from messages where topic_id = ?",
        (topic_id,),
    ).fetchone()
    return ImuTopicInfo(topic_id, name, message_type, serialization_format, int(count or 0), int(start_ns or 0), int(end_ns or 0))


def _iter_messages(connection: sqlite3.Connection, topic_id: int, start_ns: int, end_ns: int, stride: int) -> Iterable[Tuple[int, bytes]]:
    query = "select timestamp, data from messages where topic_id = ?"
    params: List[Any] = [topic_id]
    if start_ns > 0:
        query += " and timestamp >= ?"
        params.append(start_ns)
    if end_ns > 0:
        query += " and timestamp <= ?"
        params.append(end_ns)
    query += " order by timestamp"
    for index, row in enumerate(connection.execute(query, params)):
        if stride > 1 and index % stride != 0:
            continue
        yield int(row[0]), bytes(row[1])


def _load_samples(values: Dict[str, Any]) -> Tuple[ImuTopicInfo, np.ndarray, np.ndarray, np.ndarray, str]:
    path = str(values.get("bag_path") or values.get("path") or "").strip()
    topic_name = str(values.get("topic") or "").strip()
    start_s = max(0.0, _safe_float(values.get("start_s"), 0.0))
    duration_s = max(0.0, _safe_float(values.get("duration_s"), 0.0))
    stride = max(1, _safe_int(values.get("stride"), 1))
    max_samples = max(1000, min(_safe_int(values.get("max_samples"), 500000), 2_000_000))
    with _connect(path) as connection:
        topic = _resolve_topic(connection, topic_name)
        start_ns = topic.start_ns + int(start_s * 1e9) if start_s > 0 else 0
        end_ns = start_ns + int(duration_s * 1e9) if duration_s > 0 and start_ns > 0 else 0
        timestamps: List[float] = []
        gyro: List[Tuple[float, float, float]] = []
        accel: List[Tuple[float, float, float]] = []
        frame_id = ""
        decode_errors = 0
        for timestamp_ns, payload in _iter_messages(connection, topic.id, start_ns, end_ns, stride):
            if len(timestamps) >= max_samples:
                break
            try:
                stamp_s, angular_velocity, linear_acceleration, message_frame = _read_imu_message(payload)
            except Exception:
                decode_errors += 1
                if decode_errors > 20:
                    raise RuntimeError("IMU CDR 解码连续失败，请确认 topic 类型和 rosbag2 格式。")
                continue
            timestamps.append(stamp_s if stamp_s > 0 else timestamp_ns / 1e9)
            gyro.append(angular_velocity)
            accel.append(linear_acceleration)
            frame_id = frame_id or message_frame
    if len(timestamps) < 100:
        raise RuntimeError(f"可用 IMU 样本太少: {len(timestamps)}，无法进行 Allan 分析。")
    return topic, np.asarray(timestamps), np.asarray(gyro), np.asarray(accel), frame_id


def _cluster_sizes(sample_count: int, sample_dt: float, min_tau_s: float, max_tau_s: float, points_per_axis: int) -> List[int]:
    min_m = max(1, int(round(min_tau_s / sample_dt)))
    max_m = max(min_m, min(sample_count // 3, int(round(max_tau_s / sample_dt))))
    if max_m <= min_m:
        return [min_m]
    raw = np.logspace(math.log10(min_m), math.log10(max_m), max(8, points_per_axis))
    return sorted({int(max(1, round(item))) for item in raw if int(round(item)) < sample_count // 2})


def _allan_axis(data: np.ndarray, sample_dt: float, cluster_sizes: List[int]) -> List[Dict[str, float]]:
    points: List[Dict[str, float]] = []
    for cluster_size in cluster_sizes:
        cluster_count = data.size // cluster_size
        if cluster_count < 3:
            continue
        means = data[: cluster_count * cluster_size].reshape(cluster_count, cluster_size).mean(axis=1)
        diffs = np.diff(means)
        adev = math.sqrt(0.5 * float(np.mean(diffs * diffs)))
        points.append({"tau": cluster_size * sample_dt, "adev": adev})
    return points


def _estimate_axis(points: List[Dict[str, float]]) -> Dict[str, float]:
    if not points:
        return {"noise_density": 0.0, "bias_instability": 0.0, "random_walk": 0.0}
    head = points[: max(1, min(4, len(points) // 4 or 1))]
    tail = points[-max(1, min(4, len(points) // 4 or 1)) :]
    return {
        "noise_density": float(np.median([item["adev"] * math.sqrt(item["tau"]) for item in head])),
        "bias_instability": min(item["adev"] for item in points) / 0.664,
        "random_walk": float(np.median([item["adev"] / math.sqrt(item["tau"]) for item in tail])),
    }


def _allan_group(data: np.ndarray, sample_dt: float, cluster_sizes: List[int]) -> Dict[str, Any]:
    result = {"series": {}, "estimates": {}, "stats": {}}
    for index, axis in enumerate(["x", "y", "z"]):
        axis_data = data[:, index]
        points = _allan_axis(axis_data, sample_dt, cluster_sizes)
        result["series"][axis] = points
        result["estimates"][axis] = _estimate_axis(points)
        result["stats"][axis] = {
            "mean": float(np.mean(axis_data)),
            "std": float(np.std(axis_data)),
            "min": float(np.min(axis_data)),
            "max": float(np.max(axis_data)),
        }
    return result


def _downsample_preview(timestamps: np.ndarray, gyro: np.ndarray, accel: np.ndarray, max_points: int = 1200) -> List[List[float]]:
    step = max(1, int(math.ceil(timestamps.size / max_points)))
    preview = np.column_stack([timestamps - timestamps[0], gyro, accel])[::step]
    return [[float(value) for value in row] for row in preview]


def analyze_imu_bag(values: Dict[str, Any]) -> Dict[str, Any]:
    """执行 Allan 分析，返回图表、统计和导出预览所需数据。"""

    topic, timestamps, gyro, accel, frame_id = _load_samples(values)
    diffs = np.diff(timestamps)
    diffs = diffs[np.isfinite(diffs) & (diffs > 0)]
    sample_dt = float(np.median(diffs)) if diffs.size else max(1e-6, (topic.end_ns - topic.start_ns) / max(1, topic.message_count - 1) / 1e9)
    duration_used_s = float(timestamps[-1] - timestamps[0])
    min_tau_s = max(0.001, _safe_float(values.get("min_tau_s"), 0.01))
    max_tau_s = max(min_tau_s * 4, _safe_float(values.get("max_tau_s"), 1000.0))
    points_per_axis = max(12, min(_safe_int(values.get("points_per_axis"), 48), 96))
    cluster_sizes = _cluster_sizes(timestamps.size, sample_dt, min_tau_s, min(max_tau_s, max(sample_dt, duration_used_s / 3)), points_per_axis)
    sample_hz = 1.0 / sample_dt if sample_dt > 0 else 0.0
    return {
        "status": "success",
        "message": f"已解析 {timestamps.size} 帧 IMU，采样率约 {sample_hz:.2f} Hz。",
        "bag_path": str(values.get("bag_path") or values.get("path") or ""),
        "topic": {
            "id": topic.id,
            "name": topic.name,
            "type": topic.type,
            "serialization_format": topic.serialization_format,
            "message_count": topic.message_count,
            "frame_id": frame_id,
        },
        "sample": {
            "count": int(timestamps.size),
            "duration_s": duration_used_s,
            "sample_dt_s": sample_dt,
            "sample_hz": sample_hz,
            "stride": max(1, _safe_int(values.get("stride"), 1)),
            "start_offset_s": max(0.0, _safe_float(values.get("start_s"), 0.0)),
        },
        "allan": {
            "gyro": _allan_group(gyro, sample_dt, cluster_sizes),
            "accel": _allan_group(accel, sample_dt, cluster_sizes),
        },
        "preview": {
            "columns": ["t", "gx", "gy", "gz", "ax", "ay", "az"],
            "series": _downsample_preview(timestamps, gyro, accel),
        },
    }


def run_imu_calibration(values: Dict[str, Any]):
    """通用工具运行入口，供平台任务状态复用。"""

    from app.models import ToolRunResponse

    try:
        result = analyze_imu_bag(values)
    except RuntimeError as exc:
        return ToolRunResponse(tool="imu_calibration", status="error", summary=str(exc), logs=[f"[ERROR] {exc}"], data={})
    sample = result["sample"]
    return ToolRunResponse(
        tool="imu_calibration",
        status="success",
        summary=result["message"],
        logs=[
            f"[INFO] topic: {result['topic']['name']} ({result['topic']['type']})",
            f"[INFO] samples: {sample['count']} duration: {sample['duration_s']:.2f}s hz: {sample['sample_hz']:.2f}",
            "[INFO] Allan deviation 已完成。",
        ],
        data=result,
    )
