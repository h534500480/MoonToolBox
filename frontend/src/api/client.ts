import type { BrowseDialogPayload, ToolDefinition, ToolRunResponse, PreferencesPayload, SystemInfoResponse } from "../types";

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
    let detail = "Failed to run tool";
    try {
      const data = await response.json();
      detail = data.detail ?? detail;
    } catch {
      // Keep fallback message.
    }
    throw new Error(detail);
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

export async function fetchSystemInfo(): Promise<SystemInfoResponse> {
  const response = await fetch(`${API_BASE}/system/info`);
  if (!response.ok) {
    throw new Error("Failed to load system info");
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

export async function browsePath(payload: BrowseDialogPayload): Promise<string> {
  const response = await fetch(`${API_BASE}/dialogs/browse`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify(payload)
  });
  if (!response.ok) {
    throw new Error("Failed to open browse dialog");
  }
  const data = await response.json();
  return data.path ?? "";
}

export async function openLocalPath(path: string): Promise<void> {
  const response = await fetch(`${API_BASE}/dialogs/open-path`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ path })
  });
  if (!response.ok) {
    let detail = "Failed to open path";
    try {
      const data = await response.json();
      detail = data.detail ?? detail;
    } catch {
      // Keep fallback message.
    }
    throw new Error(detail);
  }
}

export interface TilePreviewResponse {
  point_count: number;
  xmin: number;
  xmax: number;
  ymin: number;
  ymax: number;
  zmin: number;
  zmax: number;
  estimated_tiles: number;
}

export async function fetchPcdTilePreview(path: string, tileSize: string): Promise<TilePreviewResponse> {
  const query = new URLSearchParams({
    path,
    tile_size: tileSize || "20.0"
  });
  const response = await fetch(`${API_BASE}/tools/pcd_tile/preview?${query.toString()}`);
  if (!response.ok) {
    throw new Error("Failed to preview pcd tile");
  }
  return response.json();
}

export interface MtslashCaptchaResponse {
  session_id: string;
  captcha_image: string;
  message: string;
}

export async function fetchMtslashCaptcha(): Promise<MtslashCaptchaResponse> {
  const response = await fetch(`${API_BASE}/tools/mtslash_export/login-captcha`, {
    method: "POST"
  });
  if (!response.ok) {
    let detail = "Failed to fetch captcha";
    try {
      const data = await response.json();
      detail = data.detail ?? detail;
    } catch {
      // Keep fallback message.
    }
    throw new Error(detail);
  }
  return response.json();
}

export interface MtslashLoginResponse {
  status: string;
  message: string;
  session_id: string;
}

export async function loginMtslash(values: Record<string, string>): Promise<MtslashLoginResponse> {
  const response = await fetch(`${API_BASE}/tools/mtslash_export/login`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify(values)
  });
  if (!response.ok) {
    let detail = "Failed to login";
    try {
      const data = await response.json();
      detail = data.detail ?? detail;
    } catch {
      // Keep fallback message.
    }
    throw new Error(detail);
  }
  return response.json();
}

export interface MtslashFavoriteItem {
  title: string;
  url: string;
}

export interface MtslashFavoritesResponse {
  status: string;
  page_count: number;
  items: MtslashFavoriteItem[];
}

export async function fetchMtslashFavorites(sessionId: string): Promise<MtslashFavoritesResponse> {
  const query = new URLSearchParams({
    session_id: sessionId,
    max_pages: "50"
  });
  const response = await fetch(`${API_BASE}/tools/mtslash_export/favorites?${query.toString()}`);
  if (!response.ok) {
    let detail = "Failed to fetch favorites";
    try {
      const data = await response.json();
      detail = data.detail ?? detail;
    } catch {
      // Keep fallback message.
    }
    throw new Error(detail);
  }
  return response.json();
}
