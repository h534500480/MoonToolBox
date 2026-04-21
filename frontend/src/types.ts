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
