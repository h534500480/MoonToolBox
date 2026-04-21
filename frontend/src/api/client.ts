import type { PreferencesPayload, ToolDefinition, ToolRunResponse } from "../types";

const API_BASE = "http://127.0.0.1:8000/api";

export async function fetchTools(): Promise<ToolDefinition[]> {
  const response = await fetch(`${API_BASE}/tools`);
  if (!response.ok) {
    throw new Error("Failed to load tools");
  }
  return response.json();
}

export async function runTool(toolKey: string, values: Record<string, string>): Promise<ToolRunResponse> {
  const response = await fetch(`${API_BASE}/tools/${toolKey}/run`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ values })
  });
  if (!response.ok) {
    throw new Error("Failed to run tool");
  }
  return response.json();
}

export async function fetchPreferences(): Promise<PreferencesPayload> {
  const response = await fetch(`${API_BASE}/preferences`);
  if (!response.ok) {
    throw new Error("Failed to load preferences");
  }
  return response.json();
}

export async function savePreferences(payload: PreferencesPayload): Promise<PreferencesPayload> {
  const response = await fetch(`${API_BASE}/preferences`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify(payload)
  });
  if (!response.ok) {
    throw new Error("Failed to save preferences");
  }
  return response.json();
}
