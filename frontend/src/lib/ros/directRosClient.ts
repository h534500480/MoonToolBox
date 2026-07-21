/**
 * 功能说明：
 * 通过 rosbridge + rosapi 直接在前端读取话题列表、服务列表和运行时参数，
 * 让移动端 APK 在没有独立后端服务的情况下也能完成 ROS 测试。
 */
import * as ROSLIB from "roslib";

import type { RosLiveAdapter } from "./liveAdapter";
import type {
  RosDataSourceConfig,
  RosInspectionResponse,
  RosRuntimeParamGroup,
  RosRuntimeParamNode,
  RosRuntimeParamsResponse,
  RosRuntimeParamSection,
  RosTopicItem,
  RosTopicListResponse,
} from "../../types";

const runtimeGroups: Array<[string, string, Array<[string, string[]]>]> = [
  [
    "nav2",
    "Nav2",
    [
      ["规划", ["/planner_server"]],
      ["控制", ["/controller_server"]],
      ["行为与导航状态机", ["/behavior_server", "/bt_navigator"]],
      ["代价地图", ["/local_costmap/local_costmap", "/global_costmap/global_costmap"]],
    ],
  ],
  [
    "ndt",
    "NDT",
    [
      ["点云预处理", ["/cloud_filter_node", "/custom_to_pointcloud2", "/cloud_frame_rewriter"]],
      ["IMU 与滤波", ["/imu_source_bridge", "/ekf_filter_node"]],
      ["定位辅助与时序", ["/initialpose_bridge", "/map_odom_publisher", "/ndt_score_bridge", "/localization_startup_manager", "/ndt_health_monitor"]],
      ["NDT 与地图", ["/ndt_scan_matcher", "/pcd_loader_service", "/map_server", "/lifecycle_manager_localization"]],
    ],
  ],
];

function timeoutMsFromConfig(config: RosDataSourceConfig) {
  const raw = config.options.timeout_ms || "8000";
  const parsed = Number(raw);
  return Number.isFinite(parsed) && parsed > 0 ? Math.max(8000, parsed) : 8000;
}

function serviceName(nodeName: string, suffix: string) {
  const normalized = nodeName.replace(/\/+$/g, "");
  return normalized ? `${normalized}/${suffix}` : `/${suffix}`;
}

type RosServiceCaller = <T>(service: string, serviceType: string, request: Record<string, unknown>, timeoutMs: number) => Promise<T>;

interface DirectRosExecutionContext {
  ros?: ROSLIB.Ros;
  adapter?: RosLiveAdapter;
}

interface DirectRosCallOptions {
  serviceTimeoutMs?: number;
}

async function withRosConnection<T>(config: RosDataSourceConfig, worker: (ros: ROSLIB.Ros) => Promise<T>): Promise<T> {
  const url = (config.options.url || "").trim();
  if (!url) {
    throw new Error("未配置 rosbridge WebSocket 地址。");
  }
  const timeoutMs = timeoutMsFromConfig(config);
  const ros = new ROSLIB.Ros();
  await new Promise<void>((resolve, reject) => {
    let settled = false;
    const timer = window.setTimeout(() => {
      if (settled) {
        return;
      }
      settled = true;
      try {
        ros.close();
      } catch {
        // 保持超时处理可继续。
      }
      reject(new Error(`连接超时: ${url}`));
    }, timeoutMs);

    const finish = (callback: () => void) => {
      if (settled) {
        return;
      }
      settled = true;
      window.clearTimeout(timer);
      callback();
    };

    ros.once("connection", () => finish(resolve));
    ros.once("error", (error: unknown) => {
      finish(() => reject(error instanceof Error ? error : new Error(String(error ?? "rosbridge 连接失败"))));
    });
    ros.connect(url);
  });

  try {
    return await worker(ros);
  } finally {
    try {
      ros.close();
    } catch {
      // 断开失败时不影响上层结果。
    }
  }
}

function createRosServiceCaller(ros: ROSLIB.Ros): RosServiceCaller {
  return async <T>(service: string, serviceType: string, request: Record<string, unknown>, timeoutMs: number) => {
    return await callRosService<T>(ros, service, serviceType, request, timeoutMs);
  };
}

function createAdapterServiceCaller(adapter: RosLiveAdapter): RosServiceCaller {
  return async <T>(service: string, serviceType: string, request: Record<string, unknown>, timeoutMs: number) => {
    return await adapter.callService<T>(service, serviceType, request, timeoutMs);
  };
}

async function withServiceCaller<T>(
  config: RosDataSourceConfig,
  context: DirectRosExecutionContext | undefined,
  worker: (callService: RosServiceCaller) => Promise<T>
): Promise<T> {
  if (context?.adapter) {
    return await worker(createAdapterServiceCaller(context.adapter));
  }
  if (context?.ros) {
    return await worker(createRosServiceCaller(context.ros));
  }
  return await withRosConnection(config, async (ros) => {
    return await worker(createRosServiceCaller(ros));
  });
}

async function callRosService<T>(ros: ROSLIB.Ros, service: string, serviceType: string, request: Record<string, unknown>, timeoutMs: number): Promise<T> {
  return await new Promise<T>((resolve, reject) => {
    const client = new ROSLIB.Service({
      ros,
      name: service,
      serviceType,
    });
    const timer = window.setTimeout(() => {
      reject(new Error(`调用服务超时: ${service}`));
    }, timeoutMs);
    client.callService(
      request as never,
      (response) => {
        window.clearTimeout(timer);
        resolve(response as T);
      },
      (error) => {
        window.clearTimeout(timer);
        reject(new Error(typeof error === "string" ? error : `调用服务失败: ${service}`));
      }
    );
  });
}

function decodeParameterValue(value: Record<string, unknown>) {
  const parameterType = Number(value.type ?? 0);
  if (parameterType === 1) {
    return Boolean(value.bool_value ?? false);
  }
  if (parameterType === 2) {
    return Number(value.integer_value ?? 0);
  }
  if (parameterType === 3) {
    return Number(value.double_value ?? 0);
  }
  if (parameterType === 4) {
    return String(value.string_value ?? "");
  }
  if (parameterType === 5) {
    return Array.isArray(value.byte_array_value) ? value.byte_array_value : [];
  }
  if (parameterType === 6) {
    return Array.isArray(value.bool_array_value) ? value.bool_array_value : [];
  }
  if (parameterType === 7) {
    return Array.isArray(value.integer_array_value) ? value.integer_array_value.map((item) => Number(item)) : [];
  }
  if (parameterType === 8) {
    return Array.isArray(value.double_array_value) ? value.double_array_value.map((item) => Number(item)) : [];
  }
  if (parameterType === 9) {
    return Array.isArray(value.string_array_value) ? value.string_array_value.map((item) => String(item)) : [];
  }
  return null;
}

async function listServices(callService: RosServiceCaller, timeoutMs: number) {
  const response = await callService<{ services?: string[] }>("/rosapi/services", "rosapi_msgs/srv/Services", {}, timeoutMs);
  return (response.services || []).map((item) => String(item).trim()).filter(Boolean);
}

async function resolveParameterService(callService: RosServiceCaller, nodeName: string, suffix: string, timeoutMs: number) {
  const directName = serviceName(nodeName, suffix);
  const services = await listServices(callService, timeoutMs);
  if (services.includes(directName)) {
    return directName;
  }
  const candidates = services.filter((item) => item.endsWith(directName));
  if (candidates.length === 1) {
    return candidates[0];
  }
  if (candidates.length > 1) {
    return candidates.sort((left, right) => left.length - right.length)[0];
  }
  throw new Error(`Service ${directName} does not exist`);
}

async function loadNodeRuntimeParams(callService: RosServiceCaller, nodeName: string, timeoutMs: number) {
  const listService = await resolveParameterService(callService, nodeName, "list_parameters", timeoutMs);
  const listResponse = await callService<{ result?: { names?: string[] } }>(
    listService,
    "rcl_interfaces/srv/ListParameters",
    { prefixes: [], depth: 100 },
    timeoutMs
  );
  const names = listResponse.result?.names || [];
  if (names.length === 0) {
    return {};
  }

  const getService = await resolveParameterService(callService, nodeName, "get_parameters", timeoutMs);
  const getResponse = await callService<{ values?: Array<Record<string, unknown>> }>(
    getService,
    "rcl_interfaces/srv/GetParameters",
    { names },
    timeoutMs
  );
  const values = getResponse.values || [];
  const params: Record<string, unknown> = {};
  names.forEach((name, index) => {
    params[String(name)] = decodeParameterValue(values[index] || {});
  });
  return params;
}

export async function inspectRosDataSourceDirect(config: RosDataSourceConfig, context?: DirectRosExecutionContext): Promise<RosInspectionResponse> {
  if ((config.provider || "rosbridge").trim().toLowerCase() !== "rosbridge") {
    return {
      provider: config.provider,
      status: "error",
      message: "移动端当前只支持 rosbridge 数据源。",
      capabilities: [],
      detected_hints: [],
      topics_count: 0,
    };
  }

  try {
    return await withServiceCaller(config, context, async (callService) => {
      const timeoutMs = timeoutMsFromConfig(config);
      await callService("/rosapi/get_time", "rosapi_msgs/srv/GetTime", {}, Math.min(timeoutMs, 10000));
      return {
        provider: "rosbridge",
        status: "success",
        message: "rosbridge 与 rosapi 轻量探测成功。",
        capabilities: ["inspect", "list_topics", "call_service"],
        detected_hints: [
          `WebSocket 连接成功: ${(config.options.url || "").trim()}`,
          "已通过 /rosapi/get_time 完成轻量服务探测。",
        ],
        topics_count: 0,
      };
    });
  } catch (error) {
    return {
      provider: "rosbridge",
      status: "error",
      message: `连接 rosbridge 失败: ${(error as Error).message}`,
      capabilities: [],
      detected_hints: [
        "请确认手机能访问机器人上的 rosbridge WebSocket。",
        "如果连的是局域网地址，请确认手机和机器人在同一网段。",
      ],
      topics_count: 0,
    };
  }
}

export async function listRosTopicsDirect(
  config: RosDataSourceConfig,
  context?: DirectRosExecutionContext,
  options?: DirectRosCallOptions
): Promise<RosTopicListResponse> {
  const executor = async (callService: RosServiceCaller) => {
    const timeoutMs = Math.max(timeoutMsFromConfig(config), options?.serviceTimeoutMs ?? 0);
    const serviceNameRaw = (config.options.rosapi_service || "/rosapi/topics_and_raw_types").trim() || "/rosapi/topics_and_raw_types";
    try {
      const response = await callService<{ topics?: string[]; types?: string[] }>(
        serviceNameRaw,
        "rosapi_msgs/srv/TopicsAndRawTypes",
        {},
        timeoutMs
      );
      const topics = response.topics || [];
      const types = response.types || [];
      return {
        provider: "rosbridge",
        status: "success",
        message: `已通过 ${serviceNameRaw} 获取 ${topics.length} 个 topic。`,
        topics: topics.map((topic, index) => ({ name: String(topic), type: String(types[index] || "") })),
      } satisfies RosTopicListResponse;
    } catch {
      const fallback = await callService<{ topics?: string[] }>("/rosapi/topics", "rosapi_msgs/srv/Topics", {}, timeoutMs);
      const topics = fallback.topics || [];
      return {
        provider: "rosbridge",
        status: "partial",
        message: "已通过 /rosapi/topics 获取 topic 名称，但没有拿到消息类型。",
        topics: topics.map((topic) => ({ name: String(topic), type: "" })),
      } satisfies RosTopicListResponse;
    }
  };

  return await withServiceCaller(config, context, executor);
}

export async function listRosRuntimeParamsDirect(config: RosDataSourceConfig, context?: DirectRosExecutionContext): Promise<RosRuntimeParamsResponse> {
  if ((config.provider || "rosbridge").trim().toLowerCase() !== "rosbridge") {
    return {
      provider: config.provider,
      status: "error",
      message: "移动端运行时参数窗口只支持 rosbridge 数据源。",
      updated_at: new Date().toISOString(),
      groups: [],
      failed_nodes: [],
    };
  }

  return await withServiceCaller(config, context, async (callService) => {
    const timeoutMs = timeoutMsFromConfig(config);
    const groups: RosRuntimeParamGroup[] = [];
    const failedNodes: string[] = [];

    for (const [groupKey, groupLabel, sections] of runtimeGroups) {
      const sectionItems: RosRuntimeParamSection[] = [];
      for (const [sectionTitle, nodeNames] of sections) {
        const nodes: RosRuntimeParamNode[] = [];
        for (const nodeName of nodeNames) {
          try {
            const params = await loadNodeRuntimeParams(callService, nodeName, timeoutMs);
            nodes.push({ node: nodeName, params, error: "" });
          } catch (error) {
            const message = (error as Error).message;
            failedNodes.push(`${nodeName}: ${message}`);
            nodes.push({ node: nodeName, params: {}, error: message });
          }
        }
        sectionItems.push({ title: sectionTitle, nodes });
      }
      groups.push({ key: groupKey, label: groupLabel, sections: sectionItems });
    }

    return {
      provider: "rosbridge",
      status: failedNodes.length > 0 ? "partial" : "success",
      message: failedNodes.length > 0 ? `部分节点读取失败，共 ${failedNodes.length} 个。` : "已读取 Nav2 / NDT 运行时参数。",
      updated_at: new Date().toISOString(),
      groups,
      failed_nodes: failedNodes,
    };
  });
}
