import math
from pathlib import Path
import struct
from typing import Dict, Tuple

from app.models import TilePreviewResponse


def parse_pcd_header(file_obj) -> Tuple[Dict[str, object], int]:
    header: Dict[str, object] = {}
    lines = []
    while True:
        line = file_obj.readline()
        if not line:
            raise RuntimeError("PCD header ended unexpectedly")
        text = line.decode("utf-8", errors="ignore").strip()
        if text:
            lines.append(text)
        if text.startswith("DATA "):
            data_offset = file_obj.tell()
            break

    def get_list(key: str):
        for item in lines:
            if item.startswith(key + " "):
                return item.split()[1:]
        return []

    def get_value(key: str, default=None):
        for item in lines:
            if item.startswith(key + " "):
                return item.split()[1:]
        return default

    header["FIELDS"] = get_list("FIELDS") or get_list("FIELD")
    header["SIZE"] = list(map(int, get_list("SIZE")))
    header["TYPE"] = get_list("TYPE")
    header["COUNT"] = list(map(int, get_list("COUNT"))) if get_list("COUNT") else [1] * len(header["FIELDS"])
    header["POINTS"] = int(get_value("POINTS")[0]) if get_value("POINTS") else 0
    header["DATA"] = get_value("DATA")[0].lower()
    return header, data_offset


def build_struct_fmt(header: Dict[str, object]):
    fields = header["FIELDS"]
    sizes = header["SIZE"]
    types = header["TYPE"]
    counts = header["COUNT"]

    def type_to_struct(type_code: str, size: int) -> str:
        if type_code == "F":
            return {4: "f", 8: "d"}[size]
        if type_code == "I":
            return {1: "b", 2: "h", 4: "i", 8: "q"}[size]
        if type_code == "U":
            return {1: "B", 2: "H", 4: "I", 8: "Q"}[size]
        raise RuntimeError(f"Unsupported TYPE/SIZE: {type_code}/{size}")

    fmt = "<"
    for _name, size, type_code, count in zip(fields, sizes, types, counts):
        fmt += type_to_struct(type_code, size) * count
    return fmt


def preview_pcd_tile(path: str, tile_size: float) -> TilePreviewResponse:
    pcd_path = Path(path)
    if not pcd_path.exists():
        raise RuntimeError(f"输入 PCD 不存在: {path}")

    with open(pcd_path, "rb") as file_obj:
        header, data_offset = parse_pcd_header(file_obj)
        fields = header["FIELDS"]
        field_index = {name: i for i, name in enumerate(fields)}
        if "x" not in field_index or "y" not in field_index or "z" not in field_index:
            raise RuntimeError("PCD 缺少 x/y/z 字段")

        points = int(header["POINTS"])
        data_type = str(header["DATA"])
        xmin = ymin = zmin = math.inf
        xmax = ymax = zmax = -math.inf
        tile_keys = set()
        point_count = 0

        file_obj.seek(data_offset)
        if data_type == "ascii":
            for raw_line in file_obj:
                text = raw_line.decode("utf-8", errors="ignore").strip()
                if not text:
                    continue
                values = text.split()
                x = float(values[field_index["x"]])
                y = float(values[field_index["y"]])
                z = float(values[field_index["z"]])
                xmin = min(xmin, x)
                xmax = max(xmax, x)
                ymin = min(ymin, y)
                ymax = max(ymax, y)
                zmin = min(zmin, z)
                zmax = max(zmax, z)
                tile_keys.add((math.floor(x / tile_size), math.floor(y / tile_size)))
                point_count += 1
        elif data_type == "binary":
            fmt = build_struct_fmt(header)
            rec_size = struct.calcsize(fmt)
            unpacker = struct.Struct(fmt).unpack_from
            blob = file_obj.read(points * rec_size)
            actual_points = len(blob) // rec_size
            for index in range(actual_points):
                row = unpacker(blob, index * rec_size)
                x = float(row[field_index["x"]])
                y = float(row[field_index["y"]])
                z = float(row[field_index["z"]])
                xmin = min(xmin, x)
                xmax = max(xmax, x)
                ymin = min(ymin, y)
                ymax = max(ymax, y)
                zmin = min(zmin, z)
                zmax = max(zmax, z)
                tile_keys.add((math.floor(x / tile_size), math.floor(y / tile_size)))
                point_count += 1
        else:
            raise RuntimeError(f"暂不支持的 PCD DATA 类型: {data_type}")

    if point_count == 0:
        raise RuntimeError("没有读取到点云数据")

    return TilePreviewResponse(
        point_count=point_count,
        xmin=xmin,
        xmax=xmax,
        ymin=ymin,
        ymax=ymax,
        zmin=zmin,
        zmax=zmax,
        estimated_tiles=len(tile_keys),
    )
