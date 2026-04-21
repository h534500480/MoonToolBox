from pathlib import Path
import subprocess
from typing import Dict, List

from fastapi import HTTPException

from app.models import ToolRunResponse


ROOT_DIR = Path(__file__).resolve().parents[3]
CPP_BUILD_DIR = ROOT_DIR / "cpp" / "build"
PCD_MAP_CLI = CPP_BUILD_DIR / "pcd_map_cli.exe"


def _parse_key_value_output(lines: List[str]) -> Dict[str, str]:
    parsed: Dict[str, str] = {}
    for line in lines:
        if ": " not in line:
            continue
        key, value = line.split(": ", 1)
        parsed[key.strip()] = value.strip()
    return parsed


def run_pcd_map(values: Dict[str, str]) -> ToolRunResponse:
    if not PCD_MAP_CLI.exists():
        raise HTTPException(status_code=500, detail=f"C++ CLI not found: {PCD_MAP_CLI}")

    input_pcd = values.get("input_pcd", "").strip()
    if not input_pcd:
        raise HTTPException(status_code=400, detail="Input PCD is required")

    input_path = Path(input_pcd)
    if not input_path.exists():
        raise HTTPException(status_code=400, detail=f"Input PCD not found: {input_pcd}")

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
        f"[INFO] running: {' '.join(command)}",
        *[f"[STDOUT] {line}" for line in stdout_lines],
        *[f"[STDERR] {line}" for line in stderr_lines],
    ]

    if completed.returncode != 0:
        summary = "pcd_map_cli execution failed."
        return ToolRunResponse(tool="pcd_map", status="error", summary=summary, logs=logs)

    summary = (
        f"Map generated: {parsed.get('pgm_path', 'unknown')} | "
        f"walkable={parsed.get('walkable_cells', 'n/a')} | "
        f"obstacle={parsed.get('obstacle_cells', 'n/a')}"
    )
    return ToolRunResponse(tool="pcd_map", status="success", summary=summary, logs=logs)
