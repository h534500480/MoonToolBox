from typing import Any, Dict, List

from pydantic import BaseModel, Field


class ToolField(BaseModel):
    key: str
    label: str
    value: str = ""
    placeholder: str = ""


class ToolDefinition(BaseModel):
    key: str
    title: str
    subtitle: str
    description: str
    primary_action: str
    secondary_action: str
    fields: List[ToolField] = Field(default_factory=list)


class ToolRunRequest(BaseModel):
    values: Dict[str, Any] = Field(default_factory=dict)


class ToolRunResponse(BaseModel):
    tool: str
    status: str
    summary: str
    logs: List[str] = Field(default_factory=list)
    data: Dict[str, Any] = Field(default_factory=dict)


class ToolSection(BaseModel):
    key: str
    label: str


class PreferencesPayload(BaseModel):
    sections: List[ToolSection] = Field(default_factory=list)
    section_assignments: Dict[str, str] = Field(default_factory=dict)
    favorite_keys: List[str] = Field(default_factory=list)


class BrowseDialogRequest(BaseModel):
    mode: str = "open_file"
    title: str = "Select Path"
    initial_path: str = ""


class BrowseDialogResponse(BaseModel):
    path: str = ""


class TilePreviewResponse(BaseModel):
    point_count: int = 0
    xmin: float = 0.0
    xmax: float = 0.0
    ymin: float = 0.0
    ymax: float = 0.0
    zmin: float = 0.0
    zmax: float = 0.0
    estimated_tiles: int = 0


class OpenPathRequest(BaseModel):
    path: str


class SystemInfoResponse(BaseModel):
    local_ip: str = ""
    subnet_prefix: str = ""
