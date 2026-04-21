from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import yaml

from app.models import ToolRunResponse

try:
    from PIL import Image, ImageDraw
except ImportError:  # pragma: no cover - handled at runtime for optional export.
    Image = None
    ImageDraw = None


def _parse_one_doc(doc: dict, index: int) -> Optional[Dict[str, object]]:
    if not isinstance(doc, dict):
        return None
    if "info" not in doc or "data" not in doc:
        return None

    info = doc["info"]
    header = doc.get("header", {})
    stamp = header.get("stamp", {})
    origin = info.get("origin", {}).get("position", {})

    width = int(info["width"])
    height = int(info["height"])
    resolution = float(info["resolution"])
    data = list(doc["data"])
    expected = width * height
    if len(data) != expected:
        raise ValueError(f"第 {index + 1} 帧尺寸不对: data={len(data)}, width*height={expected}")

    return {
        "index": index,
        "stamp_sec": int(stamp.get("sec", 0)),
        "stamp_nanosec": int(stamp.get("nanosec", 0)),
        "frame_id": str(header.get("frame_id", "")),
        "width": width,
        "height": height,
        "resolution": resolution,
        "origin_x": float(origin.get("x", 0.0)),
        "origin_y": float(origin.get("y", 0.0)),
        "grid": data,
    }


def _downsample_frame(frame: Dict[str, object], max_side: int = 180) -> Dict[str, object]:
    width = int(frame["width"])
    height = int(frame["height"])
    grid = frame["grid"]
    scale = max(1, max(width, height) // max_side + (1 if max(width, height) % max_side else 0))
    preview_width = max(1, width // scale)
    preview_height = max(1, height // scale)

    pixels: List[int] = []
    nonzero = 0
    lethal = 0
    for py in range(preview_height):
        src_y = min(height - 1, py * scale)
        row_offset = src_y * width
        for px in range(preview_width):
            src_x = min(width - 1, px * scale)
            value = int(grid[row_offset + src_x])
            pixels.append(value)
            if value > 0:
                nonzero += 1
            if value >= 99:
                lethal += 1

    return {
        "index": frame["index"],
        "stamp_sec": frame["stamp_sec"],
        "stamp_nanosec": frame["stamp_nanosec"],
        "frame_id": frame["frame_id"],
        "width": width,
        "height": height,
        "resolution": frame["resolution"],
        "origin_x": frame["origin_x"],
        "origin_y": frame["origin_y"],
        "preview_width": preview_width,
        "preview_height": preview_height,
        "preview_pixels": pixels,
        "nonzero": nonzero,
        "lethal": lethal,
    }


def _write_summary(path: Path, frames: List[Dict[str, object]]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as file_obj:
        file_obj.write(f"frame_count: {len(frames)}\n")
        if frames:
            first = frames[0]
            file_obj.write(f"width: {first['width']}\n")
            file_obj.write(f"height: {first['height']}\n")
            file_obj.write(f"resolution: {first['resolution']}\n")
            file_obj.write(f"origin_x: {first['origin_x']}\n")
            file_obj.write(f"origin_y: {first['origin_y']}\n")
    return str(path)


def _bool_value(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on", "是"}


def _safe_float(value: object, default: float) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def _cost_color(value: int) -> Tuple[int, int, int]:
    if value < 0:
        return (92, 98, 112)
    if value == 0:
        return (13, 19, 29)
    value = max(0, min(100, value))
    if value >= 99:
        return (255, 80, 48)
    ratio = value / 100.0
    red = int(55 + ratio * 200)
    green = int(132 + ratio * 78)
    blue = int(255 - ratio * 220)
    return (red, green, max(30, blue))


def _frame_to_image(frame: Dict[str, object], cell_size: int = 3):
    if Image is None:
        raise RuntimeError("导出 PNG/GIF 需要安装 pillow")

    width = int(frame["width"])
    height = int(frame["height"])
    grid: Sequence[int] = frame["grid"]  # type: ignore[assignment]
    scale = max(1, min(8, cell_size))
    image = Image.new("RGB", (width, height))
    pixels = image.load()
    for y in range(height):
        row_offset = y * width
        out_y = height - 1 - y
        for x in range(width):
            pixels[x, out_y] = _cost_color(int(grid[row_offset + x]))
    if scale != 1:
        image = image.resize((width * scale, height * scale), Image.Resampling.NEAREST)
    return image


def _draw_footprint(image, frame: Dict[str, object], footprint_length: float, footprint_width: float) -> None:
    if ImageDraw is None:
        return
    resolution = float(frame["resolution"])
    if resolution <= 0:
        return
    scale_x = image.width / int(frame["width"])
    scale_y = image.height / int(frame["height"])
    center_x = image.width / 2.0
    center_y = image.height / 2.0
    half_w = max(1.0, footprint_length / resolution * scale_x / 2.0)
    half_h = max(1.0, footprint_width / resolution * scale_y / 2.0)
    draw = ImageDraw.Draw(image)
    draw.rectangle(
        (center_x - half_w, center_y - half_h, center_x + half_w, center_y + half_h),
        outline=(0, 240, 255),
        width=max(1, int(min(scale_x, scale_y))),
    )
    draw.line((center_x - 6, center_y, center_x + 6, center_y), fill=(0, 240, 255), width=1)
    draw.line((center_x, center_y - 6, center_x, center_y + 6), fill=(0, 240, 255), width=1)


def _export_images(
    output_dir: Path,
    frames: List[Dict[str, object]],
    export_png: bool,
    export_gif: bool,
    fps: float,
    footprint_length: float,
    footprint_width: float,
    show_footprint: bool,
) -> List[str]:
    paths: List[str] = []
    if not export_png and not export_gif:
        return paths
    if Image is None:
        raise RuntimeError("导出 PNG/GIF 需要安装 pillow，请执行 pip install pillow")

    output_dir.mkdir(parents=True, exist_ok=True)
    rendered = []
    if export_gif:
        rendered = [_frame_to_image(frame, cell_size=3) for frame in frames]
        if show_footprint:
            for image, frame in zip(rendered, frames):
                _draw_footprint(image, frame, footprint_length, footprint_width)

    if export_png:
        png_dir = output_dir / "png_frames"
        png_dir.mkdir(parents=True, exist_ok=True)
        for index, frame in enumerate(frames):
            image = rendered[index].copy() if rendered else _frame_to_image(frame, cell_size=3)
            if show_footprint and not rendered:
                _draw_footprint(image, frame, footprint_length, footprint_width)
            png_path = png_dir / f"costmap_frame_{index + 1:04d}.png"
            image.save(png_path)
        paths.append(str(png_dir))

    if export_gif:
        gif_path = output_dir / "costmap_playback.gif"
        duration = int(1000.0 / max(0.1, fps))
        rendered[0].save(gif_path, save_all=True, append_images=rendered[1:], duration=duration, loop=0)
        paths.append(str(gif_path))
    return paths


def run_costmap(values: Dict[str, str]) -> ToolRunResponse:
    yaml_path = values.get("yaml_path", "").strip()
    if not yaml_path:
        raise ValueError("缺少输入 YAML")

    input_path = Path(yaml_path)
    if not input_path.exists():
        raise ValueError(f"输入 YAML 不存在: {yaml_path}")

    output_dir = Path(values.get("output_dir", "").strip() or (input_path.parent / (input_path.stem + "_costmap")))
    fps = max(0.1, _safe_float(values.get("fps"), 2.0))
    threshold = _safe_float(values.get("threshold"), 99.0)
    export_gif = _bool_value(values.get("export_gif"), False)
    export_png = _bool_value(values.get("export_png"), False)
    show_footprint = _bool_value(values.get("show_footprint"), True)
    footprint_length = max(0.01, _safe_float(values.get("footprint_length"), 0.70))
    footprint_width = max(0.01, _safe_float(values.get("footprint_width"), 0.40))

    with open(input_path, "r", encoding="utf-8") as file_obj:
        docs = list(yaml.safe_load_all(file_obj))

    frames: List[Dict[str, object]] = []
    for index, doc in enumerate(docs):
        frame = _parse_one_doc(doc, index)
        if frame is not None:
            frames.append(frame)

    if not frames:
        return ToolRunResponse(
            tool="costmap",
            status="error",
            summary="没有解析到任何有效帧。",
            logs=[f"[ERROR] 文件中没有可用的 costmap 帧: {input_path}"],
            data={},
        )

    preview_frames = [_downsample_frame(frame) for frame in frames]
    summary_path = _write_summary(output_dir / "costmap_summary.txt", frames)
    export_paths = _export_images(
        output_dir=output_dir,
        frames=frames,
        export_png=export_png,
        export_gif=export_gif,
        fps=fps,
        footprint_length=footprint_length,
        footprint_width=footprint_width,
        show_footprint=show_footprint,
    )

    logs = [
        f"[INFO] 已加载文件: {input_path}",
        f"[INFO] 帧数量: {len(frames)}",
        f"[INFO] FPS: {fps}",
        f"[INFO] Lethal 阈值: {threshold}",
        f"[INFO] 摘要文件: {summary_path}",
    ]
    logs.extend([f"[INFO] 导出文件: {path}" for path in export_paths])

    first = frames[0]
    first_grid: Sequence[int] = first["grid"]  # type: ignore[assignment]
    first_lethal = sum(1 for value in first_grid if int(value) >= threshold)
    first_nonzero = sum(1 for value in first_grid if int(value) > 0)
    summary = f"已加载 {len(frames)} 帧，可直接播放。"
    data = {
        "frame_count": len(frames),
        "summary_path": summary_path,
        "export_paths": export_paths,
        "fps": fps,
        "threshold": threshold,
        "footprint_length": footprint_length,
        "footprint_width": footprint_width,
        "frames": preview_frames,
        "first_frame": {
            "width": first["width"],
            "height": first["height"],
            "resolution": first["resolution"],
            "origin_x": first["origin_x"],
            "origin_y": first["origin_y"],
            "nonzero": first_nonzero,
            "lethal": first_lethal,
        },
    }
    return ToolRunResponse(tool="costmap", status="success", summary=summary, logs=logs, data=data)
