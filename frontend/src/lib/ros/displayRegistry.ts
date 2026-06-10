/**
 * 功能说明：
 * 维护导航测试页中“显示项”的识别规则。
 *
 * 设计目的：
 * 1. 让 RViz 风格的“按 topic 添加显示项”有统一入口。
 * 2. 根据 topic 名和消息类型推断显示类型，避免模板里堆判断。
 * 3. 后续新增 LaserScan、Marker、PointCloud2 时只扩展这里。
 */
export type NavDisplayKind = "map" | "path" | "tf" | "pose" | "pointcloud" | "laser" | "obstacle_zone" | "unknown";

export interface NavViewerDisplay {
  topic: string;
  messageType: string;
  label: string;
  kind: NavDisplayKind;
  mapOpacity?: number;
  pointSize?: number;
  hzLimit?: number;
  color?: string;
  tfShowNames?: boolean;
  tfLabelSize?: number;
  tfVisibleFrames?: string[];
}

function isCustomPointCloudMessageType(messageType: string): boolean {
  const normalized = messageType.trim().toLowerCase();
  return normalized.endsWith("/custommsg") || normalized.endsWith("/msg/custommsg");
}

export function inferDisplayKind(topic: string, messageType: string): NavDisplayKind {
  if (messageType === "sensor_msgs/msg/PointCloud2" || isCustomPointCloudMessageType(messageType)) {
    return "pointcloud";
  }
  if (messageType === "sensor_msgs/msg/LaserScan") {
    return "laser";
  }
  if (messageType === "nav_msgs/OccupancyGrid" || messageType === "nav_msgs/msg/OccupancyGrid") {
    return "map";
  }
  if (topic === "/map" || topic.endsWith("/map")) {
    return "map";
  }
  if (messageType === "nav_msgs/Path" || messageType === "nav_msgs/msg/Path") {
    return "path";
  }
  if (topic.includes("plan") || topic.endsWith("/path")) {
    return "path";
  }
  if (messageType === "tf2_msgs/TFMessage" || topic === "/tf" || topic === "/tf_static") {
    return "tf";
  }
  if (topic === "/geneox_mid360_obstacle" || topic.endsWith("/geneox_mid360_obstacle")) {
    return "obstacle_zone";
  }
  if (
    messageType === "geometry_msgs/msg/PoseWithCovarianceStamped" ||
    messageType === "geometry_msgs/msg/PoseStamped" ||
    messageType === "geometry_msgs/PoseWithCovarianceStamped" ||
    messageType === "geometry_msgs/PoseStamped"
  ) {
    return "pose";
  }
  if (topic.includes("pose") || topic.includes("amcl")) {
    return "pose";
  }
  return "unknown";
}

export function buildDisplayLabel(topic: string, kind: NavDisplayKind): string {
  if (kind === "pointcloud") {
    return `PointCloud: ${topic}`;
  }
  if (kind === "laser") {
    return `Laser: ${topic}`;
  }
  if (kind === "map") {
    return `Map: ${topic}`;
  }
  if (kind === "path") {
    return `Path: ${topic}`;
  }
  if (kind === "tf") {
    return `TF: ${topic}`;
  }
  if (kind === "pose") {
    return `Pose: ${topic}`;
  }
  if (kind === "obstacle_zone") {
    return `Obstacle Zone: ${topic}`;
  }
  return `Topic: ${topic}`;
}
