from fastapi import APIRouter, HTTPException

from app.catalog import TOOL_DEFINITIONS
from app.models import (
    BrowseDialogRequest,
    BrowseDialogResponse,
    OpenPathRequest,
    PreferencesPayload,
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
from app.services.pcd_preview import preview_pcd_tile
from app.services.preferences import load_preferences, save_preferences
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
    return TOOL_DEFINITIONS


@router.get("/preferences", response_model=PreferencesPayload)
def get_preferences():
    return load_preferences()


@router.put("/preferences", response_model=PreferencesPayload)
def put_preferences(payload: PreferencesPayload):
    return save_preferences(payload)


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


@router.get("/tools/pcd_tile/preview", response_model=TilePreviewResponse)
def get_pcd_tile_preview(path: str, tile_size: float = 20.0):
    return preview_pcd_tile(path=path, tile_size=tile_size)


@router.post("/tools/mtslash_export/login-captcha")
def post_mtslash_login_captcha():
    try:
        return start_mtslash_login_session()
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/tools/mtslash_export/login")
def post_mtslash_login(payload: dict):
    values = {key: str(value) for key, value in payload.items()}
    try:
        return submit_mtslash_login(values)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/tools/mtslash_export/favorites")
def get_mtslash_favorites(session_id: str, max_pages: int = 200):
    try:
        max_pages = max(1, min(max_pages, 200))
        return fetch_mtslash_favorites(session_id=session_id, max_pages=max_pages)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/tools/mtslash_export/browser/favorites")
def get_mtslash_browser_favorites(browser: str = "edge", max_pages: int = 200):
    try:
        max_pages = max(1, min(max_pages, 200))
        return fetch_mtslash_browser_favorites(browser=browser, max_pages=max_pages)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/tools/mtslash_export/browser/start")
def post_mtslash_browser_start(payload: dict):
    browser = str(payload.get("browser", "edge"))
    try:
        return start_browser(browser)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/tools/mtslash_export/browser/tabs")
def get_mtslash_browser_tabs(browser: str = "edge"):
    try:
        return {"status": "success", "items": list_tabs(browser)}
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/tools/{tool_key}/run", response_model=ToolRunResponse)
def run_tool(tool_key: str, request: ToolRunRequest):
    tool = next((item for item in TOOL_DEFINITIONS if item.key == tool_key), None)
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
