/**
 * 功能说明：
 * 维护移动端 ROS APP 的连接配置、主视图显示项和话题列表等共享状态。
 */
import { reactive } from "vue";

import type { RosDataSourceConfig, RosInspectionResponse, RosRuntimeParamsResponse } from "../../types";
import type { RosLiveAdapter } from "./liveAdapter";
import {
  MOBILE_ROS_STORAGE_KEY,
  defaultMobileRosConnectionConfig,
  defaultMobileTopicOptions,
  mergeMobileTopicOptions,
  topicOptionToMobileDisplay,
  type MobileNavTopicOption,
  type MobileRosConnectionConfig,
} from "./mobileCatalog";
import type { NavViewerDisplay } from "./displayRegistry";
import { inspectRosDataSourceDirect, listRosRuntimeParamsDirect, listRosTopicsDirect } from "./directRosClient";

interface MobileRosStoredState {
  connection: MobileRosConnectionConfig;
  mainDisplays: NavViewerDisplay[];
}

export const mobileRosAppState = reactive({
  connection: { ...defaultMobileRosConnectionConfig } as MobileRosConnectionConfig,
  mainDisplays: [] as NavViewerDisplay[],
  topicOptions: [...defaultMobileTopicOptions] as MobileNavTopicOption[],
  topicsLoading: false,
  topicsMessage: "",
  inspectLoading: false,
  inspectResult: null as RosInspectionResponse | null,
  runtimeLoading: false,
  runtimeParams: null as RosRuntimeParamsResponse | null,
  runtimeMessage: "",
});

function buildDataSourceConfig(timeoutOverrideMs?: number): RosDataSourceConfig {
  const baseTimeoutMs = mobileRosAppState.connection.timeoutMs || "8000";
  return {
    provider: mobileRosAppState.connection.provider || "rosbridge",
    options: {
      url: mobileRosAppState.connection.url.trim(),
      rosapi_service: mobileRosAppState.connection.rosapiService.trim() || "/rosapi/topics_and_raw_types",
      timeout_ms: timeoutOverrideMs ? String(timeoutOverrideMs) : baseTimeoutMs,
    },
  };
}

export function loadMobileRosAppState() {
  const raw = window.localStorage.getItem(MOBILE_ROS_STORAGE_KEY);
  if (!raw) {
    return;
  }
  try {
    const parsed = JSON.parse(raw) as Partial<MobileRosStoredState>;
    mobileRosAppState.connection = {
      ...defaultMobileRosConnectionConfig,
      ...(parsed.connection || {}),
    };
    mobileRosAppState.mainDisplays = Array.isArray(parsed.mainDisplays) ? parsed.mainDisplays : [];
  } catch {
    // 本地缓存损坏时回退默认值，避免阻断页面使用。
  }
}

export function persistMobileRosAppState() {
  const payload: MobileRosStoredState = {
    connection: mobileRosAppState.connection,
    mainDisplays: mobileRosAppState.mainDisplays,
  };
  window.localStorage.setItem(MOBILE_ROS_STORAGE_KEY, JSON.stringify(payload));
}

export function updateMobileConnectionConfig(patch: Partial<MobileRosConnectionConfig>) {
  mobileRosAppState.connection = {
    ...mobileRosAppState.connection,
    ...patch,
  };
  persistMobileRosAppState();
}

export function hasMobileMainDisplay(topic: string) {
  return mobileRosAppState.mainDisplays.some((item) => item.topic === topic);
}

export function addTopicToMobileMainView(option: MobileNavTopicOption) {
  if (hasMobileMainDisplay(option.key)) {
    return;
  }
  mobileRosAppState.mainDisplays = [...mobileRosAppState.mainDisplays, topicOptionToMobileDisplay(option)];
  persistMobileRosAppState();
}

export function removeTopicFromMobileMainView(topic: string) {
  mobileRosAppState.mainDisplays = mobileRosAppState.mainDisplays.filter((item) => item.topic !== topic);
  persistMobileRosAppState();
}

export function updateMobileMainDisplay(topic: string, patch: Partial<NavViewerDisplay>) {
  mobileRosAppState.mainDisplays = mobileRosAppState.mainDisplays.map((item) => {
    if (item.topic !== topic) {
      return item;
    }
    return {
      ...item,
      ...patch,
    };
  });
  persistMobileRosAppState();
}

export async function inspectMobileRosConnection(adapter?: RosLiveAdapter) {
  mobileRosAppState.inspectLoading = true;
  try {
    mobileRosAppState.inspectResult = await inspectRosDataSourceDirect(buildDataSourceConfig(), adapter ? { adapter } : undefined);
    mobileRosAppState.runtimeMessage = mobileRosAppState.inspectResult.message;
  } finally {
    mobileRosAppState.inspectLoading = false;
  }
}

export async function refreshMobileTopics(adapter?: RosLiveAdapter) {
  mobileRosAppState.topicsLoading = true;
  try {
    const response = await listRosTopicsDirect(buildDataSourceConfig(15000), adapter ? { adapter } : undefined, { serviceTimeoutMs: 15000 });
    const merged = mergeMobileTopicOptions(response.topics.map((topic) => ({
      key: topic.name,
      label: topic.name.split("/").filter(Boolean).pop() || topic.name,
      type: topic.type,
      note: "来自机器人实时 ROS 话题列表。",
    })));
    mobileRosAppState.topicOptions = merged;
    mobileRosAppState.topicsMessage = response.message;
  } catch (error) {
    mobileRosAppState.topicsMessage = `读取话题失败: ${(error as Error).message}`;
  } finally {
    mobileRosAppState.topicsLoading = false;
  }
}

export async function refreshMobileRuntimeParams(adapter?: RosLiveAdapter) {
  mobileRosAppState.runtimeLoading = true;
  try {
    mobileRosAppState.runtimeParams = await listRosRuntimeParamsDirect(buildDataSourceConfig(), adapter ? { adapter } : undefined);
    mobileRosAppState.runtimeMessage = mobileRosAppState.runtimeParams.message;
  } catch (error) {
    mobileRosAppState.runtimeMessage = `读取运行时参数失败: ${(error as Error).message}`;
  } finally {
    mobileRosAppState.runtimeLoading = false;
  }
}

export function currentMobileDataSourceConfig() {
  return buildDataSourceConfig();
}
