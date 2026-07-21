"""全局重定位候选点审核服务，负责轻量读取点云、候选点和导出人工编辑文件。"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import yaml


CANDIDATE_COLUMNS = [
    "place_id",
    "x",
    "y",
    "z",
    "roll_deg",
    "pitch_deg",
    "canonical_yaw_deg",
    "qx",
    "qy",
    "qz",
    "qw",
    "observability_score",
    "hit_count",
    "hit_ratio",
    "visible_sector_count",
    "descriptor_nonzero_ratio",
]


def _require_numpy():
    """延迟加载 numpy，避免缺少可选依赖时阻断整个后端启动。"""
    try:
        import numpy as np  # type: ignore
    except ModuleNotFoundError as exc:
        raise RuntimeError("缺少 numpy，请在项目虚拟环境中执行: python -m pip install -r backend/requirements.txt") from exc
    return np


def _ensure_file(path: str) -> Path:
    file_path = Path(path)
    if not file_path.exists() or not file_path.is_file():
        raise RuntimeError(f"文件不存在: {path}")
    return file_path


def _parse_pcd_header(raw: bytes) -> Tuple[Dict[str, Any], int]:
    lines: List[str] = []
    offset = 0
    for raw_line in raw.splitlines(keepends=True):
        line = raw_line.decode("utf-8", errors="ignore").strip()
        lines.append(line)
        offset += len(raw_line)
        if line.lower().startswith("data"):
            break

    header: Dict[str, Any] = {}
    for line in lines:
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        key = parts[0].lower()
        values = parts[1:]
        if key in {"fields", "type"}:
            header[key] = values
        elif key in {"size", "count"}:
            header[key] = [int(value) for value in values]
        elif key in {"width", "height", "points"}:
            header[key] = int(values[0]) if values else 0
        elif key == "data":
            header[key] = values[0].lower() if values else ""
    return header, offset


def _pcd_dtype(header: Dict[str, Any]) -> np.dtype:
    np = _require_numpy()
    fields = header.get("fields", [])
    sizes = header.get("size", [])
    types = header.get("type", [])
    counts = header.get("count") or [1] * len(fields)
    dtype_fields = []
    for field, size, kind, count in zip(fields, sizes, types, counts):
        if kind == "F" and size == 4:
            dtype = np.float32
        elif kind == "F" and size == 8:
            dtype = np.float64
        elif kind == "U" and size == 1:
            dtype = np.uint8
        elif kind == "U" and size == 2:
            dtype = np.uint16
        elif kind == "U" and size == 4:
            dtype = np.uint32
        elif kind == "I" and size == 1:
            dtype = np.int8
        elif kind == "I" and size == 2:
            dtype = np.int16
        elif kind == "I" and size == 4:
            dtype = np.int32
        else:
            raise RuntimeError(f"暂不支持的 PCD 字段类型: {field} {kind}{size}")
        dtype_fields.append((field, dtype, (count,)) if count > 1 else (field, dtype))
    return np.dtype(dtype_fields)


def _sample_xyz(points: np.ndarray, max_points: int) -> Tuple[np.ndarray, int]:
    np = _require_numpy()
    xyz = np.column_stack([points["x"], points["y"], points["z"]]).astype(np.float32, copy=False)
    xyz = xyz[np.isfinite(xyz).all(axis=1)]
    total = int(xyz.shape[0])
    if total > max_points:
        indices = np.linspace(0, total - 1, max_points, dtype=np.int64)
        xyz = xyz[indices]
    return xyz, total


def preview_pcd_points(path: str, max_points: int = 90000) -> Dict[str, Any]:
    """读取 PCD 的 x/y/z 字段并返回前端三维预览所需的采样点。"""
    np = _require_numpy()
    file_path = _ensure_file(path)
    max_points = max(1000, min(int(max_points), 200000))
    raw = file_path.read_bytes()
    header, data_offset = _parse_pcd_header(raw)
    fields = header.get("fields", [])
    if not {"x", "y", "z"}.issubset(set(fields)):
        raise RuntimeError("PCD 缺少 x/y/z 字段")

    data_type = header.get("data", "")
    if data_type == "ascii":
        text = raw[data_offset:].decode("utf-8", errors="ignore")
        rows = [
            [float(item) for item in line.split()]
            for line in text.splitlines()
            if line.strip()
        ]
        array = np.asarray(rows, dtype=np.float32)
        field_index = {field: index for index, field in enumerate(fields)}
        xyz = array[:, [field_index["x"], field_index["y"], field_index["z"]]]
        xyz = xyz[np.isfinite(xyz).all(axis=1)]
        total = int(xyz.shape[0])
        if total > max_points:
            xyz = xyz[np.linspace(0, total - 1, max_points, dtype=np.int64)]
    elif data_type == "binary":
        dtype = _pcd_dtype(header)
        count = int(header.get("points") or header.get("width", 0) * max(1, header.get("height", 1)))
        points = np.frombuffer(raw, dtype=dtype, count=count, offset=data_offset)
        xyz, total = _sample_xyz(points, max_points)
    else:
        raise RuntimeError(f"暂不支持的 PCD DATA 类型: {data_type}")

    bounds = {
        "xmin": float(np.min(xyz[:, 0])) if xyz.size else 0.0,
        "xmax": float(np.max(xyz[:, 0])) if xyz.size else 0.0,
        "ymin": float(np.min(xyz[:, 1])) if xyz.size else 0.0,
        "ymax": float(np.max(xyz[:, 1])) if xyz.size else 0.0,
        "zmin": float(np.min(xyz[:, 2])) if xyz.size else 0.0,
        "zmax": float(np.max(xyz[:, 2])) if xyz.size else 0.0,
    }
    return {
        "path": str(file_path),
        "point_count": total,
        "sampled_count": int(xyz.shape[0]),
        "bounds": bounds,
        "points": xyz.tolist(),
    }


def _candidate_from_values(values: Iterable[Any], index: int, source: str = "auto") -> Dict[str, Any]:
    padded = list(values)[:16]
    padded.extend([0.0] * (16 - len(padded)))
    row = {column: float(padded[column_index]) for column_index, column in enumerate(CANDIDATE_COLUMNS)}
    row["place_id"] = int(row["place_id"]) if row["place_id"] >= 0 else index
    row["candidate_id"] = row["place_id"]
    row["yaw_deg"] = row["canonical_yaw_deg"]
    row["source"] = source
    row["locked"] = False
    row["label"] = ""
    row["original_candidate_id"] = row["place_id"]
    return row


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in {None, ""}:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: Any, default: int = 0) -> int:
    try:
        if value in {None, ""}:
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _to_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value in {None, ""}:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _candidate_from_dict(row: Dict[str, Any], index: int) -> Dict[str, Any]:
    candidate = _candidate_from_values([row.get(column, 0.0) for column in CANDIDATE_COLUMNS], index)
    place_id = _to_int(row.get("place_id", row.get("candidate_id")), index)
    canonical_yaw = _to_float(row.get("canonical_yaw_deg", row.get("yaw_deg")), 0.0)
    candidate["place_id"] = place_id
    candidate["candidate_id"] = place_id
    candidate["canonical_yaw_deg"] = canonical_yaw
    candidate["yaw_deg"] = canonical_yaw
    candidate["source"] = str(row.get("source") or "auto")
    candidate["locked"] = _to_bool(row.get("locked"), False)
    candidate["label"] = str(row.get("label") or "")
    candidate["original_candidate_id"] = _to_int(row.get("original_candidate_id"), candidate["place_id"])
    candidate["z_frame"] = str(row.get("z_frame") or "base_link")
    return candidate


def _candidate_export_row(candidate: Dict[str, Any], place_id: int) -> Dict[str, Any]:
    """将前端审核态候选点转换为 v2 place-level 导出字段。"""
    row = {column: candidate.get(column, "") for column in CANDIDATE_COLUMNS}
    row["place_id"] = place_id
    row["canonical_yaw_deg"] = 0.0
    return row


def _candidate_npy_row(candidate: Dict[str, Any], place_id: int) -> List[float]:
    values = []
    for column in CANDIDATE_COLUMNS:
        if column == "place_id":
            values.append(float(place_id))
        elif column == "canonical_yaw_deg":
            values.append(0.0)
        else:
            values.append(_to_float(candidate.get(column), 0.0))
    return values


def _place_key(candidate: Dict[str, Any]) -> str:
    """按毫米级 xyz 量化归并同一可站立位置，匹配 C++ v2 place-level 输出。"""
    return ":".join(
        str(round(_to_float(candidate.get(axis), 0.0) * 1000.0))
        for axis in ("x", "y", "z")
    )


def _collapse_to_places(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    places: List[Dict[str, Any]] = []
    seen = set()
    for candidate in candidates:
        key = _place_key(candidate)
        if key in seen:
            continue
        seen.add(key)
        item = dict(candidate)
        item["place_id"] = len(places)
        item["candidate_id"] = len(places)
        item["canonical_yaw_deg"] = 0.0
        item["yaw_deg"] = 0.0
        places.append(item)
    return places


def load_candidates(path: str, max_candidates: int = 200000) -> Dict[str, Any]:
    """读取 candidates.csv 或 candidates.npy，保持 candidates.npy 的 [N,16] 兼容字段。"""
    np = _require_numpy()
    file_path = _ensure_file(path)
    max_candidates = max(1, min(int(max_candidates), 500000))
    suffix = file_path.suffix.lower()
    candidates: List[Dict[str, Any]] = []
    if suffix == ".npy":
        array = np.load(file_path)
        if array.ndim != 2 or array.shape[1] < 7:
            raise RuntimeError(f"候选点 npy 形状不符合预期: {array.shape}")
        for index, values in enumerate(array[:max_candidates]):
            candidates.append(_candidate_from_values(values, index))
    else:
        with file_path.open("r", encoding="utf-8-sig", newline="") as handle:
            sample = handle.read(4096)
            handle.seek(0)
            lower_sample = sample.lower()
            has_header = "place_id" in lower_sample or "candidate_id" in lower_sample or "observability" in lower_sample
            reader = csv.DictReader(handle) if has_header else csv.reader(handle)
            for index, row in enumerate(reader):
                if index >= max_candidates:
                    break
                if isinstance(row, dict):
                    candidates.append(_candidate_from_dict(row, index))
                else:
                    candidates.append(_candidate_from_values(row, index))

    return {
        "path": str(file_path),
        "candidate_count": len(candidates),
        "columns": CANDIDATE_COLUMNS,
        "candidates": candidates,
    }


def export_manual_candidates(payload: Dict[str, Any]) -> Dict[str, Any]:
    """按 MD 推荐格式导出 manual_candidates.yaml 和 reviewed_candidates.csv。"""
    output_dir = Path(str(payload.get("output_dir") or "")).expanduser()
    if not output_dir:
        raise RuntimeError("缺少输出目录")
    output_dir.mkdir(parents=True, exist_ok=True)

    frame_id = str(payload.get("frame_id") or "map")
    base_frame = str(payload.get("base_frame") or "base_link")
    additions = payload.get("additions") if isinstance(payload.get("additions"), list) else []
    deletions = payload.get("deletions") if isinstance(payload.get("deletions"), dict) else {}
    locked_candidate_ids = payload.get("locked_candidate_ids") if isinstance(payload.get("locked_candidate_ids"), list) else []
    manual_edit = payload.get("manual_edit") if isinstance(payload.get("manual_edit"), dict) else {}
    candidates = payload.get("candidates") if isinstance(payload.get("candidates"), list) else []

    manual_payload = {
        "version": 1,
        "frame_id": frame_id,
        "base_frame": base_frame,
        "manual_edit": {
            "enabled": True,
            "allow_force_add_low_observability": bool(manual_edit.get("allow_force_add_low_observability", False)),
            "manual_points_bypass_min_distance": bool(manual_edit.get("manual_points_bypass_min_distance", True)),
            "manual_points_bypass_random_quota": bool(manual_edit.get("manual_points_bypass_random_quota", True)),
        },
        "additions": additions,
        "deletions": deletions,
        "locked_candidate_ids": locked_candidate_ids,
    }

    manual_path = output_dir / "manual_candidates.yaml"
    manual_path.write_text(yaml.safe_dump(manual_payload, allow_unicode=True, sort_keys=False), encoding="utf-8")

    csv_path = output_dir / "reviewed_candidates.csv"
    csv_columns = CANDIDATE_COLUMNS + ["source", "label", "locked", "original_candidate_id", "z_frame"]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=csv_columns)
        writer.writeheader()
        for index, candidate in enumerate(candidates):
            if not isinstance(candidate, dict):
                continue
            row = _candidate_export_row(candidate, index)
            row.update({
                "source": candidate.get("source", "auto"),
                "label": candidate.get("label", ""),
                "locked": candidate.get("locked", False),
                "original_candidate_id": candidate.get("original_candidate_id", candidate.get("candidate_id", index)),
                "z_frame": candidate.get("z_frame", "base_link"),
            })
            writer.writerow({column: row.get(column, "") for column in csv_columns})

    return {
        "manual_path": str(manual_path),
        "reviewed_csv_path": str(csv_path),
        "manual_additions_count": len(additions),
        "manual_deletions_count": len(deletions.get("candidate_ids", [])) + len(deletions.get("regions", [])),
        "locked_count": len(locked_candidate_ids),
        "candidate_count": len(candidates),
    }


def export_reviewed_database(payload: Dict[str, Any]) -> Dict[str, Any]:
    """写出审核后的候选 CSV，真实离线数据库必须交给 C++ 重新计算 descriptor。"""
    output_dir = Path(str(payload.get("output_dir") or "")).expanduser()
    if not output_dir:
        raise RuntimeError("缺少输出目录")
    output_dir.mkdir(parents=True, exist_ok=True)

    candidates = payload.get("candidates") if isinstance(payload.get("candidates"), list) else []
    normalized: List[Dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        if isinstance(candidate, dict):
            item = _candidate_from_dict(candidate, index)
        else:
            item = _candidate_from_values([], index)
        item["candidate_id"] = index
        normalized.append(item)
    normalized = _collapse_to_places(normalized)

    reviewed_csv = output_dir / "reviewed_candidates.csv"

    csv_columns = CANDIDATE_COLUMNS + ["source", "label", "locked", "original_candidate_id", "z_frame"]
    with reviewed_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=csv_columns)
        writer.writeheader()
        for index, candidate in enumerate(normalized):
            row = _candidate_export_row(candidate, index)
            row.update({
                "source": candidate.get("source", "auto"),
                "label": candidate.get("label", ""),
                "locked": candidate.get("locked", False),
                "original_candidate_id": candidate.get("original_candidate_id", candidate.get("candidate_id", index)),
                "z_frame": candidate.get("z_frame", "base_link"),
            })
            writer.writerow({column: row.get(column, "") for column in csv_columns})

    return {
        "reviewed_csv_path": str(reviewed_csv),
        "candidate_count": len(normalized),
    }
