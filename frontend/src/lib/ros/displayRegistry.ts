/**
 * 功能说明：
 * 维护导航测试页中“显示项”的识别规则。
 *
 * 设计目的：
 * 1. 让 RViz 风格的“按 topic 添加显示项”有统一入口。
 * 2. 根据 topic 名和消息类型推断显示类型，避免模板里堆判断。
 * 3. 后续新增 LaserScan、Marker、PointCloud2 时只扩展这里。
 */
export type NavDisplayKind =
  | "map"
  | "path"
  | "tf"
  | "pose"
  | "pose_array"
  | "pointcloud"
  | "laser"
  | "marker"
  | "bspline"
  | "twist"
  | "obstacle_zone"
  | "unknown";

export interface NavViewerDisplay {
  topic: string;
  messageType: string;
  label: string;
  kind: NavDisplayKind;
  mapOpacity?: number;
  pointSize?: number;
  pointEmissiveIntensity?: number;
  hzLimit?: number;
  pointColorMode?: "solid" | "layered";
  color?: string;
  tfShowNames?: boolean;
  tfLabelSize?: number;
  tfVisibleFrames?: string[];
}

function normalizeMessageType(messageType: string): string {
  return messageType.trim().toLowerCase();
}

function messageTypeMatches(
  messageType: string,
  ...candidates: string[]
): boolean {
  const normalized = normalizeMessageType(messageType);
  return candidates.some((candidate) => normalized === candidate.toLowerCase());
}

function isCustomPointCloudMessageType(messageType: string): boolean {
  const normalized = normalizeMessageType(messageType);
  return (
    normalized.endsWith("/custommsg") || normalized.endsWith("/msg/custommsg")
  );
}

export function isPointCloudMessageType(messageType: string): boolean {
  return (
    messageTypeMatches(
      messageType,
      "sensor_msgs/msg/PointCloud2",
      "sensor_msgs/PointCloud2",
    ) || isCustomPointCloudMessageType(messageType)
  );
}

export function inferDisplayKind(
  topic: string,
  messageType: string,
): NavDisplayKind {
  if (isPointCloudMessageType(messageType)) {
    return "pointcloud";
  }
  if (
    messageTypeMatches(
      messageType,
      "sensor_msgs/msg/LaserScan",
      "sensor_msgs/LaserScan",
    )
  ) {
    return "laser";
  }
  if (
    messageTypeMatches(
      messageType,
      "visualization_msgs/msg/Marker",
      "visualization_msgs/Marker",
    )
  ) {
    return "marker";
  }
  if (
    messageTypeMatches(
      messageType,
      "scan_planner_msgs/msg/Bspline",
      "scan_planner_msgs/Bspline",
    )
  ) {
    return "bspline";
  }
  if (
    messageTypeMatches(
      messageType,
      "geometry_msgs/msg/Twist",
      "geometry_msgs/Twist",
    )
  ) {
    return "twist";
  }
  if (
    messageTypeMatches(
      messageType,
      "nav_msgs/OccupancyGrid",
      "nav_msgs/msg/OccupancyGrid",
    )
  ) {
    return "map";
  }
  if (topic === "/map" || topic.endsWith("/map")) {
    return "map";
  }
  if (messageTypeMatches(messageType, "nav_msgs/Path", "nav_msgs/msg/Path")) {
    return "path";
  }
  if (topic.includes("plan") || topic.endsWith("/path")) {
    return "path";
  }
  if (
    messageTypeMatches(
      messageType,
      "tf2_msgs/TFMessage",
      "tf2_msgs/msg/TFMessage",
    ) ||
    topic === "/tf" ||
    topic === "/tf_static"
  ) {
    return "tf";
  }
  if (
    topic === "/geneox_mid360_obstacle" ||
    topic.endsWith("/geneox_mid360_obstacle")
  ) {
    return "obstacle_zone";
  }
  if (
    messageTypeMatches(
      messageType,
      "geometry_msgs/msg/PoseArray",
      "geometry_msgs/PoseArray",
    )
  ) {
    return "pose_array";
  }
  if (
    messageTypeMatches(
      messageType,
      "geometry_msgs/msg/PoseWithCovarianceStamped",
      "geometry_msgs/msg/PoseStamped",
      "nav_msgs/msg/Odometry",
      "nav_msgs/Odometry",
      "geometry_msgs/PoseWithCovarianceStamped",
      "geometry_msgs/PoseStamped",
    )
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
  if (kind === "marker") {
    return `Marker: ${topic}`;
  }
  if (kind === "bspline") {
    return `Bspline: ${topic}`;
  }
  if (kind === "twist") {
    return `Twist: ${topic}`;
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
  if (kind === "pose_array") {
    return `PoseArray: ${topic}`;
  }
  if (kind === "obstacle_zone") {
    return `Obstacle Zone: ${topic}`;
  }
  return `Topic: ${topic}`;
}
