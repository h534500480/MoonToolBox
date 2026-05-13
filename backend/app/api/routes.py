import mimetypes
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.catalog import get_tool_definitions, is_tool_enabled
from app.models import (
    BrowseDialogRequest,
    BrowseDialogResponse,
    DeletePathRequest,
    NavRecordingFileListResponse,
    NavRecordingSaveRequest,
    OpenPathRequest,
    PreferencesPayload,
    RosDataSourceConfig,
    RosInspectionResponse,
    RosTopicListResponse,
    SystemInfoResponse,
    TilePreviewResponse,
    ToolRunRequest,
    ToolRunResponse,
)
from app.services.costmap_playback import run_costmap
from app.services.browser_bridge import list_tabs, start_browser
from app.services.cpp_runner import run_pcd_map, run_pcd_tile
from app.services.dialogs import browse_local_path
from app.services.mtslash_exporter import (
    fetch_mtslash_browser_favorites,
    fetch_mtslash_favorites,
    run_mtslash_export,
    start_mtslash_login_session,
    submit_mtslash_login,
)
from app.services.network_scan import run_network_scan
from app.services.nav_recordings import (
    delete_nav_recording_file,
    list_nav_recording_files,
    read_nav_recording_text,
    save_nav_recording,
)
from app.services.pcd_preview import preview_pcd_tile
from app.services.preferences import load_preferences, save_preferences
from app.services.ros_data_source import (
    inspect_ros_data_source,
    list_ros_topics,
    load_ros_data_source_config,
    save_ros_data_source_config,
)
from app.services.system_info import get_system_info
from app.services.system_actions import open_path_in_system


router = APIRouter()


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/system/info", response_model=SystemInfoResponse)
def system_info():
    return get_system_info()


@router.get("/tools")
def list_tools():
    return get_tool_definitions()


@router.get("/preferences", response_model=PreferencesPayload)
def get_preferences():
    return load_preferences()


@router.put("/preferences", response_model=PreferencesPayload)
def put_preferences(payload: PreferencesPayload):
    return save_preferences(payload)


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


@router.post("/tools/mtslash_export/login-captcha")
def post_mtslash_login_captcha():
    if not is_tool_enabled("mtslash_export"):
        raise HTTPException(status_code=404, detail="Tool not enabled")
    try:
        return start_mtslash_login_session()
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/tools/mtslash_export/login")
def post_mtslash_login(payload: dict):
    if not is_tool_enabled("mtslash_export"):
        raise HTTPException(status_code=404, detail="Tool not enabled")
    values = {key: str(value) for key, value in payload.items()}
    try:
        return submit_mtslash_login(values)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/tools/mtslash_export/favorites")
def get_mtslash_favorites(session_id: str, max_pages: int = 200):
    if not is_tool_enabled("mtslash_export"):
        raise HTTPException(status_code=404, detail="Tool not enabled")
    try:
        max_pages = max(1, min(max_pages, 200))
        return fetch_mtslash_favorites(session_id=session_id, max_pages=max_pages)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/tools/mtslash_export/browser/favorites")
def get_mtslash_browser_favorites(browser: str = "edge", max_pages: int = 200):
    if not is_tool_enabled("mtslash_export"):
        raise HTTPException(status_code=404, detail="Tool not enabled")
    try:
        max_pages = max(1, min(max_pages, 200))
        return fetch_mtslash_browser_favorites(browser=browser, max_pages=max_pages)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/tools/mtslash_export/browser/start")
def post_mtslash_browser_start(payload: dict):
    if not is_tool_enabled("mtslash_export"):
        raise HTTPException(status_code=404, detail="Tool not enabled")
    browser = str(payload.get("browser", "edge"))
    try:
        return start_browser(browser)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/tools/mtslash_export/browser/tabs")
def get_mtslash_browser_tabs(browser: str = "edge"):
    if not is_tool_enabled("mtslash_export"):
        raise HTTPException(status_code=404, detail="Tool not enabled")
    try:
        return {"status": "success", "items": list_tabs(browser)}
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/tools/{tool_key}/run", response_model=ToolRunResponse)
def run_tool(tool_key: str, request: ToolRunRequest):
    if not is_tool_enabled(tool_key):
        raise HTTPException(status_code=404, detail="Tool not enabled")

    tool = next((item for item in get_tool_definitions() if item.key == tool_key), None)
    if tool is None:
        raise HTTPException(status_code=404, detail="Tool not found")

    values = {key: str(value) for key, value in request.values.items()}
    try:
        if tool_key == "pcd_map":
            return run_pcd_map(values)
        if tool_key == "pcd_tile":
            return run_pcd_tile(values)
        if tool_key == "network_scan":
            return run_network_scan(values)
        if tool_key == "costmap":
            return run_costmap(values)
        if tool_key == "ros_nav_test":
            logs = [
                "[INFO] ROS 定位导航测试布局已启动",
                f"[INFO] bridge: {values.get('ros_bridge_url', 'ws://127.0.0.1:9090')}",
                f"[INFO] fixed frame: {values.get('fixed_frame', 'map')}",
                "[NEXT] 后续在这里接入 ROS topic 订阅、3D 渲染和小窗数据生命周期控制",
            ]
            return ToolRunResponse(
                tool=tool_key,
                status="ready",
                summary="导航测试工作台布局已就绪，当前版本用于确认三维主视图、话题选择和可折叠小窗区结构。",
                logs=logs,
                data={
                    "bridge_url": values.get("ros_bridge_url", "ws://127.0.0.1:9090"),
                    "fixed_frame": values.get("fixed_frame", "map"),
                },
            )
        if tool_key == "mtslash_export":
            return run_mtslash_export(values)
    except RuntimeError as exc:
        return ToolRunResponse(
            tool=tool_key,
            status="error",
            summary=str(exc),
            logs=[f"[ERROR] {exc}"],
            data={},
        )

    logs = [
        f"[INFO] selected tool: {tool.title}",
        f"[INFO] received {len(values)} input fields",
        "[INFO] backend workflow shell is ready",
        "[NEXT] wire this route to the real C++ CLI or Python task service",
    ]
    summary = f"{tool.title} request accepted. Current backend is a scaffold and echoes form values."
    return ToolRunResponse(tool=tool.key, status="ready", summary=summary, logs=logs)
