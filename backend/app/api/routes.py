"""功能说明：四模块 API 与公共文件、ROS 诊断入口。"""
import mimetypes
from io import BytesIO
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response

from app.catalog import get_tool_definitions, is_tool_enabled
from app.models import (
    BrowseDialogRequest,
    BrowseDialogResponse,
    DeletePathRequest,
    NavRecordingFileListResponse,
    NavRecordingSaveRequest,
    OpenPathRequest,
    RosDataSourceConfig,
    RosInspectionResponse,
    RosRuntimeParamsResponse,
    RosTopicListResponse,
    TilePreviewResponse,
    ToolRunRequest,
    ToolRunResponse,
)
from app.services.cpp_runner import run_global_relocalization_candidates, run_pcd_map, run_pcd_tile
from app.services.dialogs import browse_local_path
from app.services.global_relocalization import (
    export_manual_candidates,
    load_candidates,
    preview_pcd_points,
)
from app.services.nav_recordings import (
    delete_nav_recording_file,
    list_nav_recording_files,
    read_nav_recording_text,
    save_nav_recording,
)
from app.services.nav_offline_map import preview_nav_offline_map, raycast_nav_offline_map
from app.services.pcd_preview import preview_pcd_tile
from app.services.ros_data_source import (
    inspect_ros_data_source,
    list_ros_topics,
    load_ros_data_source_config,
    save_ros_data_source_config,
)
from app.services.ros_runtime_params import list_ros_runtime_params
from app.services.system_actions import open_path_in_system
from app.services.imu_calibration import analyze_imu_bag, inspect_imu_bag, run_imu_calibration


router = APIRouter()


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/tools")
def list_tools():
    return get_tool_definitions()


@router.get("/ros/data-source", response_model=RosDataSourceConfig)
def get_ros_data_source():
    return load_ros_data_source_config()


@router.put("/ros/data-source", response_model=RosDataSourceConfig)
def put_ros_data_source(payload: RosDataSourceConfig):
    return save_ros_data_source_config(payload)


@router.post("/ros/data-source/inspect", response_model=RosInspectionResponse)
def post_ros_data_source_inspect(payload: RosDataSourceConfig):
    try:
        return inspect_ros_data_source(payload)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/ros/topics", response_model=RosTopicListResponse)
def post_ros_topics(payload: RosDataSourceConfig):
    try:
        return list_ros_topics(payload)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/ros/runtime-params", response_model=RosRuntimeParamsResponse)
def post_ros_runtime_params(payload: RosDataSourceConfig):
    try:
        return list_ros_runtime_params(payload)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/dialogs/browse", response_model=BrowseDialogResponse)
def post_browse_dialog(payload: BrowseDialogRequest):
    return BrowseDialogResponse(
        path=browse_local_path(
            mode=payload.mode,
            title=payload.title,
            initial_path=payload.initial_path,
        )
    )


@router.post("/dialogs/open-path")
def post_open_path(payload: OpenPathRequest):
    try:
        open_path_in_system(payload.path)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok"}


@router.get("/files/image")
def get_local_image(path: str):
    file_path = Path(path)
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"文件不存在: {path}")
    media_type, _ = mimetypes.guess_type(str(file_path))
    if not media_type or not media_type.startswith("image/"):
        raise HTTPException(status_code=400, detail=f"不是图片文件: {path}")
    return FileResponse(file_path, media_type=media_type)


@router.get("/files/pgm-image")
def get_local_pgm_image(path: str):
    file_path = Path(path)
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"文件不存在: {path}")
    try:
        from PIL import Image
    except ModuleNotFoundError as exc:
        raise HTTPException(status_code=500, detail="缺少 Pillow，无法转换 PGM 地图。") from exc
    try:
        with Image.open(file_path) as image:
            output = BytesIO()
            image.convert("L").save(output, format="PNG")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"PGM 地图转换失败: {path}") from exc
    return Response(content=output.getvalue(), media_type="image/png")


@router.get("/files/text")
def get_local_text(path: str):
    try:
        return {"path": path, "content": read_nav_recording_text(path)}
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/nav-recordings", response_model=NavRecordingFileListResponse)
def get_nav_recordings():
    return list_nav_recording_files()


@router.post("/nav-recordings", response_model=NavRecordingFileListResponse)
def post_nav_recording(payload: NavRecordingSaveRequest):
    return save_nav_recording(payload)


@router.delete("/nav-recordings", response_model=NavRecordingFileListResponse)
def delete_nav_recording(payload: DeletePathRequest):
    try:
        return delete_nav_recording_file(payload.path)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/tools/pcd_tile/preview", response_model=TilePreviewResponse)
def get_pcd_tile_preview(path: str, tile_size: float = 20.0):
    if not is_tool_enabled("pcd_tile"):
        raise HTTPException(status_code=404, detail="Tool not enabled")
    return preview_pcd_tile(path=path, tile_size=tile_size)


@router.get("/tools/global_relocalization_candidates/pcd-preview")
def get_global_relocalization_pcd_preview(path: str, max_points: int = 90000):
    if not is_tool_enabled("global_relocalization_candidates"):
        raise HTTPException(status_code=404, detail="Tool not enabled")
    try:
        return preview_pcd_points(path=path, max_points=max_points)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/tools/ros_nav_test/offline-map-preview")
def get_ros_nav_offline_map_preview(
    pcd_path: str,
    map_yaml_path: str = "",
    map_pgm_path: str = "",
    voxel_leaf_m: float = 0.20,
    occupancy_voxel_m: float = 0.30,
    max_points: int = 60000,
    max_voxels: int = 60000,
):
    if not is_tool_enabled("ros_nav_test"):
        raise HTTPException(status_code=404, detail="Tool not enabled")
    try:
        return preview_nav_offline_map(
            pcd_path=pcd_path,
            map_yaml_path=map_yaml_path,
            map_pgm_path=map_pgm_path,
            voxel_leaf_m=voxel_leaf_m,
            occupancy_voxel_m=occupancy_voxel_m,
            max_points=max_points,
            max_voxels=max_voxels,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"离线地图预览接口异常: {type(exc).__name__}: {exc}") from exc


@router.post("/tools/ros_nav_test/offline-map-raycast")
def post_ros_nav_offline_map_raycast(payload: dict):
    if not is_tool_enabled("ros_nav_test"):
        raise HTTPException(status_code=404, detail="Tool not enabled")
    try:
        return raycast_nav_offline_map(
            origin=payload.get("origin") or [],
            direction=payload.get("direction") or [],
            max_distance_m=float(payload.get("max_distance_m") or 80.0),
            normal_radius_m=float(payload.get("normal_radius_m") or 0.8),
            ground_max_slope_deg=float(payload.get("ground_max_slope_deg") or 30.0),
            clip_bounds=payload.get("clip_bounds"),
            use_visible_voxels=payload.get("use_visible_voxels") is not False,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"离线地图射线查询异常: {type(exc).__name__}: {exc}") from exc


@router.get("/tools/global_relocalization_candidates/candidates")
def get_global_relocalization_candidates(path: str, max_candidates: int = 200000):
    if not is_tool_enabled("global_relocalization_candidates"):
        raise HTTPException(status_code=404, detail="Tool not enabled")
    try:
        return load_candidates(path=path, max_candidates=max_candidates)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/tools/global_relocalization_candidates/manual-export")
def post_global_relocalization_manual_export(payload: dict):
    if not is_tool_enabled("global_relocalization_candidates"):
        raise HTTPException(status_code=404, detail="Tool not enabled")
    try:
        return export_manual_candidates(payload)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/tools/global_relocalization_candidates/final-export")
def post_global_relocalization_final_export(payload: dict):
    if not is_tool_enabled("global_relocalization_candidates"):
        raise HTTPException(status_code=404, detail="Tool not enabled")
    raise HTTPException(status_code=400, detail="final-export 已停用；请使用“确认候选点”，该入口会调用 C++ 基于 PCD 生成真实 descriptors.npy/ring_keys.npy。")


@router.get("/tools/imu_calibration/inspect")
def get_imu_calibration_inspect(path: str):
    if not is_tool_enabled("imu_calibration"):
        raise HTTPException(status_code=404, detail="Tool not enabled")
    try:
        return inspect_imu_bag(path)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"IMU 包检查异常: {type(exc).__name__}: {exc}") from exc


@router.post("/tools/imu_calibration/analyze")
def post_imu_calibration_analyze(payload: dict):
    if not is_tool_enabled("imu_calibration"):
        raise HTTPException(status_code=404, detail="Tool not enabled")
    try:
        return analyze_imu_bag(payload)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"IMU 标定异常: {type(exc).__name__}: {exc}") from exc


@router.post("/tools/{tool_key}/run", response_model=ToolRunResponse)
def run_tool(tool_key: str, request: ToolRunRequest):
    if not is_tool_enabled(tool_key):
        raise HTTPException(status_code=404, detail="Tool not enabled")

    tool = next((item for item in get_tool_definitions() if item.key == tool_key), None)
    if tool is None:
        raise HTTPException(status_code=404, detail="Tool not found")

    values = {key: str(value) for key, value in request.values.items()}
    # 所有 CLI 与本地文件服务使用同一工作区基准，避免启动目录改变输出位置。
    workspace = Path(__file__).resolve().parents[3]
    for key in ["input_pcd", "output_dir", "config_path", "candidate_file", "manual_file"]:
        if values.get(key, "").strip():
            path = Path(values[key]).expanduser()
            values[key] = str(path if path.is_absolute() else workspace / path)
    try:
        if tool_key == "pcd_map":
            return run_pcd_map(values)
        if tool_key == "pcd_tile":
            return run_pcd_tile(values)
        if tool_key == "global_relocalization_candidates":
            return run_global_relocalization_candidates(values)
        if tool_key == "ros_nav_test":
            inspection = inspect_ros_data_source(RosDataSourceConfig(
                provider=values.get("ros_provider") or "rosbridge",
                options={"url": values.get("ros_bridge_url", ""), "rosapi_service": values.get("ros_api_service") or "/rosapi/topics_and_raw_types", "timeout_ms": values.get("timeout_ms") or "8000"},
            ))
            return ToolRunResponse(tool=tool_key, status=inspection.status, summary=inspection.message,
                logs=[inspection.message, *inspection.detected_hints], data=inspection.model_dump())
        if tool_key == "imu_calibration":
            return run_imu_calibration(values)
    except RuntimeError as exc:
        return ToolRunResponse(
            tool=tool_key,
            status="error",
            summary=str(exc),
            logs=[f"[ERROR] {exc}"],
            data={},
        )

    raise HTTPException(status_code=404, detail="未知工具")
