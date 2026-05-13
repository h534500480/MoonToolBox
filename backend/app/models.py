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
    app_root: str = ""


class RosDataSourceConfig(BaseModel):
    provider: str = "rosbridge"
    options: Dict[str, str] = Field(default_factory=dict)


class RosInspectionResponse(BaseModel):
    provider: str = ""
    status: str = "unknown"
    message: str = ""
    capabilities: List[str] = Field(default_factory=list)
    detected_hints: List[str] = Field(default_factory=list)
    topics_count: int = 0


class RosTopicItem(BaseModel):
    name: str = ""
    type: str = ""


class RosTopicListResponse(BaseModel):
    provider: str = ""
    status: str = "unknown"
    message: str = ""
    topics: List[RosTopicItem] = Field(default_factory=list)


class NavRecordingMetricSample(BaseModel):
    offset_ms: int = 0
    value: float = 0.0


class NavRecordingMetricSeries(BaseModel):
    label: str = ""
    unit: str = ""
    color: str = "#2f8cff"
    samples: List[NavRecordingMetricSample] = Field(default_factory=list)


class NavRecordingSaveRequest(BaseModel):
    panel_id: str = ""
    title: str = ""
    topic: str = ""
    message_type: str = ""
    started_at_ms: int = 0
    started_at: str = ""
    stopped_at: str = ""
    duration_ms: int = 0
    entries: List[str] = Field(default_factory=list)
    metric_series: List[NavRecordingMetricSeries] = Field(default_factory=list)


class NavRecordingFileItem(BaseModel):
    name: str = ""
    path: str = ""
    kind: str = "text"
    size_bytes: int = 0
    modified_at: str = ""


class NavRecordingFileListResponse(BaseModel):
    directory: str = ""
    items: List[NavRecordingFileItem] = Field(default_factory=list)


class DeletePathRequest(BaseModel):
    path: str = ""
