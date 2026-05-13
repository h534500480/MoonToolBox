<!-- 功能说明：导航测试页可折叠诊断小窗列表，按话题类型显示趋势线、状态卡片和关键指标。 -->
<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";

import { saveNavRecording } from "../api/client";
import { createRosLiveAdapter } from "../lib/ros/liveAdapter";

interface NavPanelItem {
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

interface MetricSeries {
  label: string;
  unit: string;
  color: string;
  values: number[];
}

interface StatusBadge {
  label: string;
  value: string;
  tone: "neutral" | "success" | "warning" | "danger";
}

interface KeyValueItem {
  key: string;
  value: string;
}

interface PointCloudPreviewPoint {
  x: number;
  y: number;
}

interface PointCloudPreview {
  totalPoints: number;
  samplePoints: number;
  dots: PointCloudPreviewPoint[];
}

interface ImuPreviewVector {
  x: number;
  y: number;
}

interface ImuPreview {
  forwardLine: string;
  forwardHead: string;
  leftLine: string;
  upLine: string;
  frontLabel: ImuPreviewVector;
  motionLevel: number;
  orientationSource: "quaternion" | "integrated_gyro" | "acceleration";
}

interface ImuPoseState {
  roll: number;
  pitch: number;
  yaw: number;
  lastStampMs: number;
}

interface PanelState {
  summary: string;
  pretty: string;
  updatedAt: string;
  chartTitle: string;
  metricSeries: MetricSeries[];
  badges: StatusBadge[];
  keyValues: KeyValueItem[];
  pointCloudPreview: PointCloudPreview | null;
  imuPreview: ImuPreview | null;
}

interface RecordedMetricPoint {
  offsetMs: number;
  value: number;
}

interface RecordedMetricSeries {
  label: string;
  unit: string;
  color: string;
  samples: RecordedMetricPoint[];
}

interface PanelRecordingState {
  isRecording: boolean;
  startedAtMs: number;
  startedAtText: string;
  stoppedAtText: string;
  durationMs: number;
  entries: string[];
  metricSeries: RecordedMetricSeries[];
}

const props = defineProps<{
  provider: string;
  url: string;
  timeoutMs: number;
  panels: NavPanelItem[];
  compact?: boolean;
}>();

const emit = defineEmits<{
  toggle: [panelId: string];
  remove: [panelId: string];
  updateConfig: [panelId: string, patch: Partial<NavPanelItem>];
  recordingSaved: [];
}>();

const panelStateMap = ref<Record<string, PanelState>>({});
const adapterState = ref("未连接");
const isAdapterConnected = ref(false);
let adapter: ReturnType<typeof createRosLiveAdapter> | null = null;
const unsubscribeMap = new Map<string, () => void>();
const lastMessageTimeMap = new Map<string, number>();
const panelRecordingMap = ref<Record<string, PanelRecordingState>>({});
const imuPoseStateMap = ref<Record<string, ImuPoseState>>({});
const compactMetricSelectionMap = ref<Record<string, string>>({});
const maxHistoryLength = 80;
const maxRecordedEntries = 120;

const activePanels = computed(() => props.panels.filter((panel) => !panel.collapsed && !panel.paused));

function formatTimestamp() {
  return new Date().toLocaleTimeString("zh-CN", { hour12: false });
}

function formatTimestampWithMs(timeMs: number) {
  return new Date(timeMs).toLocaleTimeString("zh-CN", {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    fractionalSecondDigits: 3,
  });
}

function isPointCloudPanel(panel: NavPanelItem) {
  return panel.messageType === "sensor_msgs/msg/PointCloud2";
}

function isImuPanel(panel: NavPanelItem) {
  return panel.messageType === "sensor_msgs/msg/Imu";
}

function safeNumber(value: unknown) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function safeHzLimit(panel: NavPanelItem) {
  const value = Number(panel.hzLimit ?? 0);
  return Number.isFinite(value) && value > 0 ? value : 0;
}

function normalizePointSize(panel: NavPanelItem) {
  const value = Number(panel.pointSize ?? 2.5);
  if (!Number.isFinite(value)) {
    return 2.5;
  }
  return Math.min(8, Math.max(0.8, value));
}

function ndtStatusLabel(value: number) {
  if (value === 1) {
    return "healthy";
  }
  if (value === 2) {
    return "degraded";
  }
  if (value === 3) {
    return "lost";
  }
  return "unknown";
}

function toneForBoolean(value: boolean | null | undefined): "neutral" | "success" | "warning" | "danger" {
  if (value === true) {
    return "success";
  }
  if (value === false) {
    return "warning";
  }
  return "neutral";
}

function toneForStatusText(value: string) {
  const normalized = value.toLowerCase();
  if (normalized.includes("healthy") || normalized.includes("ready") || normalized.includes("success")) {
    return "success" as const;
  }
  if (normalized.includes("degraded") || normalized.includes("pause") || normalized.includes("wait")) {
    return "warning" as const;
  }
  if (normalized.includes("lost") || normalized.includes("fail") || normalized.includes("error")) {
    return "danger" as const;
  }
  return "neutral" as const;
}

function tryParseJsonString(raw: string) {
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function formatNumber(value: number | null, digits = 3) {
  if (value === null) {
    return "-";
  }
  return value.toFixed(digits);
}

function appendValue(values: number[], next: number | null) {
  if (next === null) {
    return values;
  }
  const merged = [...values, next];
  return merged.length > maxHistoryLength ? merged.slice(-maxHistoryLength) : merged;
}

function createMetricSeries(label: string, unit: string, color: string, next: number | null, previous?: MetricSeries) {
  return {
    label,
    unit,
    color,
    values: appendValue(previous?.values ?? [], next),
  };
}

function normalizePointCloudBytes(data: unknown): Uint8Array | null {
  if (data instanceof Uint8Array) {
    return data;
  }
  if (Array.isArray(data)) {
    return Uint8Array.from(data.map((item) => Number(item) & 0xff));
  }
  if (typeof data === "string") {
    const binary = window.atob(data);
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) {
      bytes[index] = binary.charCodeAt(index);
    }
    return bytes;
  }
  return null;
}

function resolveFieldOffset(fields: any[], fieldName: string) {
  const match = fields.find((field) => field?.name === fieldName);
  return typeof match?.offset === "number" ? match.offset : -1;
}

function buildPointCloudPreview(message: any): PointCloudPreview | null {
  const fields = Array.isArray(message?.fields) ? message.fields : [];
  const pointStep = Number(message?.point_step ?? 0);
  const width = Number(message?.width ?? 0);
  const height = Number(message?.height ?? 1);
  const bytes = normalizePointCloudBytes(message?.data);
  if (pointStep <= 0 || width <= 0 || !bytes || bytes.byteLength < pointStep) {
    return null;
  }

  const xOffset = resolveFieldOffset(fields, "x");
  const yOffset = resolveFieldOffset(fields, "y");
  if (xOffset < 0 || yOffset < 0) {
    return null;
  }

  const totalPoints = width * Math.max(1, height);
  const sampleStep = Math.max(1, Math.ceil(totalPoints / 180));
  const rawPoints: Array<{ x: number; y: number }> = [];
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);

  for (let index = 0; index < totalPoints; index += sampleStep) {
    const base = index * pointStep;
    if (base + pointStep > bytes.byteLength) {
      break;
    }

    const x = view.getFloat32(base + xOffset, true);
    const y = view.getFloat32(base + yOffset, true);
    if (!Number.isFinite(x) || !Number.isFinite(y)) {
      continue;
    }
    rawPoints.push({ x, y });
  }

  if (rawPoints.length === 0) {
    return null;
  }

  const minX = Math.min(...rawPoints.map((point) => point.x));
  const maxX = Math.max(...rawPoints.map((point) => point.x));
  const minY = Math.min(...rawPoints.map((point) => point.y));
  const maxY = Math.max(...rawPoints.map((point) => point.y));
  const spanX = Math.max(1e-6, maxX - minX);
  const spanY = Math.max(1e-6, maxY - minY);

  return {
    totalPoints,
    samplePoints: rawPoints.length,
    dots: rawPoints.map((point) => ({
      x: 8 + ((point.x - minX) / spanX) * 84,
      y: 92 - ((point.y - minY) / spanY) * 84,
    })),
  };
}

function vectorLength3d(x: number, y: number, z: number) {
  return Math.sqrt((x * x) + (y * y) + (z * z));
}

function normalizeVector3d(x: number, y: number, z: number) {
  const length = vectorLength3d(x, y, z);
  if (length < 1e-6) {
    return null;
  }
  return {
    x: x / length,
    y: y / length,
    z: z / length,
  };
}

function rotateVectorByQuaternion(
  vector: { x: number; y: number; z: number },
  quaternion: { x: number; y: number; z: number; w: number }
) {
  const { x, y, z, w } = quaternion;
  const uvx = (y * vector.z) - (z * vector.y);
  const uvy = (z * vector.x) - (x * vector.z);
  const uvz = (x * vector.y) - (y * vector.x);
  const uuvx = (y * uvz) - (z * uvy);
  const uuvy = (z * uvx) - (x * uvz);
  const uuvz = (x * uvy) - (y * uvx);
  return {
    x: vector.x + (2 * ((uvx * w) + uuvx)),
    y: vector.y + (2 * ((uvy * w) + uuvy)),
    z: vector.z + (2 * ((uvz * w) + uuvz)),
  };
}

function projectPreviewVector3d(x: number, y: number, z: number): ImuPreviewVector {
  return {
    x: 72 + (x * 34) - (y * 24),
    y: 72 - (z * 34) + (y * 18),
  };
}

function buildPreviewLine(origin: ImuPreviewVector, target: ImuPreviewVector) {
  return `${origin.x.toFixed(2)},${origin.y.toFixed(2)} ${target.x.toFixed(2)},${target.y.toFixed(2)}`;
}

function buildPreviewArrowHead(origin: ImuPreviewVector, target: ImuPreviewVector) {
  const lineDx = target.x - origin.x;
  const lineDy = target.y - origin.y;
  const lineLength = Math.max(1, Math.sqrt((lineDx * lineDx) + (lineDy * lineDy)));
  const unitDx = lineDx / lineLength;
  const unitDy = lineDy / lineLength;
  const headSize = 7;
  const leftX = target.x - (unitDx * headSize) - (unitDy * 4.5);
  const leftY = target.y - (unitDy * headSize) + (unitDx * 4.5);
  const rightX = target.x - (unitDx * headSize) + (unitDy * 4.5);
  const rightY = target.y - (unitDy * headSize) - (unitDx * 4.5);
  return `${target.x.toFixed(2)},${target.y.toFixed(2)} ${leftX.toFixed(2)},${leftY.toFixed(2)} ${rightX.toFixed(2)},${rightY.toFixed(2)}`;
}

function extractMessageStampMs(message: any) {
  const sec = safeNumber(message?.header?.stamp?.sec ?? message?.header?.stamp?.secs ?? message?.header?.stamp_sec);
  const nanosec = safeNumber(message?.header?.stamp?.nanosec ?? message?.header?.stamp?.nsecs ?? message?.header?.stamp_nanosec) ?? 0;
  if (sec === null) {
    return Date.now();
  }
  return (sec * 1000) + (nanosec / 1_000_000);
}

function quaternionToEuler(x: number, y: number, z: number, w: number) {
  const sinrCosp = 2 * ((w * x) + (y * z));
  const cosrCosp = 1 - (2 * ((x * x) + (y * y)));
  const roll = Math.atan2(sinrCosp, cosrCosp);

  const sinp = 2 * ((w * y) - (z * x));
  const pitch = Math.abs(sinp) >= 1 ? Math.sign(sinp) * (Math.PI / 2) : Math.asin(sinp);

  const sinyCosp = 2 * ((w * z) + (x * y));
  const cosyCosp = 1 - (2 * ((y * y) + (z * z)));
  const yaw = Math.atan2(sinyCosp, cosyCosp);

  return { roll, pitch, yaw };
}

function hasUsableImuOrientation(message: any, quaternionNorm: number) {
  const covariance = Array.isArray(message?.orientation_covariance) ? message.orientation_covariance : [];
  const covariance0 = safeNumber(covariance[0]);
  if (covariance0 === -1) {
    return false;
  }
  return quaternionNorm > 0.5 && quaternionNorm < 1.5;
}

function rotateVectorByEuler(
  vector: { x: number; y: number; z: number },
  pose: { roll: number; pitch: number; yaw: number }
) {
  const cosRoll = Math.cos(pose.roll);
  const sinRoll = Math.sin(pose.roll);
  const cosPitch = Math.cos(pose.pitch);
  const sinPitch = Math.sin(pose.pitch);
  const cosYaw = Math.cos(pose.yaw);
  const sinYaw = Math.sin(pose.yaw);

  const m00 = cosYaw * cosPitch;
  const m01 = (cosYaw * sinPitch * sinRoll) - (sinYaw * cosRoll);
  const m02 = (cosYaw * sinPitch * cosRoll) + (sinYaw * sinRoll);
  const m10 = sinYaw * cosPitch;
  const m11 = (sinYaw * sinPitch * sinRoll) + (cosYaw * cosRoll);
  const m12 = (sinYaw * sinPitch * cosRoll) - (cosYaw * sinRoll);
  const m20 = -sinPitch;
  const m21 = cosPitch * sinRoll;
  const m22 = cosPitch * cosRoll;

  return {
    x: (m00 * vector.x) + (m01 * vector.y) + (m02 * vector.z),
    y: (m10 * vector.x) + (m11 * vector.y) + (m12 * vector.z),
    z: (m20 * vector.x) + (m21 * vector.y) + (m22 * vector.z),
  };
}

function buildImuPreview(panelId: string, message: any): ImuPreview | null {
  const orientationX = safeNumber(message?.orientation?.x) ?? 0;
  const orientationY = safeNumber(message?.orientation?.y) ?? 0;
  const orientationZ = safeNumber(message?.orientation?.z) ?? 0;
  const orientationW = safeNumber(message?.orientation?.w) ?? 0;
  const quaternionNorm = Math.sqrt((orientationX * orientationX) + (orientationY * orientationY) + (orientationZ * orientationZ) + (orientationW * orientationW));

  const accelX = safeNumber(message?.linear_acceleration?.x) ?? 0;
  const accelY = safeNumber(message?.linear_acceleration?.y) ?? 0;
  const accelZ = safeNumber(message?.linear_acceleration?.z) ?? 0;
  const gyroX = safeNumber(message?.angular_velocity?.x) ?? 0;
  const gyroY = safeNumber(message?.angular_velocity?.y) ?? 0;
  const gyroZ = safeNumber(message?.angular_velocity?.z) ?? 0;
  const stampMs = extractMessageStampMs(message);

  let forwardVector = normalizeVector3d(accelX, accelY, accelZ);
  let leftVector = forwardVector ? normalizeVector3d(-forwardVector.y, forwardVector.x, 0) : null;
  let upVector = normalizeVector3d(0, 0, 1);
  let orientationSource: "quaternion" | "integrated_gyro" | "acceleration" = "acceleration";

  if (hasUsableImuOrientation(message, quaternionNorm)) {
    const normalizedQuaternion = {
      x: orientationX / quaternionNorm,
      y: orientationY / quaternionNorm,
      z: orientationZ / quaternionNorm,
      w: orientationW / quaternionNorm,
    };
    const rotatedForward = rotateVectorByQuaternion({ x: 1, y: 0, z: 0 }, normalizedQuaternion);
    const rotatedLeft = rotateVectorByQuaternion({ x: 0, y: 1, z: 0 }, normalizedQuaternion);
    const rotatedUp = rotateVectorByQuaternion({ x: 0, y: 0, z: 1 }, normalizedQuaternion);
    forwardVector = normalizeVector3d(rotatedForward.x, rotatedForward.y, rotatedForward.z);
    leftVector = normalizeVector3d(rotatedLeft.x, rotatedLeft.y, rotatedLeft.z);
    upVector = normalizeVector3d(rotatedUp.x, rotatedUp.y, rotatedUp.z);
    imuPoseStateMap.value = {
      ...imuPoseStateMap.value,
      [panelId]: {
        ...quaternionToEuler(normalizedQuaternion.x, normalizedQuaternion.y, normalizedQuaternion.z, normalizedQuaternion.w),
        lastStampMs: stampMs,
      },
    };
    orientationSource = "quaternion";
  } else {
    const previousPose = imuPoseStateMap.value[panelId] ?? {
      roll: 0,
      pitch: 0,
      yaw: 0,
      lastStampMs: stampMs,
    };
    const dt = Math.max(0, Math.min(0.2, (stampMs - previousPose.lastStampMs) / 1000));
    const nextPose = {
      roll: previousPose.roll + (gyroX * dt),
      pitch: previousPose.pitch + (gyroY * dt),
      yaw: previousPose.yaw + (gyroZ * dt),
      lastStampMs: stampMs,
    };
    imuPoseStateMap.value = {
      ...imuPoseStateMap.value,
      [panelId]: nextPose,
    };

    if (dt > 0 || Math.abs(gyroX) > 1e-4 || Math.abs(gyroY) > 1e-4 || Math.abs(gyroZ) > 1e-4) {
      const rotatedForward = rotateVectorByEuler({ x: 1, y: 0, z: 0 }, nextPose);
      const rotatedLeft = rotateVectorByEuler({ x: 0, y: 1, z: 0 }, nextPose);
      const rotatedUp = rotateVectorByEuler({ x: 0, y: 0, z: 1 }, nextPose);
      forwardVector = normalizeVector3d(rotatedForward.x, rotatedForward.y, rotatedForward.z) ?? forwardVector;
      leftVector = normalizeVector3d(rotatedLeft.x, rotatedLeft.y, rotatedLeft.z) ?? leftVector;
      upVector = normalizeVector3d(rotatedUp.x, rotatedUp.y, rotatedUp.z) ?? upVector;
      orientationSource = "integrated_gyro";
    }
  }

  if (!forwardVector) {
    forwardVector = { x: 1, y: 0, z: 0 };
  }
  if (!leftVector) {
    leftVector = { x: 0, y: 1, z: 0 };
  }
  if (!upVector) {
    upVector = { x: 0, y: 0, z: 1 };
  }

  const accelMagnitude = vectorLength3d(accelX, accelY, accelZ);
  const gyroMagnitude = vectorLength3d(gyroX, gyroY, gyroZ);
  const planarAccelMagnitude = Math.sqrt((accelX * accelX) + (accelY * accelY));
  const verticalAccelDelta = Math.abs(Math.abs(accelZ) - 9.81);
  const motionLevel = Math.min(1, Math.max(
    planarAccelMagnitude / 2.2,
    verticalAccelDelta / 4,
    Math.abs(accelMagnitude - 9.81) / 5,
    gyroMagnitude / 2.5
  ));
  const axisLength = 24;
  const forwardLength = axisLength + (motionLevel * 12);

  const origin = { x: 72, y: 72 };
  const forwardTip = projectPreviewVector3d(
    forwardVector.x * (forwardLength / 34),
    forwardVector.y * (forwardLength / 34),
    forwardVector.z * (forwardLength / 34)
  );
  const leftTip = projectPreviewVector3d(
    leftVector.x * (axisLength / 34),
    leftVector.y * (axisLength / 34),
    leftVector.z * (axisLength / 34)
  );
  const upTip = projectPreviewVector3d(
    upVector.x * (axisLength / 34),
    upVector.y * (axisLength / 34),
    upVector.z * (axisLength / 34)
  );
  const frontLabel = projectPreviewVector3d(
    forwardVector.x * 1.08,
    forwardVector.y * 1.08,
    forwardVector.z * 1.08
  );

  return {
    forwardLine: buildPreviewLine(origin, forwardTip),
    forwardHead: buildPreviewArrowHead(origin, forwardTip),
    leftLine: buildPreviewLine(origin, leftTip),
    upLine: buildPreviewLine(origin, upTip),
    frontLabel,
    motionLevel,
    orientationSource,
  };
}

function prettyMessage(message: any) {
  if (Array.isArray(message?.fields) && message?.data) {
    return JSON.stringify(
      {
        header: message.header ?? {},
        width: message.width ?? 0,
        height: message.height ?? 0,
        point_step: message.point_step ?? 0,
        row_step: message.row_step ?? 0,
        is_dense: message.is_dense ?? false,
        fields: message.fields,
      },
      null,
      2
    );
  }
  if (typeof message?.data === "string") {
    const parsed = tryParseJsonString(message.data);
    if (parsed) {
      return JSON.stringify(parsed, null, 2);
    }
  }
  return JSON.stringify(message, null, 2);
}

function buildDefaultState(topic: string): PanelState {
  return {
    summary: `等待 ${topic} 消息`,
    pretty: "等待消息",
    updatedAt: "-",
    chartTitle: "趋势",
    metricSeries: [],
    badges: [],
    keyValues: [],
    pointCloudPreview: null,
    imuPreview: null,
  };
}

function buildDefaultRecordingState(): PanelRecordingState {
  return {
    isRecording: false,
    startedAtMs: 0,
    startedAtText: "-",
    stoppedAtText: "-",
    durationMs: 0,
    entries: [],
    metricSeries: [],
  };
}

function summarizeMessage(panel: NavPanelItem, message: any) {
  const topic = panel.topic;
  if (topic === "/ndt_status") {
    const statusValue = Number(message?.data ?? 0);
    return `NDT 状态: ${ndtStatusLabel(statusValue)} (${statusValue})`;
  }
  if (topic === "/iteration_num" || topic === "/exe_time_ms" || topic === "/ndt_score") {
    return `${topic}: ${message?.data ?? "-"}`;
  }
  if (isPointCloudPanel(panel)) {
    const totalPoints = Number(message?.width ?? 0) * Math.max(1, Number(message?.height ?? 1));
    return `${topic}: 点云 ${totalPoints || 0} 点`;
  }
  if (isImuPanel(panel)) {
    const accelX = safeNumber(message?.linear_acceleration?.x);
    const accelY = safeNumber(message?.linear_acceleration?.y);
    const accelZ = safeNumber(message?.linear_acceleration?.z);
    const gyroZ = safeNumber(message?.angular_velocity?.z);
    return `IMU accel=(${formatNumber(accelX, 2)}, ${formatNumber(accelY, 2)}, ${formatNumber(accelZ, 2)}) / gyro_z=${formatNumber(gyroZ, 2)}`;
  }
  if (typeof message?.data === "string") {
    const parsed = tryParseJsonString(message.data);
    if (topic === "/nav2_status" && parsed) {
      return `state=${parsed.state ?? "-"} / ready=${parsed.ready_for_next_goal ?? "-"} / localization=${parsed.localization_status ?? "-"}`;
    }
    if (topic === "/nav2_goal_context" && parsed) {
      return `active=${parsed.active ?? "-"} / paused_by_user=${parsed.paused_by_user ?? "-"} / request_planid=${parsed.request_planid ?? "-"}`;
    }
    if (topic === "/fastlio_ndt_observation_debug" && parsed) {
      return `sigma_xy=${parsed.sigma_xy_m ?? "-"} / sigma_yaw=${parsed.sigma_yaw_deg ?? "-"} / planar_dist=${parsed.planar_dist_before_m ?? "-"} / z_err=${parsed.z_err_before_m ?? parsed.z_err ?? "-"}`;
    }
    return message.data;
  }
  return `${topic} 已收到消息`;
}

function buildPanelVisualization(panel: NavPanelItem, message: any, previous?: PanelState): Omit<PanelState, "summary" | "pretty" | "updatedAt"> {
  const topic = panel.topic;

  if (topic === "/ndt_status") {
    const current = safeNumber(message?.data);
    const label = ndtStatusLabel(current ?? 0);
    return {
      chartTitle: "状态趋势",
      metricSeries: [
        createMetricSeries("status", "", "#31d28a", current, previous?.metricSeries.find((item) => item.label === "status")),
      ],
      badges: [
        { label: "NDT", value: label, tone: toneForStatusText(label) },
      ],
      keyValues: [
        { key: "当前值", value: current === null ? "-" : `${current}` },
      ],
      pointCloudPreview: null,
      imuPreview: null,
    };
  }

  if (topic === "/iteration_num" || topic === "/exe_time_ms" || topic === "/ndt_score") {
    const current = safeNumber(message?.data);
    const unit = topic === "/iteration_num" ? "count" : topic === "/exe_time_ms" ? "ms" : "score";
    const color = topic === "/iteration_num" ? "#2f8cff" : topic === "/exe_time_ms" ? "#f6a237" : "#31d28a";
    const label = topic === "/iteration_num" ? "iter" : topic === "/exe_time_ms" ? "delay" : "score";
    return {
      chartTitle: "单指标趋势",
      metricSeries: [
        createMetricSeries(label, unit, color, current, previous?.metricSeries[0]),
      ],
      badges: [],
      keyValues: [
        { key: "当前值", value: current === null ? "-" : `${current}` },
        { key: "单位", value: unit },
      ],
      pointCloudPreview: null,
      imuPreview: null,
    };
  }

  if (topic === "/fastlio_ndt_observation_debug" && typeof message?.data === "string") {
    const parsed = tryParseJsonString(message.data) ?? {};
    const sigmaXy = safeNumber(parsed.sigma_xy_m);
    const sigmaYaw = safeNumber(parsed.sigma_yaw_deg);
    const planarDist = safeNumber(parsed.planar_dist_before_m);
    const zErrBefore = safeNumber(parsed.z_err_before_m ?? parsed.z_err);
    const travel = safeNumber(parsed.travel);
    return {
      chartTitle: "观测质量趋势",
      metricSeries: [
        createMetricSeries("sigma_xy", "m", "#31d28a", sigmaXy, previous?.metricSeries.find((item) => item.label === "sigma_xy")),
        createMetricSeries("sigma_yaw", "deg", "#f6a237", sigmaYaw, previous?.metricSeries.find((item) => item.label === "sigma_yaw")),
        createMetricSeries("planar_dist", "m", "#f15d78", planarDist, previous?.metricSeries.find((item) => item.label === "planar_dist")),
        createMetricSeries("z_err_before", "m", "#8a63ff", zErrBefore, previous?.metricSeries.find((item) => item.label === "z_err_before")),
      ],
      badges: [
        { label: "sigma_xy", value: formatNumber(sigmaXy), tone: sigmaXy !== null && sigmaXy < 0.25 ? "success" : "warning" },
        { label: "sigma_yaw", value: formatNumber(sigmaYaw, 2), tone: sigmaYaw !== null && sigmaYaw < 8 ? "success" : "warning" },
        { label: "planar", value: formatNumber(planarDist, 2), tone: planarDist !== null && planarDist < 0.35 ? "success" : "warning" },
        { label: "z_err", value: formatNumber(zErrBefore, 2), tone: zErrBefore !== null && Math.abs(zErrBefore) < 0.2 ? "success" : "warning" },
      ],
      keyValues: [
        { key: "z_err_before_m", value: formatNumber(zErrBefore, 3) },
        { key: "travel", value: formatNumber(travel, 3) },
      ],
      pointCloudPreview: null,
      imuPreview: null,
    };
  }

  if (topic === "/nav2_status" && typeof message?.data === "string") {
    const parsed = tryParseJsonString(message.data) ?? {};
    const speed = safeNumber(parsed.robot_speed_mps);
    const cmdVelNorm = safeNumber(parsed.cmd_vel_norm);
    const distanceRemaining = safeNumber(parsed.distance_remaining);
    return {
      chartTitle: "导航运行趋势",
      metricSeries: [
        createMetricSeries("speed", "mps", "#2f8cff", speed, previous?.metricSeries.find((item) => item.label === "speed")),
        createMetricSeries("cmd_norm", "", "#31d28a", cmdVelNorm, previous?.metricSeries.find((item) => item.label === "cmd_norm")),
        createMetricSeries("distance", "m", "#f6a237", distanceRemaining, previous?.metricSeries.find((item) => item.label === "distance")),
      ],
      badges: [
        { label: "state", value: String(parsed.state ?? "-"), tone: toneForStatusText(String(parsed.state ?? "")) },
        { label: "ready", value: String(parsed.ready_for_next_goal ?? "-"), tone: toneForBoolean(parsed.ready_for_next_goal) },
        { label: "loc", value: String(parsed.localization_status ?? "-"), tone: toneForStatusText(String(parsed.localization_status ?? "")) },
        { label: "obstacle", value: String(parsed.obstacle_state_text ?? "-"), tone: toneForStatusText(String(parsed.obstacle_state_text ?? "")) },
      ],
      keyValues: [
        { key: "recoveries", value: String(parsed.number_of_recoveries ?? "-") },
        { key: "plan_fresh", value: String(parsed.plan_fresh ?? "-") },
        { key: "scan_fresh", value: String(parsed.scan_fresh ?? "-") },
        { key: "odom_fresh", value: String(parsed.odom_fresh ?? "-") },
      ],
      pointCloudPreview: null,
      imuPreview: null,
    };
  }

  if (topic === "/nav2_goal_context" && typeof message?.data === "string") {
    const parsed = tryParseJsonString(message.data) ?? {};
    return {
      chartTitle: "任务状态",
      metricSeries: [],
      badges: [
        { label: "active", value: String(parsed.active ?? "-"), tone: toneForBoolean(parsed.active) },
        { label: "accepted", value: String(parsed.accepted ?? "-"), tone: toneForBoolean(parsed.accepted) },
        { label: "paused", value: String(parsed.paused_by_user ?? parsed.paused_by_localization ?? "-"), tone: toneForBoolean(Boolean(parsed.paused_by_user || parsed.paused_by_localization || parsed.paused_by_obstacle)) },
      ],
      keyValues: [
        { key: "request_planid", value: String(parsed.request_planid ?? "-") },
        { key: "result", value: String(parsed.result ?? "-") },
        { key: "pose", value: `${parsed.pose?.x ?? "-"}, ${parsed.pose?.y ?? "-"}, ${parsed.pose?.yaw ?? "-"}` },
      ],
      pointCloudPreview: null,
      imuPreview: null,
    };
  }

  if (topic === "/cmd_vel") {
    const linearX = safeNumber(message?.linear?.x);
    const angularZ = safeNumber(message?.angular?.z);
    return {
      chartTitle: "控制输出趋势",
      metricSeries: [
        createMetricSeries("linear_x", "mps", "#2f8cff", linearX, previous?.metricSeries.find((item) => item.label === "linear_x")),
        createMetricSeries("angular_z", "rad", "#f15d78", angularZ, previous?.metricSeries.find((item) => item.label === "angular_z")),
      ],
      badges: [],
      keyValues: [
        { key: "linear_x", value: formatNumber(linearX, 3) },
        { key: "angular_z", value: formatNumber(angularZ, 3) },
      ],
      pointCloudPreview: null,
      imuPreview: null,
    };
  }

  if (isImuPanel(panel)) {
    const accelX = safeNumber(message?.linear_acceleration?.x);
    const accelY = safeNumber(message?.linear_acceleration?.y);
    const accelZ = safeNumber(message?.linear_acceleration?.z);
    const gyroX = safeNumber(message?.angular_velocity?.x);
    const gyroY = safeNumber(message?.angular_velocity?.y);
    const gyroZ = safeNumber(message?.angular_velocity?.z);
    const accelMagnitude = accelX === null || accelY === null || accelZ === null
      ? null
      : vectorLength3d(accelX, accelY, accelZ);
    const gyroMagnitude = gyroX === null || gyroY === null || gyroZ === null
      ? null
      : vectorLength3d(gyroX, gyroY, gyroZ);
    const imuPreview = buildImuPreview(panel.id, message);
    return {
      chartTitle: "IMU 运动趋势",
      metricSeries: [
        createMetricSeries("accel_mag", "m/s²", "#2f8cff", accelMagnitude, previous?.metricSeries.find((item) => item.label === "accel_mag")),
        createMetricSeries("gyro_mag", "rad/s", "#f6a237", gyroMagnitude, previous?.metricSeries.find((item) => item.label === "gyro_mag")),
      ],
      badges: [
        {
          label: "source",
          value: imuPreview?.orientationSource === "quaternion" ? "quat" : imuPreview?.orientationSource === "integrated_gyro" ? "gyro" : "accel",
          tone: "neutral",
        },
        { label: "motion", value: `${Math.round((imuPreview?.motionLevel ?? 0) * 100)}%`, tone: (imuPreview?.motionLevel ?? 0) > 0.68 ? "warning" : "neutral" },
      ],
      keyValues: [
        { key: "ax ay az", value: `${formatNumber(accelX, 2)}, ${formatNumber(accelY, 2)}, ${formatNumber(accelZ, 2)}` },
        { key: "gx gy gz", value: `${formatNumber(gyroX, 2)}, ${formatNumber(gyroY, 2)}, ${formatNumber(gyroZ, 2)}` },
      ],
      pointCloudPreview: null,
      imuPreview,
    };
  }

  if (isPointCloudPanel(panel)) {
    const totalPoints = Number(message?.width ?? 0) * Math.max(1, Number(message?.height ?? 1));
    const preview = buildPointCloudPreview(message);
    const hzLimit = safeHzLimit(panel);
    return {
      chartTitle: "点云概览",
      metricSeries: [
        createMetricSeries(
          "points",
          "count",
          "#2f8cff",
          totalPoints > 0 ? totalPoints : null,
          previous?.metricSeries.find((item) => item.label === "points")
        ),
      ],
      badges: [
        { label: "size", value: `${normalizePointSize(panel).toFixed(1)}`, tone: "neutral" },
        { label: "hz", value: hzLimit > 0 ? `${hzLimit}` : "无限制", tone: "neutral" },
      ],
      keyValues: [
        { key: "总点数", value: `${totalPoints || 0}` },
        { key: "抽样点数", value: `${preview?.samplePoints ?? 0}` },
        { key: "point_step", value: `${message?.point_step ?? "-"}` },
        { key: "row_step", value: `${message?.row_step ?? "-"}` },
      ],
      pointCloudPreview: preview,
      imuPreview: null,
    };
  }

  return {
    chartTitle: "原始消息",
    metricSeries: previous?.metricSeries ?? [],
    badges: previous?.badges ?? [],
    keyValues: previous?.keyValues ?? [],
    pointCloudPreview: previous?.pointCloudPreview ?? null,
    imuPreview: previous?.imuPreview ?? null,
  };
}

function setPanelState(panel: NavPanelItem, message: any) {
  const previous = panelStateMap.value[panel.id] ?? buildDefaultState(panel.topic);
  const visualization = buildPanelVisualization(panel, message, previous);
  panelStateMap.value = {
    ...panelStateMap.value,
    [panel.id]: {
      summary: summarizeMessage(panel, message),
      pretty: prettyMessage(message),
      updatedAt: formatTimestamp(),
      chartTitle: visualization.chartTitle,
      metricSeries: visualization.metricSeries,
      badges: visualization.badges,
      keyValues: visualization.keyValues,
      pointCloudPreview: visualization.pointCloudPreview,
      imuPreview: visualization.imuPreview,
    },
  };
  return visualization;
}

function sparklinePoints(values: number[]) {
  if (values.length === 0) {
    return "";
  }
  if (values.length === 1) {
    return "0,40 100,40";
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = Math.max(1e-6, max - min);
  return values
    .map((value, index) => {
      const x = (index / (values.length - 1)) * 100;
      const y = 44 - ((value - min) / span) * 36;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");
}

function metricLatest(metric: MetricSeries) {
  return metric.values.length > 0 ? metric.values[metric.values.length - 1] : null;
}

function metricMin(metric: MetricSeries) {
  return metric.values.length > 0 ? Math.min(...metric.values) : null;
}

function metricMax(metric: MetricSeries) {
  return metric.values.length > 0 ? Math.max(...metric.values) : null;
}

function panelState(panelId: string, topic: string) {
  return panelStateMap.value[panelId] ?? buildDefaultState(topic);
}

function panelRecording(panelId: string) {
  return panelRecordingMap.value[panelId] ?? buildDefaultRecordingState();
}

function compactMetricLabel(panelId: string, metrics: MetricSeries[]) {
  const selectedLabel = compactMetricSelectionMap.value[panelId];
  if (selectedLabel && metrics.some((metric) => metric.label === selectedLabel)) {
    return selectedLabel;
  }
  return metrics[0]?.label ?? "";
}

function selectCompactMetric(panelId: string, metricLabel: string) {
  compactMetricSelectionMap.value = {
    ...compactMetricSelectionMap.value,
    [panelId]: metricLabel,
  };
}

function compactMetricsForPanel(panelId: string, topic: string) {
  const metrics = panelState(panelId, topic).metricSeries;
  if (!props.compact || metrics.length <= 1) {
    return metrics;
  }
  const selectedLabel = compactMetricLabel(panelId, metrics);
  return metrics.filter((metric) => metric.label === selectedLabel);
}

function metricValueText(metric: MetricSeries) {
  const latest = metricLatest(metric);
  return latest === null ? "-" : latest.toFixed(3);
}

function recordingDurationText(recording: PanelRecordingState) {
  const durationMs = recording.durationMs || (recording.isRecording ? Math.max(0, Date.now() - recording.startedAtMs) : 0);
  return `${(durationMs / 1000).toFixed(2)} s`;
}

function appendRecordedEntry(recording: PanelRecordingState, timestampText: string, content: string) {
  const nextEntries = [`[${timestampText}] ${content}`, ...recording.entries];
  return nextEntries.length > maxRecordedEntries ? nextEntries.slice(0, maxRecordedEntries) : nextEntries;
}

function mergeRecordedMetricSeries(recording: PanelRecordingState, state: PanelState, offsetMs: number) {
  const previousSeries = new Map(recording.metricSeries.map((item) => [item.label, item]));
  return state.metricSeries.map((metric) => {
    const previousMetric = previousSeries.get(metric.label);
    const latest = metricLatest(metric);
    return {
      label: metric.label,
      unit: metric.unit,
      color: metric.color,
      samples: latest === null
        ? previousMetric?.samples ?? []
        : [...(previousMetric?.samples ?? []), { offsetMs, value: latest }],
    };
  });
}

async function toggleRecording(panel: NavPanelItem) {
  const current = panelRecording(panel.id);
  if (!current.isRecording) {
    const now = Date.now();
    panelRecordingMap.value = {
      ...panelRecordingMap.value,
      [panel.id]: {
        isRecording: true,
        startedAtMs: now,
        startedAtText: formatTimestampWithMs(now),
        stoppedAtText: "-",
        durationMs: 0,
        entries: [],
        metricSeries: [],
      },
    };
    return;
  }

  const stopTime = Date.now();
  const nextRecordingState: PanelRecordingState = {
    ...current,
    isRecording: false,
    stoppedAtText: formatTimestampWithMs(stopTime),
    durationMs: Math.max(0, stopTime - current.startedAtMs),
  };
  panelRecordingMap.value = {
    ...panelRecordingMap.value,
    [panel.id]: nextRecordingState,
  };
  try {
    await saveNavRecording({
      panel_id: panel.id,
      title: panel.title,
      topic: panel.topic,
      message_type: panel.messageType,
      started_at_ms: nextRecordingState.startedAtMs,
      started_at: nextRecordingState.startedAtText,
      stopped_at: nextRecordingState.stoppedAtText,
      duration_ms: nextRecordingState.durationMs,
      entries: nextRecordingState.entries,
      metric_series: nextRecordingState.metricSeries.map((metric) => ({
        label: metric.label,
        unit: metric.unit,
        color: metric.color,
        samples: metric.samples.map((sample) => ({
          offset_ms: sample.offsetMs,
          value: sample.value,
        })),
      })),
    });
    emit("recordingSaved");
  } catch {
    // 保存失败时保留当前录制结果，避免用户界面里的数据直接丢失。
  }
}

function updateRecordingState(panel: NavPanelItem, message: any, state: PanelState) {
  const recording = panelRecording(panel.id);
  if (!recording.isRecording) {
    return;
  }
  const now = Date.now();
  const timestampText = formatTimestampWithMs(now);
  const offsetMs = Math.max(0, now - recording.startedAtMs);
  panelRecordingMap.value = {
    ...panelRecordingMap.value,
    [panel.id]: {
      ...recording,
      durationMs: offsetMs,
      entries: appendRecordedEntry(recording, timestampText, prettyMessage(message)),
      metricSeries: mergeRecordedMetricSeries(recording, state, offsetMs),
    },
  };
}

function panelConnectionText(panel: NavPanelItem) {
  if (panel.paused || panel.collapsed) {
    return "已暂停";
  }
  if (!props.url && props.provider !== "mock") {
    return "未配置";
  }
  if (!isAdapterConnected.value) {
    return "未连接";
  }
  return "已订阅";
}

function pointCloudDotRadius(panel: NavPanelItem) {
  return normalizePointSize(panel);
}

function updatePointCloudPointSize(panelId: string, rawValue: string) {
  emit("updateConfig", panelId, {
    pointSize: Math.min(8, Math.max(0.8, Number(rawValue || "2.5") || 2.5)),
  });
}

function updatePointCloudHzLimit(panelId: string, rawValue: string) {
  emit("updateConfig", panelId, {
    hzLimit: Math.max(0, Math.round(Number(rawValue || "0") || 0)),
  });
}

function handlePanelMessage(panelId: string, message: any) {
  const panel = props.panels.find((item) => item.id === panelId);
  if (!panel) {
    return;
  }

  if (isPointCloudPanel(panel)) {
    const hzLimit = safeHzLimit(panel);
    if (hzLimit > 0) {
      const minIntervalMs = 1000 / hzLimit;
      const now = Date.now();
      const previousTime = lastMessageTimeMap.get(panelId) ?? 0;
      if (now - previousTime < minIntervalMs) {
        return;
      }
      lastMessageTimeMap.set(panelId, now);
    }
  }

  const visualization = setPanelState(panel, message);
  updateRecordingState(panel, message, {
    summary: summarizeMessage(panel, message),
    pretty: prettyMessage(message),
    updatedAt: formatTimestamp(),
    chartTitle: visualization.chartTitle,
    metricSeries: visualization.metricSeries,
    badges: visualization.badges,
    keyValues: visualization.keyValues,
    pointCloudPreview: visualization.pointCloudPreview,
  });
}

async function reconnect() {
  unsubscribeMap.forEach((unsubscribe) => unsubscribe());
  unsubscribeMap.clear();
  lastMessageTimeMap.clear();
  adapter?.disconnect();
  isAdapterConnected.value = false;
  adapter = createRosLiveAdapter({
    provider: props.provider,
    url: props.url,
    timeoutMs: props.timeoutMs,
  });

  if (!props.url && props.provider !== "mock") {
    adapterState.value = "未配置地址";
    return;
  }

  try {
    await adapter.connect();
    const snapshot = adapter.getConnectionSnapshot();
    isAdapterConnected.value = snapshot.connected;
    adapterState.value = snapshot.message;
    activePanels.value.forEach((panel) => {
      const unsubscribe = adapter?.subscribe(panel.topic, panel.messageType, (message) => {
        handlePanelMessage(panel.id, message);
      });
      if (unsubscribe) {
        unsubscribeMap.set(panel.id, unsubscribe);
      }
    });
  } catch (error) {
    isAdapterConnected.value = false;
    adapterState.value = (error as Error).message;
  }
}

watch(
  () => [props.provider, props.url, props.timeoutMs],
  async () => {
    await reconnect();
  },
  { immediate: true }
);

watch(
  () => props.panels,
  (panels) => {
    const activeIds = new Set(panels.filter((panel) => !panel.collapsed && !panel.paused).map((panel) => panel.id));
    const existingIds = new Set(panels.map((panel) => panel.id));
    [...unsubscribeMap.keys()].forEach((panelId) => {
      if (!activeIds.has(panelId)) {
        unsubscribeMap.get(panelId)?.();
        unsubscribeMap.delete(panelId);
        lastMessageTimeMap.delete(panelId);
      }
    });
    const nextImuPoseStateMap = Object.fromEntries(
      Object.entries(imuPoseStateMap.value).filter(([panelId]) => existingIds.has(panelId))
    );
    if (Object.keys(nextImuPoseStateMap).length !== Object.keys(imuPoseStateMap.value).length) {
      imuPoseStateMap.value = nextImuPoseStateMap;
    }
    const nextCompactMetricSelectionMap = Object.fromEntries(
      Object.entries(compactMetricSelectionMap.value).filter(([panelId]) => existingIds.has(panelId))
    );
    if (Object.keys(nextCompactMetricSelectionMap).length !== Object.keys(compactMetricSelectionMap.value).length) {
      compactMetricSelectionMap.value = nextCompactMetricSelectionMap;
    }

    if (!adapter || !isAdapterConnected.value) {
      return;
    }

    panels.filter((panel) => !panel.collapsed && !panel.paused).forEach((panel) => {
      if (unsubscribeMap.has(panel.id)) {
        return;
      }
      const unsubscribe = adapter?.subscribe(panel.topic, panel.messageType, (message) => {
        handlePanelMessage(panel.id, message);
      });
      if (unsubscribe) {
        unsubscribeMap.set(panel.id, unsubscribe);
      }
    });
  },
  { deep: true }
);

onBeforeUnmount(() => {
  unsubscribeMap.forEach((unsubscribe) => unsubscribe());
  unsubscribeMap.clear();
  lastMessageTimeMap.clear();
  adapter?.disconnect();
  isAdapterConnected.value = false;
});
</script>

<template>
  <div class="nav-topic-panels-shell" :class="{ compact: props.compact }">
    <div class="nav-topic-panels-status">{{ adapterState }}</div>
    <div class="nav-topic-panels-grid" :class="{ compact: props.compact }">
      <article v-for="panel in panels" :key="panel.id" class="nav-mini-panel" :class="{ collapsed: panel.collapsed, compact: props.compact }">
        <div class="nav-mini-panel-head">
          <button class="nav-mini-panel-toggle" type="button" @click="emit('toggle', panel.id)">
            <span class="collapse-trigger-label">
              <span class="collapse-caret" :class="{ expanded: !panel.collapsed }">▸</span>
              <span>{{ panel.title }}</span>
            </span>
            <span class="nav-mini-panel-head-side">
              <span v-if="panelRecording(panel.id).isRecording || panelRecording(panel.id).entries.length" class="nav-recording-inline">
                <span class="nav-recording-pill" :class="{ active: panelRecording(panel.id).isRecording }">
                  {{ panelRecording(panel.id).isRecording ? "录制中" : "已录制" }}
                </span>
                <span class="nav-recording-meta">{{ recordingDurationText(panelRecording(panel.id)) }}</span>
              </span>
              <span class="nav-mini-panel-state">{{ panelConnectionText(panel) }}</span>
            </span>
          </button>
          <button
            class="secondary-btn small"
            :class="{ recording: panelRecording(panel.id).isRecording }"
            type="button"
            @click="toggleRecording(panel)"
          >
            {{ panelRecording(panel.id).isRecording ? "停止录制" : "录制" }}
          </button>
          <button class="section-card-action danger" type="button" @click="emit('remove', panel.id)">移除</button>
        </div>

        <div v-if="!panel.collapsed" class="nav-mini-panel-body">
          <div v-if="isPointCloudPanel(panel) && !props.compact" class="nav-pointcloud-config-row">
            <label class="nav-pointcloud-config-item">
              <span class="kv-key">点大小</span>
              <input
                class="field-input nav-pointcloud-input"
                type="number"
                min="0.8"
                max="8"
                step="0.2"
                :value="normalizePointSize(panel)"
                @input="updatePointCloudPointSize(panel.id, ($event.target as HTMLInputElement).value)"
              />
            </label>
            <label class="nav-pointcloud-config-item">
              <span class="kv-key">Hz 限制</span>
              <input
                class="field-input nav-pointcloud-input"
                type="number"
                min="0"
                max="60"
                step="1"
                :value="safeHzLimit(panel)"
                @input="updatePointCloudHzLimit(panel.id, ($event.target as HTMLInputElement).value)"
              />
            </label>
          </div>

          <div v-if="!props.compact" class="nav-mini-panel-meta">
            <span class="kv-key">Topic</span>
            <span class="kv-value">{{ panel.topic }}</span>
          </div>
          <div v-if="!props.compact" class="nav-mini-panel-meta">
            <span class="kv-key">类型</span>
            <span class="kv-value">{{ panel.messageType || panel.type }}</span>
          </div>
          <div v-if="!props.compact" class="nav-mini-panel-meta">
            <span class="kv-key">摘要</span>
            <span class="kv-value">{{ panelState(panel.id, panel.topic).summary }}</span>
          </div>
          <div v-if="!props.compact" class="nav-mini-panel-meta">
            <span class="kv-key">更新时间</span>
            <span class="kv-value">{{ panelState(panel.id, panel.topic).updatedAt }}</span>
          </div>

          <div v-if="props.compact && !panelState(panel.id, panel.topic).metricSeries.length" class="nav-mini-panel-compact-summary">
            {{ panelState(panel.id, panel.topic).metricSeries.length ? panel.topic : panelState(panel.id, panel.topic).summary }}
          </div>

          <div v-if="panelState(panel.id, panel.topic).imuPreview" class="nav-imu-preview-card" :class="{ compact: props.compact }">
            <div class="nav-imu-preview-head">
              <span>IMU 方向</span>
              <span>
                {{
                  panelState(panel.id, panel.topic).imuPreview?.orientationSource === 'quaternion'
                    ? '姿态'
                    : panelState(panel.id, panel.topic).imuPreview?.orientationSource === 'integrated_gyro'
                      ? '角速度积分'
                      : '加速度'
                }}
              </span>
            </div>
            <svg class="nav-imu-preview" viewBox="0 0 144 144" preserveAspectRatio="xMidYMid meet">
              <circle cx="72" cy="72" r="56" class="nav-imu-preview-ring" />
              <line x1="72" y1="72" x2="108" y2="72" class="nav-imu-world-axis axis-front" />
              <line x1="72" y1="72" x2="48" y2="90" class="nav-imu-world-axis axis-left" />
              <line x1="72" y1="72" x2="72" y2="36" class="nav-imu-world-axis axis-up" />
              <polyline :points="panelState(panel.id, panel.topic).imuPreview?.leftLine" class="nav-imu-body-axis axis-left" />
              <polyline :points="panelState(panel.id, panel.topic).imuPreview?.upLine" class="nav-imu-body-axis axis-up" />
              <polyline :points="panelState(panel.id, panel.topic).imuPreview?.forwardLine" class="nav-imu-vector-line" />
              <polygon :points="panelState(panel.id, panel.topic).imuPreview?.forwardHead" class="nav-imu-vector-head" />
              <text :x="panelState(panel.id, panel.topic).imuPreview?.frontLabel.x" :y="panelState(panel.id, panel.topic).imuPreview?.frontLabel.y" class="nav-imu-label front">FRONT</text>
              <text x="109" y="69" class="nav-imu-world-label front">W+X</text>
              <text x="34" y="98" class="nav-imu-world-label side">W+Y</text>
              <text x="77" y="31" class="nav-imu-world-label side">W+Z</text>
            </svg>
          </div>

          <div v-if="!props.compact && panelState(panel.id, panel.topic).badges.length" class="nav-panel-badges">
            <span
              v-for="badge in panelState(panel.id, panel.topic).badges"
              :key="`${panel.id}-${badge.label}`"
              class="nav-panel-badge"
              :class="`tone-${badge.tone}`"
            >
              {{ badge.label }}: {{ badge.value }}
            </span>
          </div>

          <div v-if="props.compact && panelState(panel.id, panel.topic).metricSeries.length > 1" class="nav-compact-metric-selector">
            <button
              v-for="metric in panelState(panel.id, panel.topic).metricSeries"
              :key="`${panel.id}-selector-${metric.label}`"
              class="nav-compact-metric-chip"
              :class="{ active: compactMetricLabel(panel.id, panelState(panel.id, panel.topic).metricSeries) === metric.label }"
              type="button"
              @click="selectCompactMetric(panel.id, metric.label)"
            >
              {{ metric.label }}
            </button>
          </div>

          <div v-if="panelState(panel.id, panel.topic).metricSeries.length && !(props.compact && panelState(panel.id, panel.topic).imuPreview)" class="nav-panel-metric-grid">
            <section
              v-for="metric in (props.compact ? compactMetricsForPanel(panel.id, panel.topic) : panelState(panel.id, panel.topic).metricSeries)"
              :key="`${panel.id}-${metric.label}`"
              class="nav-panel-metric-card"
            >
              <div class="nav-panel-metric-head">
                <strong>{{ metric.label }}</strong>
                <span>{{ metric.unit || "value" }}</span>
              </div>
              <div class="nav-panel-metric-value">
                {{ metricValueText(metric) }}
              </div>
              <svg class="nav-panel-sparkline" viewBox="0 0 100 48" preserveAspectRatio="none">
                <polyline
                  :points="sparklinePoints(metric.values)"
                  :stroke="metric.color"
                  stroke-width="2"
                  fill="none"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  vector-effect="non-scaling-stroke"
                />
              </svg>
              <div v-if="!props.compact" class="nav-panel-metric-stats">
                <span>min {{ metricMin(metric)?.toFixed(3) ?? "-" }}</span>
                <span>max {{ metricMax(metric)?.toFixed(3) ?? "-" }}</span>
              </div>
            </section>
          </div>

          <div v-if="!props.compact && panelState(panel.id, panel.topic).keyValues.length" class="nav-panel-kv-grid">
            <div
              v-for="item in panelState(panel.id, panel.topic).keyValues"
              :key="`${panel.id}-${item.key}`"
              class="nav-panel-kv-item"
            >
              <span class="kv-key">{{ item.key }}</span>
              <span class="kv-value">{{ item.value }}</span>
            </div>
          </div>

          <pre v-if="!panelState(panel.id, panel.topic).metricSeries.length" class="logs nav-panel-pretty" :class="{ compact: props.compact }">{{ panelState(panel.id, panel.topic).pretty }}</pre>
          <pre v-else-if="!props.compact" class="logs nav-panel-pretty">{{ panelState(panel.id, panel.topic).pretty }}</pre>
          <div v-if="!props.compact && panelRecording(panel.id).entries.length" class="nav-recording-log-block">
            <div class="nav-panel-recorded-title">
              录制内容
              <span>{{ panelRecording(panel.id).startedAtText }} -> {{ panelRecording(panel.id).stoppedAtText === '-' && panelRecording(panel.id).isRecording ? '进行中' : panelRecording(panel.id).stoppedAtText }}</span>
            </div>
            <pre class="logs nav-panel-pretty nav-recording-log">{{ panelRecording(panel.id).entries.join('\n\n') }}</pre>
          </div>
        </div>
      </article>
    </div>
  </div>
</template>
