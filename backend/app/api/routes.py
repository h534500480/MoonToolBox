from fastapi import APIRouter, HTTPException

from app.catalog import TOOL_DEFINITIONS
from app.models import PreferencesPayload, ToolRunRequest, ToolRunResponse
from app.services.cpp_runner import run_pcd_map
from app.services.preferences import load_preferences, save_preferences


router = APIRouter()


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/tools")
def list_tools():
    return TOOL_DEFINITIONS


@router.get("/preferences", response_model=PreferencesPayload)
def get_preferences():
    return load_preferences()


@router.put("/preferences", response_model=PreferencesPayload)
def put_preferences(payload: PreferencesPayload):
    return save_preferences(payload)


@router.post("/tools/{tool_key}/run", response_model=ToolRunResponse)
def run_tool(tool_key: str, request: ToolRunRequest):
    tool = next((item for item in TOOL_DEFINITIONS if item.key == tool_key), None)
    if tool is None:
        raise HTTPException(status_code=404, detail="Tool not found")

    values = {key: str(value) for key, value in request.values.items()}
    if tool_key == "pcd_map":
        return run_pcd_map(values)

    logs = [
        f"[INFO] selected tool: {tool.title}",
        f"[INFO] received {len(values)} input fields",
        "[INFO] backend workflow shell is ready",
        "[NEXT] wire this route to the real C++ CLI or Python task service",
    ]
    summary = f"{tool.title} request accepted. Current backend is a scaffold and echoes form values."
    return ToolRunResponse(tool=tool.key, status="ready", summary=summary, logs=logs)
