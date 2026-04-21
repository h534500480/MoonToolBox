from pathlib import Path
import subprocess
from typing import Dict, List, Tuple

from fastapi import HTTPException

from app.models import ToolRunResponse


ROOT_DIR = Path(__file__).resolve().parents[3]
CPP_BUILD_DIR = ROOT_DIR / "cpp" / "build"
PCD_MAP_CLI = CPP_BUILD_DIR / "pcd_map_cli.exe"
PCD_TILE_CLI = CPP_BUILD_DIR / "pcd_tile_cli.exe"
NETWORK_SCAN_CLI = CPP_BUILD_DIR / "network_scan_cli.exe"
COSTMAP_CLI = CPP_BUILD_DIR / "costmap_cli.exe"


def _parse_key_value_output(lines: List[str]) -> Dict[str, str]:
    parsed: Dict[str, str] = {}
    for line in lines:
        if ": " not in line:
            continue
        key, value = line.split(": ", 1)
        parsed[key.strip()] = value.strip()
    return parsed


def _run_command(tool_key: str, command: List[str]) -> Tuple[subprocess.CompletedProcess, List[str], List[str], Dict[str, str]]:
    completed = subprocess.run(
        command,
        cwd=str(ROOT_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    stdout_lines = [line for line in completed.stdout.splitlines() if line.strip()]
    stderr_lines = [line for line in completed.stderr.splitlines() if line.strip()]
    parsed = _parse_key_value_output(stdout_lines)
    logs = [
        f"[INFO] tool={tool_key}",
        f"[INFO] command={' '.join(command)}",
        *[f"[STDOUT] {line}" for line in stdout_lines],
        *[f"[STDERR] {line}" for line in stderr_lines],
    ]
    return completed, logs, stdout_lines, parsed


def run_pcd_map(values: Dict[str, str]) -> ToolRunResponse:
    if not PCD_MAP_CLI.exists():
        raise HTTPException(status_code=500, detail=f"C++ CLI not found: {PCD_MAP_CLI}")

    input_pcd = values.get("input_pcd", "").strip()
    if not input_pcd:
        raise HTTPException(status_code=400, detail="缺少输入 PCD")

    input_path = Path(input_pcd)
    if not input_path.exists():
        raise HTTPException(status_code=400, detail=f"输入 PCD 不存在: {input_pcd}")

    output_dir = values.get("output_dir", "").strip() or str(ROOT_DIR / "output")
    base_name = values.get("base_name", "").strip() or "map"

    command = [
        str(PCD_MAP_CLI),
        "--pcd",
        str(input_path),
        "--output-dir",
        output_dir,
        "--base-name",
        base_name,
    ]

    option_map = {
        "resolution": "--resolution",
        "clip_min_z": "--clip-min-z",
        "clip_max_z": "--clip-max-z",
        "walkable_min_z": "--walkable-min-z",
        "walkable_max_z": "--walkable-max-z",
        "obstacle_min_z": "--obstacle-min-z",
        "obstacle_max_z": "--obstacle-max-z",
        "ground_tolerance": "--ground-tolerance",
        "min_points_per_cell": "--min-points-per-cell",
        "obstacle_inflate_radius": "--obstacle-inflate-radius",
        "hole_fill_neighbors": "--hole-fill-neighbors",
        "overlay_smooth_radius": "--overlay-smooth-radius",
    }

    for field_key, cli_flag in option_map.items():
        raw_value = values.get(field_key, "").strip()
        if raw_value:
            command.extend([cli_flag, raw_value])

    completed, logs, _, parsed = _run_command("pcd_map", command)
    if completed.returncode != 0:
        return ToolRunResponse(tool="pcd_map", status="error", summary="地图生成失败。", logs=logs)

    summary = (
        f"地图生成完成：{parsed.get('pgm_path', 'unknown')} | "
        f"可行走格={parsed.get('walkable_cells', 'n/a')} | "
        f"障碍格={parsed.get('obstacle_cells', 'n/a')}"
    )
    return ToolRunResponse(tool="pcd_map", status="success", summary=summary, logs=logs)


def run_pcd_tile(values: Dict[str, str]) -> ToolRunResponse:
    if not PCD_TILE_CLI.exists():
        raise HTTPException(status_code=500, detail=f"C++ CLI not found: {PCD_TILE_CLI}")

    input_pcd = values.get("input_pcd", "").strip()
    if not input_pcd:
        raise HTTPException(status_code=400, detail="缺少输入 PCD")
    input_path = Path(input_pcd)
    if not input_path.exists():
        raise HTTPException(status_code=400, detail=f"输入 PCD 不存在: {input_pcd}")

    output_dir = values.get("output_dir", "").strip() or str(ROOT_DIR / "output_tiles")
    command = [
        str(PCD_TILE_CLI),
        "--pcd",
        str(input_path),
        "--output-dir",
        output_dir,
    ]

    if values.get("tile_size", "").strip():
        command.extend(["--tile-size", values["tile_size"].strip()])
    if values.get("overlap", "").strip():
        command.extend(["--overlap", values["overlap"].strip()])
    if values.get("format", "").strip():
        command.extend(["--format", values["format"].strip()])
    if values.get("zip_output", "").strip().lower() in {"1", "true", "yes", "y"}:
        command.append("--zip-output")

    completed, logs, _, parsed = _run_command("pcd_tile", command)
    if completed.returncode != 0:
        return ToolRunResponse(tool="pcd_tile", status="error", summary="点云切片失败。", logs=logs)

    summary = (
        f"切片任务已执行：metadata={parsed.get('metadata_path', 'unknown')} | "
        f"tile_count={parsed.get('tile_count', '0')}"
    )
    return ToolRunResponse(tool="pcd_tile", status="success", summary=summary, logs=logs)


def run_network_scan(values: Dict[str, str]) -> ToolRunResponse:
    if not NETWORK_SCAN_CLI.exists():
        raise HTTPException(status_code=500, detail=f"C++ CLI not found: {NETWORK_SCAN_CLI}")

    prefix = values.get("prefix", "").strip() or "192.168.1"
    start = values.get("start", "").strip() or "1"
    end = values.get("end", "").strip() or "32"
    timeout_ms = values.get("timeout_ms", "").strip() or "400"

    command = [
        str(NETWORK_SCAN_CLI),
        "--prefix",
        prefix,
        "--start",
        start,
        "--end",
        end,
        "--timeout-ms",
        timeout_ms,
    ]

    completed, logs, stdout_lines, _ = _run_command("network_scan", command)
    if completed.returncode != 0:
        return ToolRunResponse(tool="network_scan", status="error", summary="网络扫描失败。", logs=logs)

    device_lines = [line for line in stdout_lines if " | " in line]
    summary = f"扫描完成：发现 {len(device_lines)} 条结果。"
    return ToolRunResponse(tool="network_scan", status="success", summary=summary, logs=logs)


def run_costmap(values: Dict[str, str]) -> ToolRunResponse:
    if not COSTMAP_CLI.exists():
        raise HTTPException(status_code=500, detail=f"C++ CLI not found: {COSTMAP_CLI}")

    yaml_path = values.get("yaml_path", "").strip()
    if not yaml_path:
        raise HTTPException(status_code=400, detail="缺少输入 YAML")
    input_path = Path(yaml_path)
    if not input_path.exists():
        raise HTTPException(status_code=400, detail=f"输入 YAML 不存在: {yaml_path}")

    output_dir = values.get("output_dir", "").strip() or str(ROOT_DIR / "output_costmap")
    command = [
        str(COSTMAP_CLI),
        "--yaml",
        str(input_path),
        "--output-dir",
        output_dir,
    ]

    if values.get("fps", "").strip():
        command.extend(["--fps", values["fps"].strip()])
    if values.get("export_gif", "").strip().lower() in {"0", "false", "no", "n"}:
        command.append("--no-gif")

    completed, logs, _, parsed = _run_command("costmap", command)
    if completed.returncode != 0:
        return ToolRunResponse(tool="costmap", status="error", summary="Costmap 处理失败。", logs=logs)

    summary = (
        f"处理完成：summary={parsed.get('summary_path', 'unknown')} | "
        f"frame_count={parsed.get('frame_count', '0')}"
    )
    return ToolRunResponse(tool="costmap", status="success", summary=summary, logs=logs)
