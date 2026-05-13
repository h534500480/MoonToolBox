export interface ToolField {
  key: string;
  label: string;
  value: string;
  placeholder: string;
}

export interface ToolDefinition {
  key: string;
  title: string;
  subtitle: string;
  description: string;
  primary_action: string;
  secondary_action: string;
  fields: ToolField[];
}

export interface ToolRunResponse {
  tool: string;
  status: string;
  summary: string;
  logs: string[];
  data?: Record<string, any>;
}

export interface ToolSection {
  key: string;
  label: string;
}

export interface PreferencesPayload {
  sections: ToolSection[];
  section_assignments: Record<string, string>;
  favorite_keys: string[];
}

export interface BrowseDialogPayload {
  mode: "open_file" | "open_dir" | "save_file";
  title: string;
  initial_path: string;
}

export interface SystemInfoResponse {
  local_ip: string;
  subnet_prefix: string;
  app_root: string;
}

export interface RosDataSourceConfig {
  provider: string;
  options: Record<string, string>;
}

export interface RosInspectionResponse {
  provider: string;
  status: string;
  message: string;
  capabilities: string[];
  detected_hints: string[];
  topics_count: number;
}

export interface RosTopicItem {
  name: string;
  type: string;
}

export interface RosTopicListResponse {
  provider: string;
  status: string;
  message: string;
  topics: RosTopicItem[];
}

export interface NavRecordingMetricSample {
  offset_ms: number;
  value: number;
}

export interface NavRecordingMetricSeries {
  label: string;
  unit: string;
  color: string;
  samples: NavRecordingMetricSample[];
}

export interface NavRecordingSavePayload {
  panel_id: string;
  title: string;
  topic: string;
  message_type: string;
  started_at_ms: number;
  started_at: string;
  stopped_at: string;
  duration_ms: number;
  entries: string[];
  metric_series: NavRecordingMetricSeries[];
}

export interface NavRecordingFileItem {
  name: string;
  path: string;
  kind: "text" | "image";
  size_bytes: number;
  modified_at: string;
}

export interface NavRecordingFileListResponse {
  directory: string;
  items: NavRecordingFileItem[];
}
