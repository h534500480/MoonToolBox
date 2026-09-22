# 功能说明：为 ROS 导航测试页加载离线 PCD 点云预览，并解析 map.yaml/PGM 坐标信息。

from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import yaml


from app.paths import DATA_ROOT, CPP_BUILD_DIR

ROOT_DIR = DATA_ROOT
NAV_PCD_PREVIEW_CLI = CPP_BUILD_DIR / "nav_pcd_preview_cli.exe"


class OfflineOccupancyCache:
    """保存离线点云的稀疏占据结构，供初始化点击射线查询使用。"""

    def __init__(self, cache_key: str, points: List[List[float]], voxel_m: float):
        self.cache_key = cache_key
        self.voxel_m = max(0.03, float(voxel_m))
        self.points = [
            (float(point[0]), float(point[1]), float(point[2]))
            for point in points
            if len(point) >= 3 and all(math.isfinite(float(value)) for value in point[:3])
        ]
        self.point_buckets: Dict[Tuple[int, int, int], List[Tuple[float, float, float]]] = {}
        for point in self.points:
            self.point_buckets.setdefault(self._voxel_key(*point), []).append(point)
        self.occupied = {
            self._voxel_key(x, y, z)
            for x, y, z in self.points
        }
        self.visible_occupied = set(self.occupied)

    def _voxel_key(self, x: float, y: float, z: float) -> Tuple[int, int, int]:
        epsilon = 1e-9
        return (
            math.floor(x / self.voxel_m + epsilon),
            math.floor(y / self.voxel_m + epsilon),
            math.floor(z / self.voxel_m + epsilon),
        )

    def _voxel_center(self, key: Tuple[int, int, int]) -> Tuple[float, float, float]:
        half = self.voxel_m * 0.5
        return (
            key[0] * self.voxel_m + half,
            key[1] * self.voxel_m + half,
            key[2] * self.voxel_m + half,
        )

    def active_occupied(self, use_visible_voxels: bool) -> Set[Tuple[int, int, int]]:
        return self.visible_occupied if use_visible_voxels and self.visible_occupied else self.occupied

    def has_occupied_near(
        self,
        x: float,
        y: float,
        z: float,
        clip_bounds: Optional[Dict[str, float]] = None,
        use_visible_voxels: bool = True,
    ) -> bool:
        active_occupied = self.active_occupied(use_visible_voxels)
        vx, vy, vz = self._voxel_key(x, y, z)
        for dz in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    key = (vx + dx, vy + dy, vz + dz)
                    if key in active_occupied and _point_in_clip_bounds(*self._voxel_center(key), clip_bounds):
                        return True
        return False

    def neighbors(self, x: float, y: float, z: float, radius_m: float, clip_bounds: Optional[Dict[str, float]] = None) -> List[Tuple[float, float, float]]:
        radius2 = radius_m * radius_m
        z_limit = max(0.12, radius_m * 0.8)
        bucket_radius = max(1, math.ceil(radius_m / self.voxel_m))
        vx, vy, vz = self._voxel_key(x, y, z)
        result = []
        for iz in range(vz - bucket_radius, vz + bucket_radius + 1):
            for iy in range(vy - bucket_radius, vy + bucket_radius + 1):
                for ix in range(vx - bucket_radius, vx + bucket_radius + 1):
                    for px, py, pz in self.point_buckets.get((ix, iy, iz), []):
                        dx = px - x
                        dy = py - y
                        dz = pz - z
                        if (
                            _point_in_clip_bounds(px, py, pz, clip_bounds)
                            and abs(dz) <= z_limit
                            and dx * dx + dy * dy + dz * dz <= radius2
                        ):
                            result.append((px, py, pz))
        return result

    def voxel_centers(self, max_voxels: int) -> List[List[float]]:
        """返回占据体素中心点，前端用这些中心点绘制轻量 InstancedMesh。"""
        safe_max_voxels = max(1000, int(max_voxels or 60000))
        keys = sorted(self.occupied)
        if len(keys) > safe_max_voxels:
            step = math.ceil(len(keys) / safe_max_voxels)
            keys = keys[::step][:safe_max_voxels]
        self.visible_occupied = set(keys)
        half = self.voxel_m * 0.5
        return [
            [
                ix * self.voxel_m + half,
                iy * self.voxel_m + half,
                iz * self.voxel_m + half,
            ]
            for ix, iy, iz in keys
        ]


_OCCUPANCY_CACHE: Optional[OfflineOccupancyCache] = None


def _point_in_clip_bounds(x: float, y: float, z: float, bounds: Optional[Dict[str, float]]) -> bool:
    if not bounds:
        return True
    return (
        bounds["xmin"] <= x <= bounds["xmax"]
        and bounds["ymin"] <= y <= bounds["ymax"]
        and bounds["zmin"] <= z <= bounds["zmax"]
    )


def _parse_clip_bounds(value: Any) -> Optional[Dict[str, float]]:
    if not isinstance(value, dict):
        return None
    try:
        bounds = {
            "xmin": float(value["xmin"]),
            "xmax": float(value["xmax"]),
            "ymin": float(value["ymin"]),
            "ymax": float(value["ymax"]),
            "zmin": float(value["zmin"]),
            "zmax": float(value["zmax"]),
        }
    except (KeyError, TypeError, ValueError):
        return None
    if not all(math.isfinite(item) for item in bounds.values()):
        return None
    if bounds["xmin"] > bounds["xmax"] or bounds["ymin"] > bounds["ymax"] or bounds["zmin"] > bounds["zmax"]:
        return None
    return bounds


def _ensure_file(path: str, label: str) -> Path:
    file_path = Path(path)
    if not file_path.exists() or not file_path.is_file():
        raise RuntimeError(f"{label}不存在: {path}")
    return file_path


def _read_pgm_size(path: Path) -> Tuple[int, int]:
    """读取 PGM 头部尺寸，避免仅为获取宽高而完整解码大地图。"""
    with path.open("rb") as file:
        magic = file.readline().strip()
        if magic not in {b"P2", b"P5"}:
            raise RuntimeError(f"暂不支持的 PGM 格式: {path}")

        tokens = []
        while len(tokens) < 3:
            line = file.readline()
            if not line:
                break
            line = line.split(b"#", 1)[0].strip()
            if not line:
                continue
            tokens.extend(line.split())

    if len(tokens) < 3:
        raise RuntimeError(f"PGM 头部缺少宽高信息: {path}")
    return int(tokens[0]), int(tokens[1])


def _resolve_map_image_path(yaml_path: Path, image_value: str) -> Path:
    image_path = Path(image_value)
    if not image_path.is_absolute():
        image_path = yaml_path.parent / image_path
    return image_path.resolve()


def _parse_map_yaml(path: str, pgm_path: str = "") -> Dict[str, Any]:
    yaml_path = _ensure_file(path, "map.yaml ")
    try:
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    except UnicodeDecodeError:
        data = yaml.safe_load(yaml_path.read_text(encoding="gbk", errors="ignore")) or {}

    image_value = str(data.get("image") or "").strip()
    if not image_value:
        raise RuntimeError(f"map.yaml 缺少 image 字段: {path}")

    image_path = Path(pgm_path).resolve() if pgm_path.strip() else _resolve_map_image_path(yaml_path, image_value)
    _ensure_file(str(image_path), "map.pgm ")
    width, height = _read_pgm_size(image_path)

    resolution = float(data.get("resolution") or 0.0)
    if not math.isfinite(resolution) or resolution <= 0:
        raise RuntimeError(f"map.yaml resolution 无效: {path}")

    origin = data.get("origin") or [0.0, 0.0, 0.0]
    if not isinstance(origin, list) or len(origin) < 2:
        raise RuntimeError(f"map.yaml origin 无效: {path}")
    origin_x = float(origin[0])
    origin_y = float(origin[1])
    origin_yaw = float(origin[2]) if len(origin) >= 3 else 0.0

    width_m = width * resolution
    height_m = height * resolution
    return {
        "yaml_path": str(yaml_path),
        "image_path": str(image_path),
        "resolution": resolution,
        "origin": [origin_x, origin_y, origin_yaw],
        "width": width,
        "height": height,
        "bounds": {
            "xmin": origin_x,
            "xmax": origin_x + width_m,
            "ymin": origin_y,
            "ymax": origin_y + height_m,
            "zmin": 0.0,
            "zmax": 0.0,
        },
        "occupied_thresh": data.get("occupied_thresh"),
        "free_thresh": data.get("free_thresh"),
        "negate": data.get("negate"),
    }


def _run_nav_pcd_preview(path: str, voxel_leaf_m: float, max_points: int) -> Dict[str, Any]:
    if not NAV_PCD_PREVIEW_CLI.exists():
        raise RuntimeError(f"C++ CLI 不存在: {NAV_PCD_PREVIEW_CLI}")

    command = [
        str(NAV_PCD_PREVIEW_CLI),
        "--pcd",
        path,
        "--voxel-leaf",
        f"{voxel_leaf_m:.6f}",
        "--max-points",
        str(max_points),
    ]
    completed = subprocess.run(
        command,
        cwd=str(ROOT_DIR),
        capture_output=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "nav_pcd_preview_cli 执行失败"
        raise RuntimeError(detail)
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("nav_pcd_preview_cli 输出不是有效 JSON") from exc


def _cache_key(pcd_path: str, voxel_leaf_m: float, max_points: int) -> str:
    return f"{Path(pcd_path).resolve()}|{voxel_leaf_m:.4f}|{max_points}"


def _build_occupancy_cache(
    pcd_path: str,
    pcd_preview: Dict[str, Any],
    voxel_leaf_m: float,
    max_points: int,
    occupancy_voxel_m: float,
) -> None:
    global _OCCUPANCY_CACHE
    points = pcd_preview.get("points") or []
    safe_occupancy_voxel_m = max(0.05, min(2.0, float(occupancy_voxel_m or 0.30)))
    _OCCUPANCY_CACHE = OfflineOccupancyCache(
        cache_key=_cache_key(pcd_path, voxel_leaf_m, max_points),
        points=points,
        voxel_m=safe_occupancy_voxel_m,
    )


def _occupancy_preview_payload(max_voxels: int) -> Dict[str, Any]:
    cache = _OCCUPANCY_CACHE
    if cache is None:
        return {
            "voxel_m": 0.0,
            "occupied_count": 0,
            "displayed_count": 0,
            "truncated": False,
            "voxels": [],
        }
    voxels = cache.voxel_centers(max_voxels)
    return {
        "voxel_m": cache.voxel_m,
        "occupied_count": len(cache.occupied),
        "displayed_count": len(voxels),
        "truncated": len(voxels) < len(cache.occupied),
        "voxels": voxels,
    }


def _normalize_vector(values: Iterable[float]) -> Tuple[float, float, float]:
    vector = tuple(float(value) for value in values)
    if len(vector) != 3:
        raise RuntimeError("射线向量必须包含 3 个数值")
    norm = math.sqrt(sum(value * value for value in vector))
    if not math.isfinite(norm) or norm <= 1e-9:
        raise RuntimeError("射线方向无效")
    return vector[0] / norm, vector[1] / norm, vector[2] / norm


def _parse_point3(values: Iterable[float], label: str) -> Tuple[float, float, float]:
    point = tuple(float(value) for value in values)
    if len(point) != 3 or not all(math.isfinite(value) for value in point):
        raise RuntimeError(f"{label} 必须包含 3 个有效数值")
    return point[0], point[1], point[2]


def _estimate_surface_normal(points: List[Tuple[float, float, float]]) -> Optional[Tuple[float, float, float]]:
    """用最小二乘拟合 z=ax+by+c，并转换为朝上的地面法线。"""
    if len(points) < 6:
        return None
    n = float(len(points))
    sx = sum(point[0] for point in points)
    sy = sum(point[1] for point in points)
    sz = sum(point[2] for point in points)
    sxx = sum(point[0] * point[0] for point in points)
    syy = sum(point[1] * point[1] for point in points)
    sxy = sum(point[0] * point[1] for point in points)
    sxz = sum(point[0] * point[2] for point in points)
    syz = sum(point[1] * point[2] for point in points)

    matrix = [
        [sxx, sxy, sx],
        [sxy, syy, sy],
        [sx, sy, n],
    ]
    rhs = [sxz, syz, sz]

    for pivot_index in range(3):
        pivot_row = max(range(pivot_index, 3), key=lambda row: abs(matrix[row][pivot_index]))
        if abs(matrix[pivot_row][pivot_index]) < 1e-9:
            return None
        if pivot_row != pivot_index:
            matrix[pivot_index], matrix[pivot_row] = matrix[pivot_row], matrix[pivot_index]
            rhs[pivot_index], rhs[pivot_row] = rhs[pivot_row], rhs[pivot_index]
        pivot = matrix[pivot_index][pivot_index]
        for column in range(pivot_index, 3):
            matrix[pivot_index][column] /= pivot
        rhs[pivot_index] /= pivot
        for row in range(3):
            if row == pivot_index:
                continue
            factor = matrix[row][pivot_index]
            for column in range(pivot_index, 3):
                matrix[row][column] -= factor * matrix[pivot_index][column]
            rhs[row] -= factor * rhs[pivot_index]

    a, b, _ = rhs
    normal = (-a, -b, 1.0)
    length = math.sqrt(normal[0] * normal[0] + normal[1] * normal[1] + normal[2] * normal[2])
    if length <= 1e-9:
        return None
    return normal[0] / length, normal[1] / length, normal[2] / length


def raycast_nav_offline_map(
    origin: List[float],
    direction: List[float],
    max_distance_m: float = 80.0,
    normal_radius_m: float = 0.8,
    ground_max_slope_deg: float = 30.0,
    clip_bounds: Optional[Dict[str, float]] = None,
    use_visible_voxels: bool = True,
) -> Dict[str, Any]:
    """在缓存的过滤点云占据结构中射线查询可用地面命中点。"""
    cache = _OCCUPANCY_CACHE
    if cache is None or not cache.occupied:
        raise RuntimeError("请先加载离线地图点云，再进行初始化地面吸附。")

    ox, oy, oz = _parse_point3(origin, "射线起点")
    dx, dy, dz = _normalize_vector(direction)
    safe_max_distance = max(1.0, min(float(max_distance_m or 80.0), 200.0))
    requested_normal_radius = max(0.15, min(float(normal_radius_m or 0.8), 3.0))
    safe_normal_radius = min(3.0, max(requested_normal_radius, cache.voxel_m * 2.2))
    max_slope = max(1.0, min(float(ground_max_slope_deg or 30.0), 75.0))
    safe_clip_bounds = _parse_clip_bounds(clip_bounds)
    min_normal_z = math.cos(math.radians(max_slope))
    step = max(cache.voxel_m * 0.5, 0.03)
    previous_key = None
    checked_candidates = 0
    z_only_candidate: Optional[Dict[str, Any]] = None

    distance = 0.0
    while distance <= safe_max_distance:
        x = ox + dx * distance
        y = oy + dy * distance
        z = oz + dz * distance
        key = cache._voxel_key(x, y, z)
        if (
            key != previous_key
            and _point_in_clip_bounds(x, y, z, safe_clip_bounds)
            and cache.has_occupied_near(x, y, z, safe_clip_bounds, use_visible_voxels)
        ):
            previous_key = key
            checked_candidates += 1
            neighbors = cache.neighbors(x, y, z, safe_normal_radius, safe_clip_bounds)
            normal = _estimate_surface_normal(neighbors)
            if neighbors and z_only_candidate is None:
                z_only_candidate = {
                    "hit": True,
                    "x": x,
                    "y": y,
                    "z": sum(point[2] for point in neighbors) / len(neighbors),
                    "normal": [0.0, 0.0, 1.0],
                    "neighbor_count": len(neighbors),
                    "distance_m": distance,
                    "confidence": min(0.45, len(neighbors) / 48.0),
                    "message": "射线命中占据 voxel，但邻域点不足或法线不稳定，已只吸附高度并将 roll/pitch 回退为 0。",
                }
            if normal and normal[2] >= min_normal_z:
                ground_z = sum(point[2] for point in neighbors) / len(neighbors) if neighbors else z
                return {
                    "hit": True,
                    "x": x,
                    "y": y,
                    "z": ground_z,
                    "normal": list(normal),
                    "neighbor_count": len(neighbors),
                    "distance_m": distance,
                    "confidence": min(1.0, len(neighbors) / 24.0),
                    "message": "已通过离线点云占据射线命中可靠地面。",
                }
            if checked_candidates >= 8:
                break
        distance += step

    if z_only_candidate is not None:
        return z_only_candidate

    return {
        "hit": False,
        "message": "射线未命中可靠地面，已回退到平面初始化。",
    }


def preview_nav_offline_map(
    pcd_path: str,
    map_yaml_path: str = "",
    map_pgm_path: str = "",
    voxel_leaf_m: float = 0.20,
    occupancy_voxel_m: float = 0.30,
    max_points: int = 60000,
    max_voxels: int = 60000,
) -> Dict[str, Any]:
    """生成导航测试页离线地图预览数据，供前端以 map 坐标系渲染。"""
    pcd_file = _ensure_file(pcd_path, "离线 PCD ")
    safe_voxel_leaf = min(5.0, max(0.01, float(voxel_leaf_m or 0.20)))
    safe_occupancy_voxel = min(2.0, max(0.05, float(occupancy_voxel_m or 0.30)))
    safe_max_points = min(300000, max(1000, int(max_points or 60000)))
    safe_max_voxels = min(200000, max(1000, int(max_voxels or 60000)))

    pcd_preview = _run_nav_pcd_preview(str(pcd_file), safe_voxel_leaf, safe_max_points)
    _build_occupancy_cache(str(pcd_file), pcd_preview, safe_voxel_leaf, safe_max_points, safe_occupancy_voxel)
    map_info = _parse_map_yaml(map_yaml_path, map_pgm_path) if map_yaml_path.strip() else None
    return {
        "pcd": pcd_preview,
        "occupancy": _occupancy_preview_payload(safe_max_voxels),
        "map": map_info,
    }
