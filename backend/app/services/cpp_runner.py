from pathlib import Path
import subprocess
from datetime import datetime
import json
from typing import Dict, List, Tuple

import yaml
from fastapi import HTTPException

from app.models import ToolRunResponse
from app.services.global_relocalization import export_reviewed_database, load_candidates


ROOT_DIR = Path(__file__).resolve().parents[3]
CPP_BUILD_DIR = ROOT_DIR / "cpp" / "build"
PCD_MAP_CLI = CPP_BUILD_DIR / "pcd_map_cli.exe"
PCD_TILE_CLI = CPP_BUILD_DIR / "pcd_tile_cli.exe"
NETWORK_SCAN_CLI = CPP_BUILD_DIR / "network_scan_cli.exe"
COSTMAP_CLI = CPP_BUILD_DIR / "costmap_cli.exe"
GLOBAL_RELOCALIZATION_CLI = CPP_BUILD_DIR / "global_relocalization_cli.exe"


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


def _write_runtime_global_reloc_config(output_dir: str, config: Dict) -> str:
    if not config:
        return ""
    path = Path(output_dir) / "_runtime_global_relocalization_config.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return str(path)


def _global_reloc_option_args(values: Dict[str, str]) -> List[str]:
    option_map = {
        "target_base_positions": "--target-base-positions",
        "max_base_samples": "--max-base-samples",
        "min_candidate_distance_m": "--min-candidate-distance",
        "yaw_step_deg": "--yaw-step-deg",
    }
    args: List[str] = []
    for field_key, cli_flag in option_map.items():
        raw_value = values.get(field_key, "").strip()
        if raw_value:
            args.extend([cli_flag, raw_value])
    return args


def _run_global_reloc_command(command: List[str]) -> ToolRunResponse:
    completed, logs, _, parsed = _run_command("global_relocalization_candidates", command)
    if completed.returncode != 0:
        return ToolRunResponse(tool="global_relocalization_candidates", status="error", summary="全局重定位候选点生成失败。", logs=logs)

    summary = (
        f"C++ 候选点/描述子生成完成：候选={parsed.get('accepted_candidates', '0')} | "
        f"rejected={parsed.get('rejected_candidates', '0')} | rays={parsed.get('ray_count', '0')} | "
        f"输出={parsed.get('candidates_csv_path', 'unknown')}"
    )
    data = {
        "metadata_path": parsed.get("metadata_path", ""),
        "candidates_csv_path": parsed.get("candidates_csv_path", ""),
        "candidates_npy_path": parsed.get("candidates_npy_path", ""),
        "descriptors_npy_path": parsed.get("descriptors_npy_path", ""),
        "ring_keys_npy_path": parsed.get("ring_keys_npy_path", ""),
        "sector_keys_npy_path": parsed.get("sector_keys_npy_path", ""),
        "preview_pcd_path": parsed.get("preview_pcd_path", ""),
        "input_points": parsed.get("input_points", ""),
        "downsampled_points": parsed.get("downsampled_points", ""),
        "occupied_voxels": parsed.get("occupied_voxels", ""),
        "supported_ground_cells": parsed.get("supported_ground_cells", ""),
        "accepted_base_positions": parsed.get("accepted_base_positions", ""),
        "accepted_candidates": parsed.get("accepted_candidates", ""),
        "manual_additions": parsed.get("manual_additions", ""),
        "manual_deletions": parsed.get("manual_deletions", ""),
        "rejected_candidates": parsed.get("rejected_candidates", ""),
        "ray_count": parsed.get("ray_count", ""),
        "generated_at": datetime.utcnow().isoformat(),
    }
    return ToolRunResponse(tool="global_relocalization_candidates", status="success", summary=summary, logs=logs, data=data)


def _reviewed_candidate_count(path: Path) -> int:
    """读取 reviewed/candidates 文件的候选数量，用于避免空审核文件覆盖自动生成入口。"""
    try:
        return int(load_candidates(str(path), max_candidates=500000).get("candidate_count", 0))
    except Exception:
        return 0


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
    data = {
        "pgm_path": parsed.get("pgm_path", ""),
        "yaml_path": parsed.get("yaml_path", ""),
        "color_path": parsed.get("color_path", ""),
        "preview_path": parsed.get("preview_path", ""),
        "width": parsed.get("width", ""),
        "height": parsed.get("height", ""),
        "origin_x": parsed.get("origin_x", ""),
        "origin_y": parsed.get("origin_y", ""),
        "point_count": parsed.get("point_count", ""),
        "walkable_cells": parsed.get("walkable_cells", ""),
        "obstacle_cells": parsed.get("obstacle_cells", ""),
        "unknown_cells": parsed.get("unknown_cells", ""),
        "output_dir": output_dir,
        "base_name": base_name,
        "generated_at": datetime.utcnow().isoformat(),
    }
    return ToolRunResponse(tool="pcd_map", status="success", summary=summary, logs=logs, data=data)


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


def run_global_relocalization_candidates(values: Dict[str, str]) -> ToolRunResponse:
    if not GLOBAL_RELOCALIZATION_CLI.exists():
        raise HTTPException(status_code=500, detail=f"C++ CLI not found: {GLOBAL_RELOCALIZATION_CLI}")

    output_dir = values.get("output_dir", "").strip() or str(ROOT_DIR / "output_global_relocalization")
    config = {}
    if values.get("config_json", "").strip():
        try:
            config = json.loads(values["config_json"])
        except json.JSONDecodeError:
            config = {}
    runtime_config_path = _write_runtime_global_reloc_config(output_dir, config)
    config_path = values.get("config_path", "").strip() or runtime_config_path
    input_pcd = values.get("input_pcd", "").strip()

    final_candidates_json = values.get("final_candidates_json", "").strip()
    if final_candidates_json:
        try:
            final_candidates = json.loads(final_candidates_json)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="最终候选点 JSON 格式错误") from exc
        if not isinstance(final_candidates, list):
            raise HTTPException(status_code=400, detail="最终候选点 JSON 必须是数组")
        if not input_pcd:
            raise HTTPException(status_code=400, detail="计算 descriptors.npy/ring_keys.npy 需要输入 PCD")
        input_path = Path(input_pcd)
        if not input_path.exists():
            raise HTTPException(status_code=400, detail=f"输入 PCD 不存在: {input_pcd}")
        exported = export_reviewed_database({
            "output_dir": output_dir,
            "config": config,
            "candidates": final_candidates,
        })
        command = [
            str(GLOBAL_RELOCALIZATION_CLI),
            "--map",
            str(input_path),
            "--output",
            output_dir,
            "--candidates",
            exported["reviewed_csv_path"],
        ]
        if config_path:
            command.extend(["--config", config_path])
        command.extend(_global_reloc_option_args(values))
        return _run_global_reloc_command(command)

    candidate_file = values.get("candidate_file", "").strip()
    candidate_path = Path(candidate_file) if candidate_file else None
    if candidate_path and candidate_path.exists() and candidate_path.name.lower() == "reviewed_candidates.csv":
        reviewed_count = _reviewed_candidate_count(candidate_path)
        if reviewed_count <= 0:
            candidate_path = None
        else:
            values["active_candidates"] = str(reviewed_count)
    if candidate_path and candidate_path.exists() and candidate_path.name.lower() == "reviewed_candidates.csv":
        if not input_pcd:
            raise HTTPException(status_code=400, detail="计算 descriptors.npy/ring_keys.npy 需要输入 PCD")
        input_path = Path(input_pcd)
        if not input_path.exists():
            raise HTTPException(status_code=400, detail=f"输入 PCD 不存在: {input_pcd}")
        command = [
            str(GLOBAL_RELOCALIZATION_CLI),
            "--map",
            str(input_path),
            "--output",
            output_dir,
            "--candidates",
            str(candidate_path),
        ]
        if config_path:
            command.extend(["--config", config_path])
        command.extend(_global_reloc_option_args(values))
        return _run_global_reloc_command(command)

    if not input_pcd:
        raise HTTPException(status_code=400, detail="缺少输入 PCD")
    input_path = Path(input_pcd)
    if not input_path.exists():
        raise HTTPException(status_code=400, detail=f"输入 PCD 不存在: {input_pcd}")

    command = [
        str(GLOBAL_RELOCALIZATION_CLI),
        "--map",
        str(input_path),
        "--output",
        output_dir,
    ]

    if config_path:
        command.extend(["--config", config_path])
    manual_file = values.get("manual_file", "").strip()
    if manual_file:
        command.extend(["--manual", manual_file])

    command.extend(_global_reloc_option_args(values))
    return _run_global_reloc_command(command)


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
