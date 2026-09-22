/**
 * 功能说明：
 * 为移动端 ROS 定位测试 APP 提供默认话题目录、主视图显示项转换和本地状态类型。
 */
import { buildDisplayLabel, inferDisplayKind, type NavViewerDisplay } from "./displayRegistry";
import type { RosTopicItem } from "../../types";

export interface MobileRosConnectionConfig {
  provider: string;
  url: string;
  rosapiService: string;
  timeoutMs: string;
  fixedFrame: string;
}

export interface MobileNavTopicOption {
  key: string;
  label: string;
  type: string;
  note: string;
}

export interface MobileNavPanelItem {
  id: string;
  title: string;
  topic: string;
  type: string;
  messageType: string;
  collapsed: boolean;
  paused: boolean;
  pointSize?: number;
  hzLimit?: number;
}

export const MOBILE_ROS_STORAGE_KEY = "moontoolbox.rosNavMobileState";

export const defaultMobileRosConnectionConfig: MobileRosConnectionConfig = {
  provider: "rosbridge",
  url: "",
  rosapiService: "/rosapi/topics_and_raw_types",
  timeoutMs: "8000",
  fixedFrame: "map",
};

export const defaultMobileTopicOptions: MobileNavTopicOption[] = [
  { key: "/map", label: "二维地图", type: "nav_msgs/OccupancyGrid", note: "常用二维栅格地图，适合直接叠加到主视图。" },
  { key: "/debug/loaded_pointcloud_map", label: "地图点云", type: "sensor_msgs/msg/PointCloud2", note: "用于和实时点云做重合验证。" },
  { key: "/points_aligned", label: "对齐结果点云", type: "sensor_msgs/msg/PointCloud2", note: "关键几何验证话题，用来看 NDT 是否真正贴图。" },
  { key: "/cloud_registered_bl", label: "NDT 输入点云", type: "sensor_msgs/msg/PointCloud2", note: "适合和 points_aligned 做对比。" },
  { key: "/cloud_registered_body", label: "FAST-LIO 输出点云", type: "sensor_msgs/msg/PointCloud2", note: "扫描链路上游点云。" },
  { key: "/ndt_pose", label: "NDT 位姿", type: "geometry_msgs/msg/PoseStamped", note: "优先用于显示定位箭头。" },
  { key: "/odometry/filtered", label: "融合里程计", type: "nav_msgs/msg/Odometry", note: "查看导航运动和位姿连续性。" },
  { key: "/plan", label: "当前路径", type: "nav_msgs/msg/Path", note: "常规路径叠加项。" },
  { key: "/tf", label: "TF 树", type: "tf2_msgs/msg/TFMessage", note: "查看 base_link 与地图坐标系链路。" },
  { key: "/scan", label: "LaserScan", type: "sensor_msgs/msg/LaserScan", note: "查看局部避障输入。" },
  { key: "/geneox_mid360_obstacle", label: "冷静区/危险区", type: "std_msgs/msg/UInt8", note: "绑定定位位姿绘制风险区。" },
  { key: "/ndt_status", label: "NDT 状态", type: "std_msgs/msg/UInt8", note: "0 unknown / 1 healthy / 2 degraded / 3 lost。" },
  { key: "/iteration_num", label: "NDT 迭代数", type: "autoware_internal_debug_msgs/msg/Int32Stamped", note: "判断是否接近失配或吃满迭代。" },
  { key: "/exe_time_ms", label: "NDT 耗时", type: "autoware_internal_debug_msgs/msg/Float32Stamped", note: "判断环境复杂度和性能抖动。" },
  { key: "/ndt_score", label: "NDT 评分", type: "std_msgs/msg/Float32", note: "适合趋势显示和失配预警。" },
  { key: "/fastlio_ndt_observation_debug", label: "NDT 观测调试", type: "std_msgs/msg/String", note: "字符串 JSON，重点关注 sigma_xy 和 sigma_yaw。" },
  { key: "/nav2_status", label: "Nav2 状态汇总", type: "std_msgs/msg/String", note: "字符串 JSON，总状态看板核心话题。" },
  { key: "/nav2_goal_context", label: "导航任务上下文", type: "std_msgs/msg/String", note: "字符串 JSON，适合看 active / paused / request_planid。" },
  { key: "/cmd_vel", label: "控制输出", type: "geometry_msgs/msg/Twist", note: "判断 Nav2 是否真的在输出控制指令。" },
];

function defaultMainDisplayColor(topic: string, kind: NavViewerDisplay["kind"]) {
  if (kind === "path") {
    return "#d7b265";
  }
  if (kind === "pose") {
    if (topic.includes("ekf")) {
      return "#8ca8b8";
    }
    if (topic.includes("ndt")) {
      return "#f0d5a3";
    }
    return "#b88b5a";
  }
  if (topic.includes("loaded_pointcloud_map")) {
    return "#d7d1c6";
  }
  if (topic.includes("points_aligned")) {
    return "#cfc09d";
  }
  if (topic.includes("cloud_registered_bl")) {
    return "#8f9f96";
  }
  if (topic.includes("cloud_registered_body")) {
    return "#b89574";
  }
  return "#ddd4c6";
}

export function mapTopicItemToMobileOption(topic: RosTopicItem): MobileNavTopicOption {
  const defaultMatch = defaultMobileTopicOptions.find((item) => item.key === topic.name);
  return {
    key: topic.name,
    label: defaultMatch?.label || topic.name.split("/").filter(Boolean).pop() || topic.name,
    type: topic.type || defaultMatch?.type || "",
    note: defaultMatch?.note || "来自机器人实时 ROS 话题列表。",
  };
}

export function mergeMobileTopicOptions(nextTopics: MobileNavTopicOption[]) {
  const merged = new Map<string, MobileNavTopicOption>();
  defaultMobileTopicOptions.forEach((topic) => {
    merged.set(topic.key, topic);
  });
  nextTopics.forEach((topic) => {
    const current = merged.get(topic.key);
    merged.set(topic.key, {
      key: topic.key,
      label: topic.label || current?.label || topic.key,
      type: topic.type || current?.type || "",
      note: current?.note || topic.note || "来自机器人实时 ROS 话题列表。",
    });
  });
  return [...merged.values()].sort((left, right) => {
    const leftIsDefault = defaultMobileTopicOptions.some((topic) => topic.key === left.key);
    const rightIsDefault = defaultMobileTopicOptions.some((topic) => topic.key === right.key);
    if (leftIsDefault !== rightIsDefault) {
      return leftIsDefault ? -1 : 1;
    }
    return left.key.localeCompare(right.key, "zh-CN");
  });
}

export function topicOptionToMobileDisplay(option: MobileNavTopicOption): NavViewerDisplay {
  const kind = inferDisplayKind(option.key, option.type);
  return {
    topic: option.key,
    messageType: option.type,
    kind,
    label: buildDisplayLabel(option.key, kind),
    color: defaultMainDisplayColor(option.key, kind),
    pointSize: kind === "pointcloud" ? 0.08 : undefined,
    hzLimit: kind === "pointcloud" ? 5 : undefined,
    mapOpacity: kind === "map" ? 0.55 : undefined,
    tfShowNames: kind === "tf" ? true : undefined,
    tfLabelSize: kind === "tf" ? 0.5 : undefined,
    tfVisibleFrames: kind === "tf" ? ["base_link", "body"] : undefined,
  };
}

export function createMobileDetailPanel(option: MobileNavTopicOption): MobileNavPanelItem {
  const isPointCloudTopic = option.type === "sensor_msgs/msg/PointCloud2";
  return {
    id: `mobile-panel-${option.key.replace(/[^a-z0-9]+/gi, "-").replace(/^-+|-+$/g, "")}`,
    title: option.label,
    topic: option.key,
    type: "详情卡片",
    messageType: option.type,
    collapsed: false,
    paused: false,
    pointSize: isPointCloudTopic ? 2.5 : undefined,
    hzLimit: isPointCloudTopic ? 5 : undefined,
  };
}
