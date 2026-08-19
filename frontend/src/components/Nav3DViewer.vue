<!-- 功能说明：导航测试页三维主视图，负责把 ROS 常用话题渲染到统一 3D 窗口。 -->
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

import type { NavViewerDisplay } from "../lib/ros/displayRegistry";
import { buildSharedRosKey, createSharedRosLiveAdapter, type RosLiveConfig } from "../lib/ros/liveAdapter";

interface NavViewerExpose {
  focusOnNdtPose: () => { ok: boolean; message: string };
}

const props = defineProps<{
  provider: string;
  url: string;
  timeoutMs: number;
  fixedFrame: string;
  displays: NavViewerDisplay[];
  interactionMode?: "none" | "initialpose" | "navgoal";
  reconnectToken?: number;
}>();

const emit = defineEmits<{
  interactionComplete: [payload: { mode: "initialpose" | "navgoal"; x: number; y: number; yaw: number }];
  tfFramesChange: [payload: { topic: string; frames: string[] }];
  rosLog: [payload: { source: string; level: "info" | "warning" | "error"; message: string }];
}>();

const mountRef = ref<HTMLDivElement | null>(null);
const connectionLabel = ref("未连接");
const sceneStatus = ref("等待显示项");
const baseLinkHudText = ref("等待 rosbridge 连接");

interface NavPoseAnchor {
  topic: string;
  frameId: string;
  x: number;
  y: number;
  z: number;
  yaw: number;
}

interface ObstacleZoneState {
  code: number;
  label: string;
}

interface TfTransformSample {
  parentFrame: string;
  matrixToParent: THREE.Matrix4;
  stampMs: number | null;
  staticTransform: boolean;
}

const OBSTACLE_ZONE_DEFAULTS = {
  detectionRange: 5,
  calmRadius: 1,
  dangerRadius: 0.6,
  ignoreZone: {
    xMin: -0.3,
    xMax: 0.3,
    yMin: -0.2,
    yMax: 0.5,
  },
} as const;

let renderer: THREE.WebGLRenderer | null = null;
let scene: THREE.Scene | null = null;
let camera: THREE.PerspectiveCamera | null = null;
let controls: OrbitControls | null = null;
let animationFrame = 0;
let rosAdapter: ReturnType<typeof createSharedRosLiveAdapter> | null = null;
let resizeObserver: ResizeObserver | null = null;
let reconnectTimer: number | undefined;
let lastViewportWidth = 0;
let lastViewportHeight = 0;
let interactionStartPoint: THREE.Vector3 | null = null;
let interactionCurrentPoint: THREE.Vector3 | null = null;
let interactionPreviewGroup: THREE.Group | null = null;
let activeInteractionPointerId: number | null = null;
let webglContextLost = false;

const unsubscribeMap = new Map<string, () => void>();
const supportTfUnsubscribeMap = new Map<string, () => void>();
const mapMeshByTopic = new Map<string, THREE.Object3D>();
const mapTextureByTopic = new Map<string, THREE.CanvasTexture>();
const pathLineByTopic = new Map<string, THREE.Line>();
const tfGroupByTopic = new Map<string, THREE.Group>();
const tfFrameNodeCacheByTopic = new Map<string, Map<string, THREE.Group>>();
const poseObjectByTopic = new Map<string, THREE.Object3D>();
const poseAnchorByTopic = new Map<string, NavPoseAnchor>();
const pointCloudByTopic = new Map<string, THREE.Points>();
const laserByTopic = new Map<string, THREE.Points>();
const markerObjectByTopic = new Map<string, THREE.Object3D>();
const twistObjectByTopic = new Map<string, THREE.Object3D>();
const obstacleZoneGroupByTopic = new Map<string, THREE.Group>();
const lastMessageTimeByTopic = new Map<string, number>();
const latestMessageByTopic = new Map<string, any>();
const sourceFrameByTopic = new Map<string, string>();
const sourceStampMsByTopic = new Map<string, number | null>();
const baseLocalMatrixByTopic = new Map<string, THREE.Matrix4>();
const tfTransformHistoryByTopic = new Map<string, Map<string, TfTransformSample[]>>();
const tfFrameSignatureByTopic = new Map<string, string>();
const raycaster = new THREE.Raycaster();
const interactionPlane = new THREE.Plane(new THREE.Vector3(0, 0, 1), 0);
const maxTfHistorySamplesPerFrame = 240;
const maxTfHistoryAgeMs = 30000;

const hudDisplayCount = computed(() => props.displays.length);
const currentInteractionMode = computed(() => props.interactionMode || "none");
const canConsumeTopicData = computed(
  () => connectionLabel.value === "已连接"
);
const emptyStateText = computed(() => {
  if (connectionLabel.value === "未配置地址") {
    return "请先填写 rosbridge 地址，再启动三维主视图。";
  }
  if (connectionLabel.value === "连接失败") {
    return "当前未连接 rosbridge，仅显示基础网格和坐标轴。";
  }
  if (connectionLabel.value !== "已连接") {
    return "等待 rosbridge 连接成功后再开始订阅并渲染话题。";
  }
  return "当前没有主视图显示项，请从右侧话题列表添加。";
});
const interactionHintText = computed(() => {
  if (currentInteractionMode.value === "initialpose") {
    return "初始化定位模式: 左键点击地图并拖动方向，松开后下发 /initialpose。";
  }
  if (currentInteractionMode.value === "navgoal") {
    return "导航目标模式: 左键点击地图并拖动方向，松开后下发 /nav2_goal_request。";
  }
  return "";
});
const baseLinkHudTone = computed(() => {
  if (connectionLabel.value !== "已连接") {
    return "warning";
  }
  return baseLinkHudText.value.includes("等待") || baseLinkHudText.value.includes("不可用") ? "warning" : "success";
});

function initializeScene() {
  const host = mountRef.value;
  if (!host) {
    return;
  }

  scene = new THREE.Scene();
  scene.background = new THREE.Color("#08111d");
  scene.up.set(0, 0, 1);

  camera = new THREE.PerspectiveCamera(52, 1, 0.01, 500);
  camera.up.set(0, 0, 1);
  camera.position.set(7, -9, 8);
  camera.lookAt(0, 0, 0);

  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
  renderer.setPixelRatio(window.devicePixelRatio);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.setClearColor("#08111d", 1);
  renderer.domElement.style.display = "block";
  renderer.domElement.style.width = "100%";
  renderer.domElement.style.height = "100%";
  renderer.domElement.addEventListener("webglcontextlost", handleWebglContextLost, false);
  renderer.domElement.addEventListener("webglcontextrestored", handleWebglContextRestored, false);
  host.appendChild(renderer.domElement);

  controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.target.set(0, 0, 0);
  controls.screenSpacePanning = false;
  controls.mouseButtons.LEFT = THREE.MOUSE.ROTATE;
  controls.mouseButtons.RIGHT = THREE.MOUSE.PAN;

  const ambient = new THREE.AmbientLight("#c7dcff", 1.35);
  scene.add(ambient);

  const keyLight = new THREE.DirectionalLight("#9cc9ff", 1.2);
  keyLight.position.set(7, -5, 10);
  scene.add(keyLight);

  const grid = new THREE.GridHelper(40, 40, "#2f8cff", "#1d3555");
  grid.rotateX(Math.PI / 2);
  scene.add(grid);

  const axes = new THREE.AxesHelper(1.4);
  scene.add(axes);

  fitRendererSize();
  animate();
}

function fitRendererSize() {
  if (!renderer || !camera || !mountRef.value) {
    return;
  }
  const bounds = mountRef.value.getBoundingClientRect();
  const width = Math.max(320, Math.round(bounds.width));
  const height = Math.max(320, Math.round(bounds.height));
  if (width === lastViewportWidth && height === lastViewportHeight) {
    return;
  }
  lastViewportWidth = width;
  lastViewportHeight = height;
  renderer.setSize(width, height, false);
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
}

function syncControlLockState() {
  if (!controls || !renderer) {
    return;
  }
  const interactionLocked = currentInteractionMode.value !== "none" || activeInteractionPointerId !== null;
  controls.enabled = !interactionLocked;
  // 主视图区域统一禁用浏览器默认触控滚动，避免移动端横屏下手势被页面抢走。
  renderer.domElement.style.touchAction = "none";
  renderer.domElement.style.cursor = interactionLocked ? "crosshair" : "grab";
}

function animate() {
  if (!renderer || !scene || !camera || webglContextLost) {
    return;
  }
  animationFrame = window.requestAnimationFrame(animate);
  controls?.update();
  renderer.render(scene, camera);
}

function disposeMaterialResources(material: THREE.Material | null | undefined) {
  if (!material) {
    return;
  }
  const textureKeys = [
    "map",
    "alphaMap",
    "aoMap",
    "bumpMap",
    "displacementMap",
    "emissiveMap",
    "envMap",
    "lightMap",
    "metalnessMap",
    "normalMap",
    "roughnessMap",
    "specularMap",
  ] as const;
  textureKeys.forEach((key) => {
    const texture = (material as THREE.Material & Record<string, unknown>)[key];
    if (texture instanceof THREE.Texture) {
      texture.dispose();
    }
  });
  material.dispose();
}

function clearThreeObject(object: THREE.Object3D) {
  scene?.remove(object);
  object.traverse((child) => {
    const mesh = child as THREE.Mesh;
    if (mesh.geometry) {
      mesh.geometry.dispose();
    }
    const material = mesh.material;
    if (Array.isArray(material)) {
      material.forEach((item) => disposeMaterialResources(item));
    } else {
      disposeMaterialResources(material ?? null);
    }
  });
}

function handleWebglContextLost(event: Event) {
  event.preventDefault();
  webglContextLost = true;
  window.cancelAnimationFrame(animationFrame);
  connectionLabel.value = "渲染上下文丢失";
  sceneStatus.value = "WebGL 上下文已丢失，请等待恢复或手动重连页面。";
  emitRosLog("warning", "三维主视图 WebGL 上下文丢失，已暂停渲染。");
}

function handleWebglContextRestored() {
  webglContextLost = false;
  sceneStatus.value = "WebGL 上下文已恢复，准备重新连接并渲染。";
  emitRosLog("info", "三维主视图 WebGL 上下文已恢复，正在重新订阅并重建场景。");
  void reconnectAndResubscribe();
  animate();
}

function teardownRenderer() {
  clearInteractionPreview();
  clearAllTopicVisuals();
  tfTransformHistoryByTopic.clear();
  tfFrameNodeCacheByTopic.clear();
  if (renderer?.domElement) {
    renderer.domElement.removeEventListener("webglcontextlost", handleWebglContextLost);
    renderer.domElement.removeEventListener("webglcontextrestored", handleWebglContextRestored);
  }
  controls?.dispose();
  controls = null;
  if (renderer) {
    renderer.dispose();
    renderer.forceContextLoss();
    const canvas = renderer.domElement;
    if (canvas.parentElement) {
      canvas.parentElement.removeChild(canvas);
    }
  }
  renderer = null;
  scene = null;
  camera = null;
  webglContextLost = false;
  lastViewportWidth = 0;
  lastViewportHeight = 0;
}

function disposeTopic(topic: string) {
  const unsubscribe = unsubscribeMap.get(topic);
  unsubscribe?.();
  unsubscribeMap.delete(topic);

  const mapMesh = mapMeshByTopic.get(topic);
  if (mapMesh) {
    clearThreeObject(mapMesh);
    mapMeshByTopic.delete(topic);
  }
  const mapTexture = mapTextureByTopic.get(topic);
  mapTexture?.dispose();
  mapTextureByTopic.delete(topic);

  const pathLine = pathLineByTopic.get(topic);
  if (pathLine) {
    clearThreeObject(pathLine);
    pathLineByTopic.delete(topic);
  }

  const tfGroup = tfGroupByTopic.get(topic);
  if (tfGroup) {
    clearThreeObject(tfGroup);
    tfGroupByTopic.delete(topic);
  }
  tfFrameNodeCacheByTopic.delete(topic);
  tfTransformHistoryByTopic.delete(normalizeTfTopicKey(topic));

  const poseObject = poseObjectByTopic.get(topic);
  if (poseObject) {
    clearThreeObject(poseObject);
    poseObjectByTopic.delete(topic);
  }
  poseAnchorByTopic.delete(topic);

  const pointCloud = pointCloudByTopic.get(topic);
  if (pointCloud) {
    clearThreeObject(pointCloud);
    pointCloudByTopic.delete(topic);
  }

  const laser = laserByTopic.get(topic);
  if (laser) {
    clearThreeObject(laser);
    laserByTopic.delete(topic);
  }

  const markerObject = markerObjectByTopic.get(topic);
  if (markerObject) {
    clearThreeObject(markerObject);
    markerObjectByTopic.delete(topic);
  }

  const twistObject = twistObjectByTopic.get(topic);
  if (twistObject) {
    clearThreeObject(twistObject);
    twistObjectByTopic.delete(topic);
  }

  const obstacleZone = obstacleZoneGroupByTopic.get(topic);
  if (obstacleZone) {
    clearThreeObject(obstacleZone);
    obstacleZoneGroupByTopic.delete(topic);
  }

  lastMessageTimeByTopic.delete(topic);
  latestMessageByTopic.delete(topic);
  sourceFrameByTopic.delete(topic);
  sourceStampMsByTopic.delete(topic);
  baseLocalMatrixByTopic.delete(topic);
  tfFrameSignatureByTopic.delete(topic);

  if (getDisplayByTopic(topic)?.kind === "pose" || !getDisplayByTopic(topic)) {
    refreshAllObstacleZones();
  }
}

function clearAllTopicVisuals() {
  [
    ...mapMeshByTopic.keys(),
    ...pathLineByTopic.keys(),
    ...tfGroupByTopic.keys(),
    ...poseObjectByTopic.keys(),
    ...pointCloudByTopic.keys(),
    ...laserByTopic.keys(),
    ...markerObjectByTopic.keys(),
    ...twistObjectByTopic.keys(),
    ...obstacleZoneGroupByTopic.keys(),
  ].forEach((topic) => disposeTopic(topic));
  updateBaseLinkHud();
}

function replaceObjectGeometry<T extends THREE.Object3D & { geometry?: THREE.BufferGeometry | THREE.Geometry | null }>(
  object: T,
  nextGeometry: THREE.BufferGeometry,
) {
  const previousGeometry = object.geometry;
  if (previousGeometry && "dispose" in previousGeometry) {
    previousGeometry.dispose();
  }
  object.geometry = nextGeometry as T["geometry"];
}

function getDisplayByTopic(topic: string) {
  return props.displays.find((display) => display.topic === topic) || null;
}

function normalizeFrameId(frameId: unknown) {
  return String(frameId ?? "").trim().replace(/^\/+/, "");
}

function normalizeTfTopicKey(topic: unknown) {
  return normalizeFrameId(topic);
}

function tfReferenceTopicKeys(topic: string) {
  const normalizedTopic = normalizeTfTopicKey(topic);
  if (normalizedTopic === "tf_static") {
    return ["tf_static"];
  }
  if (normalizedTopic === "tf") {
    return ["tf", "tf_static"];
  }
  return ["tf_static", normalizedTopic].filter((item, index, array) => item && array.indexOf(item) === index);
}

function tfHistoryMapForTopic(topic: string, createIfMissing = false) {
  const topicKey = normalizeTfTopicKey(topic);
  if (!topicKey) {
    return null;
  }
  const existing = tfTransformHistoryByTopic.get(topicKey);
  if (existing || !createIfMissing) {
    return existing ?? null;
  }
  const created = new Map<string, TfTransformSample[]>();
  tfTransformHistoryByTopic.set(topicKey, created);
  return created;
}

function tfFramesForTopic(topic: string) {
  const frameSet = new Set<string>();
  tfReferenceTopicKeys(topic).forEach((topicKey) => {
    const historyMap = tfTransformHistoryByTopic.get(topicKey);
    historyMap?.forEach((_samples, frameName) => {
      frameSet.add(frameName);
    });
  });
  return Array.from(frameSet).sort((left, right) => left.localeCompare(right, "zh-CN"));
}

function tfSamplesForFrame(topic: string, frameId: string) {
  const samples: TfTransformSample[] = [];
  tfReferenceTopicKeys(topic).forEach((topicKey) => {
    const historyMap = tfTransformHistoryByTopic.get(topicKey);
    const topicSamples = historyMap?.get(frameId) ?? [];
    samples.push(...topicSamples);
  });
  return samples;
}

function extractHeaderStampMs(message: any) {
  const sec = Number(message?.header?.stamp?.sec ?? Number.NaN);
  const nanosec = Number(message?.header?.stamp?.nanosec ?? Number.NaN);
  if (!Number.isFinite(sec) || !Number.isFinite(nanosec)) {
    return null;
  }
  return sec * 1000 + nanosec / 1e6;
}

function currentFixedFrame() {
  return normalizeFrameId(props.fixedFrame || "map");
}

function buildTransformMatrix(translation: any, rotation: any) {
  const position = new THREE.Vector3(
    Number(translation?.x ?? 0),
    Number(translation?.y ?? 0),
    Number(translation?.z ?? 0)
  );
  const quaternion = new THREE.Quaternion(
    Number(rotation?.x ?? 0),
    Number(rotation?.y ?? 0),
    Number(rotation?.z ?? 0),
    Number(rotation?.w ?? 1)
  );
  const matrix = new THREE.Matrix4();
  matrix.compose(position, quaternion, new THREE.Vector3(1, 1, 1));
  return matrix;
}

function selectTfTransformSample(frameId: string, targetStampMs: number | null, tfTopic = "/tf") {
  const samples = tfSamplesForFrame(tfTopic, frameId);
  if (samples.length === 0) {
    return null;
  }
  const staticSample = samples.find((item) => item.staticTransform) ?? null;
  if (targetStampMs === null) {
    return samples[samples.length - 1] ?? staticSample;
  }

  let bestSample: TfTransformSample | null = null;
  let bestDelta = Number.POSITIVE_INFINITY;
  samples.forEach((sample) => {
    if (sample.stampMs === null) {
      return;
    }
    const delta = Math.abs(sample.stampMs - targetStampMs);
    if (delta < bestDelta) {
      bestDelta = delta;
      bestSample = sample;
    }
  });
  return bestSample ?? staticSample ?? samples[samples.length - 1] ?? null;
}

function resolveFrameTransformToFixed(frameId: unknown, targetStampMs: number | null = null, tfTopic = "/tf", trail = new Set<string>()): THREE.Matrix4 | null {
  const sourceFrame = normalizeFrameId(frameId);
  const fixedFrame = currentFixedFrame();
  if (!sourceFrame || sourceFrame === fixedFrame) {
    return new THREE.Matrix4().identity();
  }
  if (trail.has(sourceFrame)) {
    return null;
  }
  const sample = selectTfTransformSample(sourceFrame, targetStampMs, tfTopic);
  if (!sample) {
    return null;
  }
  trail.add(sourceFrame);
  const parentMatrix = resolveFrameTransformToFixed(sample.parentFrame, targetStampMs, tfTopic, trail);
  trail.delete(sourceFrame);
  if (!parentMatrix) {
    return null;
  }
  return parentMatrix.clone().multiply(sample.matrixToParent);
}

function transformPositionArrayInPlace(positions: number[], transformMatrix: THREE.Matrix4 | null) {
  if (!transformMatrix) {
    return;
  }
  const point = new THREE.Vector3();
  for (let index = 0; index < positions.length; index += 3) {
    point.set(positions[index], positions[index + 1], positions[index + 2]);
    point.applyMatrix4(transformMatrix);
    positions[index] = point.x;
    positions[index + 1] = point.y;
    positions[index + 2] = point.z;
  }
}

function cacheTopicLocalMatrix(topic: string, matrix: THREE.Matrix4) {
  baseLocalMatrixByTopic.set(topic, matrix.clone());
}

function composeLocalMatrix(
  position: THREE.Vector3 = new THREE.Vector3(),
  quaternion: THREE.Quaternion = new THREE.Quaternion(),
  scale: THREE.Vector3 = new THREE.Vector3(1, 1, 1)
) {
  const matrix = new THREE.Matrix4();
  matrix.compose(position, quaternion, scale);
  return matrix;
}

function applyObjectFrameTransform(topic: string, object: THREE.Object3D, frameId: unknown, targetStampMs: number | null = null, tfTopic = "/tf") {
  const transformMatrix = resolveFrameTransformToFixed(frameId, targetStampMs, tfTopic);
  const baseMatrix = baseLocalMatrixByTopic.get(topic) ?? new THREE.Matrix4().identity();
  const finalMatrix = transformMatrix ? transformMatrix.clone().multiply(baseMatrix) : baseMatrix.clone();
  const position = new THREE.Vector3();
  const quaternion = new THREE.Quaternion();
  const scale = new THREE.Vector3();
  finalMatrix.decompose(position, quaternion, scale);
  object.position.copy(position);
  object.quaternion.copy(quaternion);
  object.scale.copy(scale);
  object.updateMatrix();
}

function updateTopicTransforms() {
  mapMeshByTopic.forEach((object, topic) => applyObjectFrameTransform(topic, object, sourceFrameByTopic.get(topic), sourceStampMsByTopic.get(topic) ?? null));
  pathLineByTopic.forEach((object, topic) => applyObjectFrameTransform(topic, object, sourceFrameByTopic.get(topic), sourceStampMsByTopic.get(topic) ?? null));
  poseObjectByTopic.forEach((object, topic) => applyObjectFrameTransform(topic, object, sourceFrameByTopic.get(topic), sourceStampMsByTopic.get(topic) ?? null));
  pointCloudByTopic.forEach((object, topic) => applyObjectFrameTransform(topic, object, sourceFrameByTopic.get(topic), sourceStampMsByTopic.get(topic) ?? null));
  laserByTopic.forEach((object, topic) => applyObjectFrameTransform(topic, object, sourceFrameByTopic.get(topic), sourceStampMsByTopic.get(topic) ?? null));
  markerObjectByTopic.forEach((object, topic) => applyObjectFrameTransform(topic, object, sourceFrameByTopic.get(topic), sourceStampMsByTopic.get(topic) ?? null));
  twistObjectByTopic.forEach((object, topic) => applyObjectFrameTransform(topic, object, sourceFrameByTopic.get(topic), sourceStampMsByTopic.get(topic) ?? null));
  obstacleZoneGroupByTopic.forEach((object, topic) => applyObjectFrameTransform(topic, object, sourceFrameByTopic.get(topic), sourceStampMsByTopic.get(topic) ?? null));
}

function safePointCloudSize(display: NavViewerDisplay) {
  const value = Number(display.pointSize ?? 0.08);
  if (!Number.isFinite(value)) {
    return 0.08;
  }
  return Math.min(0.6, Math.max(0.01, value));
}

function safeTfLabelSize(display: NavViewerDisplay) {
  const value = Number(display.tfLabelSize ?? 0.5);
  if (!Number.isFinite(value)) {
    return 0.5;
  }
  return Math.min(2, Math.max(0.2, value));
}

function pointColorForDisplay(display: NavViewerDisplay) {
  return display.color || pointColorForTopic(display.topic);
}

function pointColorModeForDisplay(display: NavViewerDisplay) {
  return display.pointColorMode === "layered" ? "layered" : "solid";
}

function pathColorForDisplay(display: NavViewerDisplay) {
  return display.color || "#f6a237";
}

function poseColorForDisplay(display: NavViewerDisplay) {
  return display.color || "#2f8cff";
}

function markerColorForDisplay(display: NavViewerDisplay) {
  return display.color || "#8ea1ba";
}

function twistColorForDisplay(display: NavViewerDisplay) {
  return display.color || "#31d28a";
}

function mapOpacityForDisplay(display: NavViewerDisplay) {
  const value = Number(display.mapOpacity ?? 0.94);
  if (!Number.isFinite(value)) {
    return 0.94;
  }
  return Math.min(1, Math.max(0.05, value));
}

function syncPointCloudDisplayConfigs(displays: NavViewerDisplay[]) {
  displays.forEach((display) => {
    if (display.kind !== "pointcloud") {
      return;
    }
    const points = pointCloudByTopic.get(display.topic);
    const material = points?.material;
    if (!points || !material || Array.isArray(material)) {
      return;
    }
    material.vertexColors = pointColorModeForDisplay(display) === "layered";
    material.color = new THREE.Color(pointColorModeForDisplay(display) === "layered" ? "#ffffff" : pointColorForDisplay(display));
    material.size = safePointCloudSize(display);
    material.opacity = 0.96;
    material.transparent = true;
    material.depthWrite = false;
    material.needsUpdate = true;
  });
}

function syncPathDisplayConfigs(displays: NavViewerDisplay[]) {
  displays.forEach((display) => {
    if (display.kind !== "path" && display.kind !== "bspline") {
      return;
    }
    const line = pathLineByTopic.get(display.topic);
    const material = line?.material;
    if (!line || !material || Array.isArray(material)) {
      return;
    }
    material.color = new THREE.Color(pathColorForDisplay(display));
    material.needsUpdate = true;
  });
}

function syncMarkerDisplayConfigs(displays: NavViewerDisplay[]) {
  displays.forEach((display) => {
    if (display.kind !== "marker") {
      return;
    }
    const root = markerObjectByTopic.get(display.topic);
    if (!root) {
      return;
    }
    const color = new THREE.Color(markerColorForDisplay(display));
    root.traverse((child) => {
      const mesh = child as THREE.Mesh;
      const material = mesh.material;
      if (!material) {
        return;
      }
      if (Array.isArray(material)) {
        material.forEach((item) => {
          if ("color" in item) {
            (item as THREE.Material & { color: THREE.Color }).color = color;
            item.needsUpdate = true;
          }
        });
        return;
      }
      if ("color" in material) {
        (material as THREE.Material & { color: THREE.Color }).color = color;
        material.needsUpdate = true;
      }
    });
  });
}

function syncTwistDisplayConfigs(displays: NavViewerDisplay[]) {
  displays.forEach((display) => {
    if (display.kind !== "twist") {
      return;
    }
    const root = twistObjectByTopic.get(display.topic) as THREE.Group | undefined;
    if (!root) {
      return;
    }
    const arrow = root.getObjectByName("twist-arrow") as THREE.ArrowHelper | null;
    if (!arrow) {
      return;
    }
    arrow.setColor(new THREE.Color(twistColorForDisplay(display)));
  });
}

function syncPoseDisplayConfigs(displays: NavViewerDisplay[]) {
  displays.forEach((display) => {
    if (display.kind !== "pose" && display.kind !== "pose_array") {
      return;
    }
    const group = poseObjectByTopic.get(display.topic);
    if (!group) {
      return;
    }
    const color = new THREE.Color(poseColorForDisplay(display));
    group.traverse((child) => {
      if (child.name !== "pose-body" && child.name !== "pose-tail") {
        return;
      }
      const mesh = child as THREE.Mesh;
      const material = mesh.material;
      if (!material || Array.isArray(material) || !("color" in material)) {
        return;
      }
      (material as THREE.MeshStandardMaterial | THREE.MeshBasicMaterial).color = color;
      material.needsUpdate = true;
    });
  });
}

function syncMapDisplayConfigs(displays: NavViewerDisplay[]) {
  displays.forEach((display) => {
    if (display.kind !== "map") {
      return;
    }
    const root = mapMeshByTopic.get(display.topic);
    if (!root) {
      return;
    }
    root.traverse((child) => {
      const mesh = child as THREE.Mesh;
      const material = mesh.material;
      if (!material || Array.isArray(material)) {
        return;
      }
      if (material instanceof THREE.MeshBasicMaterial) {
        material.opacity = mapOpacityForDisplay(display);
        material.transparent = material.opacity < 1;
        material.needsUpdate = true;
      }
    });
  });
}

function emitTfFrames(topic: string) {
  const frames = tfFramesForTopic(topic);
  const signature = frames.join("|");
  if (tfFrameSignatureByTopic.get(topic) === signature) {
    return;
  }
  tfFrameSignatureByTopic.set(topic, signature);
  emit("tfFramesChange", { topic, frames });
}

function shouldConsumeDisplayMessage(display: NavViewerDisplay) {
  const latestDisplay = getDisplayByTopic(display.topic) || display;
  if (latestDisplay.kind !== "pointcloud") {
    return true;
  }
  const hzLimit = Math.max(0, Math.round(Number(latestDisplay.hzLimit ?? 0) || 0));
  if (hzLimit <= 0) {
    return true;
  }
  const now = Date.now();
  const previous = lastMessageTimeByTopic.get(display.topic) ?? 0;
  const minIntervalMs = 1000 / hzLimit;
  if (now - previous < minIntervalMs) {
    return false;
  }
  lastMessageTimeByTopic.set(display.topic, now);
  return true;
}

/**
 * 功能说明：
 * 把界面上的点云刷新频率限制转换成 rosbridge 订阅参数，
 * 让限流尽量发生在桥接层而不是浏览器收包之后。
 */
function subscriptionOptionsForDisplay(display: NavViewerDisplay) {
  if (display.kind !== "pointcloud") {
    return undefined;
  }
  const hzLimit = Math.max(0, Math.round(Number(display.hzLimit ?? 0) || 0));
  if (hzLimit <= 0) {
    return {
      queueLength: 1,
    };
  }
  return {
    throttleRateMs: Math.max(1, Math.round(1000 / hzLimit)),
    queueLength: 1,
  };
}

function renderOccupancyGrid(topic: string, message: any) {
  if (!scene) {
    return;
  }
  const display = getDisplayByTopic(topic);

  const width = Number(message?.info?.width ?? 0);
  const height = Number(message?.info?.height ?? 0);
  const resolution = Number(message?.info?.resolution ?? 0);
  const originX = Number(message?.info?.origin?.position?.x ?? 0);
  const originY = Number(message?.info?.origin?.position?.y ?? 0);
  const originZ = Number(message?.info?.origin?.position?.z ?? 0);
  const originRotation = message?.info?.origin?.orientation ?? {};
  const data = Array.isArray(message?.data) ? message.data : [];
  if (width <= 0 || height <= 0 || resolution <= 0 || data.length === 0) {
    return;
  }

  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d");
  if (!context) {
    return;
  }

  const image = context.createImageData(width, height);
  for (let index = 0; index < data.length; index += 1) {
    const value = Number(data[index] ?? -1);
    const x = index % width;
    const y = height - 1 - Math.floor(index / width);
    const pixelIndex = (y * width + x) * 4;

    let color = 220;
    if (value < 0) {
      color = 115;
    } else if (value >= 80) {
      color = 35;
    } else if (value > 0) {
      color = Math.max(35, 235 - Math.round((value / 100) * 200));
    }

    image.data[pixelIndex] = color;
    image.data[pixelIndex + 1] = color;
    image.data[pixelIndex + 2] = color;
    image.data[pixelIndex + 3] = 255;
  }
  context.putImageData(image, 0, 0);

  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.needsUpdate = true;

  const oldMesh = mapMeshByTopic.get(topic);
  if (oldMesh) {
    clearThreeObject(oldMesh);
  }
  mapTextureByTopic.get(topic)?.dispose();

  const geometry = new THREE.PlaneGeometry(width * resolution, height * resolution);
  const material = new THREE.MeshBasicMaterial({
    map: texture,
    transparent: true,
    opacity: mapOpacityForDisplay(display ?? {
      topic,
      messageType: "nav_msgs/msg/OccupancyGrid",
      kind: "map",
      label: topic,
    }),
    side: THREE.DoubleSide,
    depthWrite: false,
    polygonOffset: true,
    polygonOffsetFactor: 1,
    polygonOffsetUnits: 1,
  });
  const plane = new THREE.Mesh(geometry, material);
  plane.position.set((width * resolution) / 2, (height * resolution) / 2, -0.05);

  const root = new THREE.Group();
  root.position.set(originX, originY, originZ);
  root.quaternion.set(
    Number(originRotation.x ?? 0),
    Number(originRotation.y ?? 0),
    Number(originRotation.z ?? 0),
    Number(originRotation.w ?? 1)
  );
  root.add(plane);
  sourceFrameByTopic.set(topic, normalizeFrameId(message?.header?.frame_id));
  sourceStampMsByTopic.set(topic, extractHeaderStampMs(message));
  cacheTopicLocalMatrix(topic, composeLocalMatrix(root.position.clone(), root.quaternion.clone()));
  applyObjectFrameTransform(topic, root, message?.header?.frame_id, sourceStampMsByTopic.get(topic) ?? null);

  scene.add(root);
  mapMeshByTopic.set(topic, root);
  mapTextureByTopic.set(topic, texture);
}

function renderPath(topic: string, message: any) {
  if (!scene) {
    return;
  }
  const display = getDisplayByTopic(topic);
  const poses = Array.isArray(message?.poses) ? message.poses : [];
  if (poses.length === 0) {
    return;
  }

  const points = poses.map((item: any) => {
    const position = item?.pose?.position ?? item?.position ?? {};
    return new THREE.Vector3(
      Number(position.x ?? 0),
      Number(position.y ?? 0),
      Number(position.z ?? 0) + 0.05
    );
  });

  const geometry = new THREE.BufferGeometry().setFromPoints(points);
  let line = pathLineByTopic.get(topic);
  if (!line) {
    const material = new THREE.LineBasicMaterial({ color: pathColorForDisplay(display ?? {
      topic,
      messageType: "nav_msgs/Path",
      kind: "path",
      label: topic,
    }), linewidth: 2 });
    line = new THREE.Line(geometry, material);
    scene.add(line);
    pathLineByTopic.set(topic, line);
  } else {
    replaceObjectGeometry(line, geometry);
    const material = line.material;
    if (material && !Array.isArray(material)) {
      material.color = new THREE.Color(pathColorForDisplay(display ?? {
        topic,
        messageType: "nav_msgs/Path",
        kind: "path",
        label: topic,
      }));
      material.needsUpdate = true;
    }
  }
  sourceFrameByTopic.set(topic, normalizeFrameId(message?.header?.frame_id));
  sourceStampMsByTopic.set(topic, extractHeaderStampMs(message));
  cacheTopicLocalMatrix(topic, composeLocalMatrix());
  applyObjectFrameTransform(topic, line, message?.header?.frame_id, sourceStampMsByTopic.get(topic) ?? null);
  line.visible = true;
}

/**
 * 功能说明：
 * 将 SCAN 的 B-spline 控制点消息近似采样为折线，便于在主视图快速核对局部规划轨迹。
 *
 * 注意事项：
 * 1. 这里优先保证调试可视化，不追求和规划器内部 De Boor 求值完全一致。
 * 2. 若 knots 异常或控制点太少，则自动退化为控制点折线，避免页面无显示。
 */
function sampleBsplinePositions(message: any) {
  const controlPoints = Array.isArray(message?.pos_pts) ? message.pos_pts : [];
  const order = Math.max(1, Math.round(Number(message?.order ?? 0) || 0));
  if (controlPoints.length <= 0) {
    return [];
  }
  if (controlPoints.length <= 2 || order <= 1) {
    return controlPoints.flatMap((point: any) => [Number(point?.x ?? 0), Number(point?.y ?? 0), Number(point?.z ?? 0)]);
  }

  const degree = Math.max(1, order - 1);
  const knots = Array.isArray(message?.knots)
    ? message.knots.map((value: unknown) => Number(value)).filter((value: number) => Number.isFinite(value))
    : [];
  const expectedKnotCount = controlPoints.length + order;
  if (knots.length < expectedKnotCount) {
    return controlPoints.flatMap((point: any) => [Number(point?.x ?? 0), Number(point?.y ?? 0), Number(point?.z ?? 0)]);
  }

  const start = knots[Math.min(degree, knots.length - 1)];
  const end = knots[Math.max(degree, knots.length - degree - 1)];
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) {
    return controlPoints.flatMap((point: any) => [Number(point?.x ?? 0), Number(point?.y ?? 0), Number(point?.z ?? 0)]);
  }

  const points = controlPoints.map((point: any) => new THREE.Vector3(
    Number(point?.x ?? 0),
    Number(point?.y ?? 0),
    Number(point?.z ?? 0),
  ));
  const sampleCount = Math.max(24, Math.min(240, controlPoints.length * 12));
  const positions: number[] = [];

  function findSpan(t: number) {
    let low = degree;
    let high = points.length;
    let mid = Math.floor((low + high) / 2);
    while (t < knots[mid] || t >= knots[mid + 1]) {
      if (t < knots[mid]) {
        high = mid;
      } else {
        low = mid;
      }
      mid = Math.floor((low + high) / 2);
    }
    return mid;
  }

  function evaluatePoint(t: number) {
    const clampedT = Math.min(end - 1e-6, Math.max(start, t));
    const span = findSpan(clampedT);
    const work = Array.from({ length: degree + 1 }, (_, index) => points[span - degree + index].clone());
    for (let level = 1; level <= degree; level += 1) {
      for (let index = degree; index >= level; index -= 1) {
        const knotLeft = knots[span - degree + index];
        const knotRight = knots[span + 1 + index - level];
        const denominator = knotRight - knotLeft;
        const alpha = denominator > 1e-6 ? (clampedT - knotLeft) / denominator : 0;
        work[index].lerp(work[index - 1], 1 - alpha);
      }
    }
    return work[degree];
  }

  for (let index = 0; index < sampleCount; index += 1) {
    const ratio = sampleCount === 1 ? 0 : index / (sampleCount - 1);
    const point = evaluatePoint(start + (end - start) * ratio);
    positions.push(point.x, point.y, point.z);
  }
  return positions;
}

function renderBspline(display: NavViewerDisplay, message: any) {
  const topic = display.topic;
  const sampledPositions = sampleBsplinePositions(message);
  if (sampledPositions.length < 6) {
    return;
  }
  const latestDisplay = getDisplayByTopic(topic) || display;
  let line = pathLineByTopic.get(topic);
  if (!line) {
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.Float32BufferAttribute(sampledPositions, 3));
    const material = new THREE.LineBasicMaterial({ color: pathColorForDisplay(latestDisplay) });
    line = new THREE.Line(geometry, material);
    scene?.add(line);
    pathLineByTopic.set(topic, line);
  } else {
    replaceObjectGeometry(line, new THREE.BufferGeometry().setAttribute("position", new THREE.Float32BufferAttribute(sampledPositions, 3)));
    const material = line.material;
    if (material && !Array.isArray(material)) {
      material.color = new THREE.Color(pathColorForDisplay(latestDisplay));
      material.needsUpdate = true;
    }
  }
  sourceFrameByTopic.set(topic, normalizeFrameId(message?.header?.frame_id) || currentFixedFrame());
  sourceStampMsByTopic.set(topic, extractHeaderStampMs(message));
  cacheTopicLocalMatrix(topic, composeLocalMatrix());
  applyObjectFrameTransform(topic, line, sourceFrameByTopic.get(topic), sourceStampMsByTopic.get(topic) ?? null);
  line.visible = true;
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

function pointColorForTopic(topic: string) {
  if (topic.includes("loaded_pointcloud_map")) {
    return "#d7dee8";
  }
  if (topic.includes("points_aligned")) {
    return "#31d28a";
  }
  if (topic.includes("cloud_registered_bl")) {
    return "#2f8cff";
  }
  if (topic.includes("cloud_registered_body")) {
    return "#f6a237";
  }
  return "#ffffff";
}

/**
 * 功能说明：
 * 基于点的高度和水平离散度生成轻量级顶点颜色，
 * 在不引入屏幕后处理的前提下增强点云的形状辨识度。
 *
 * 注意事项：
 * 1. 保留显示项主色，障碍物只在主色和补色之间做受控过渡，避免颜色体系失控。
 * 2. 高度分层基于点云自身的中位高度参考面，而不是简单依赖世界坐标 z 的全局范围。
 * 3. 为了避免每帧全量排序，统计只使用固定上限采样点估计参考面和局部范围。
 */
function buildPointCloudColorBuffer(positions: number[], baseColorText: string) {
  const pointCount = Math.floor(positions.length / 3);
  const colors = new Float32Array(pointCount * 3);
  if (pointCount <= 0) {
    return colors;
  }

  const statsSampleCount = Math.min(pointCount, 1024);
  const statsSampleStep = Math.max(1, Math.floor(pointCount / statsSampleCount));
  const zSamples: number[] = [];
  for (let index = 0; index < positions.length; index += 3) {
    const z = positions[index + 2];
    if (((index / 3) % statsSampleStep) === 0 && zSamples.length < statsSampleCount) {
      zSamples.push(z);
    }
  }

  const baseColor = new THREE.Color(baseColorText);
  const baseHsl = { h: 0, s: 0, l: 0 };
  baseColor.getHSL(baseHsl);
  const sortedZValues = [...zSamples].sort((left, right) => left - right);
  const medianIndex = Math.floor(sortedZValues.length / 2);
  const medianZ = sortedZValues[medianIndex];
  const upperQuartileZ = sortedZValues[Math.min(sortedZValues.length - 1, Math.floor(sortedZValues.length * 0.75))];
  const upperReferenceRange = Math.max(0.08, upperQuartileZ - medianZ, sortedZValues[sortedZValues.length - 1] - medianZ);
  const complementaryColor = new THREE.Color().setHSL(
    (baseHsl.h + 0.5) % 1,
    Math.min(1, Math.max(0.45, baseHsl.s * 0.95 + 0.06)),
    Math.min(0.68, Math.max(0.26, baseHsl.l * 0.9)),
  );
  const color = new THREE.Color();

  for (let pointIndex = 0, index = 0; index < positions.length; index += 3, pointIndex += 1) {
    const z = positions[index + 2];
    const relativeHeight = (z - medianZ) / upperReferenceRange;
    const positiveHeightRatio = Math.min(1, Math.max(0, relativeHeight));
    const negativeHeightRatio = Math.min(1, Math.max(0, -relativeHeight * 0.45));
    const obstacleBlend = positiveHeightRatio * positiveHeightRatio;
    color.copy(baseColor).lerp(complementaryColor, Math.min(0.82, obstacleBlend * 0.78));
    const currentHsl = color.getHSL({ h: 0, s: 0, l: 0 });
    const saturation = Math.min(1, Math.max(0.38, currentHsl.s + obstacleBlend * 0.08 - negativeHeightRatio * 0.04));
    const lightness = Math.min(0.72, Math.max(0.24, currentHsl.l - obstacleBlend * 0.06 - negativeHeightRatio * 0.02));
    color.setHSL(currentHsl.h, saturation, lightness);
    const offset = pointIndex * 3;
    colors[offset] = color.r;
    colors[offset + 1] = color.g;
    colors[offset + 2] = color.b;
  }
  return colors;
}

function extractCustomPointCloudPositions(message: any) {
  const points = Array.isArray(message?.points) ? message.points : [];
  if (points.length === 0) {
    return [];
  }
  const sampleStep = Math.max(1, Math.ceil(points.length / 18000));
  const positions: number[] = [];
  for (let index = 0; index < points.length; index += sampleStep) {
    const point = points[index] as Record<string, unknown> | null;
    const x = Number(point?.x ?? Number.NaN);
    const y = Number(point?.y ?? Number.NaN);
    const z = Number(point?.z ?? Number.NaN);
    if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(z)) {
      continue;
    }
    positions.push(x, y, z);
  }
  return positions;
}

function extractPointCloud2Positions(message: any) {
  const fields = Array.isArray(message?.fields) ? message.fields : [];
  const pointStep = Number(message?.point_step ?? 0);
  const width = Number(message?.width ?? 0);
  const height = Number(message?.height ?? 1);
  const bytes = normalizePointCloudBytes(message?.data);
  if (pointStep <= 0 || width <= 0 || !bytes || bytes.byteLength < pointStep) {
    return [];
  }

  const xOffset = resolveFieldOffset(fields, "x");
  const yOffset = resolveFieldOffset(fields, "y");
  const zOffset = resolveFieldOffset(fields, "z");
  if (xOffset < 0 || yOffset < 0 || zOffset < 0) {
    return [];
  }

  const totalPoints = width * Math.max(1, height);
  const sampleStep = Math.max(1, Math.ceil(totalPoints / 18000));
  const positions: number[] = [];
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);

  for (let index = 0; index < totalPoints; index += sampleStep) {
    const base = index * pointStep;
    if (base + pointStep > bytes.byteLength) {
      break;
    }

    const x = view.getFloat32(base + xOffset, true);
    const y = view.getFloat32(base + yOffset, true);
    const z = view.getFloat32(base + zOffset, true);
    if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(z)) {
      continue;
    }
    positions.push(x, y, z);
  }
  return positions;
}

function renderPointCloud(display: NavViewerDisplay, message: any) {
  if (!scene) {
    return;
  }
  const latestDisplay = getDisplayByTopic(display.topic) || display;
  const topic = latestDisplay.topic;
  const positions = Array.isArray(message?.points)
    ? extractCustomPointCloudPositions(message)
    : extractPointCloud2Positions(message);
  if (positions.length === 0) {
    return;
  }
  const useLayeredColors = pointColorModeForDisplay(latestDisplay) === "layered";
  const pointColors = useLayeredColors ? buildPointCloudColorBuffer(positions, pointColorForDisplay(latestDisplay)) : null;

  let points = pointCloudByTopic.get(topic);
  if (!points) {
    const geometry = new THREE.BufferGeometry();
    const attribute = new THREE.Float32BufferAttribute(positions, 3);
    attribute.setUsage(THREE.DynamicDrawUsage);
    geometry.setAttribute("position", attribute);
    if (pointColors) {
      geometry.setAttribute("color", new THREE.BufferAttribute(pointColors, 3));
    }
    geometry.computeBoundingSphere();
    const material = new THREE.PointsMaterial({
      color: useLayeredColors ? "#ffffff" : pointColorForDisplay(latestDisplay),
      size: safePointCloudSize(latestDisplay),
      sizeAttenuation: true,
      vertexColors: useLayeredColors,
      transparent: true,
      opacity: 0.96,
      depthWrite: true,
      depthTest: true,
    });
    points = new THREE.Points(geometry, material);
    scene.add(points);
    pointCloudByTopic.set(topic, points);
  } else {
    const geometry = points.geometry;
    const existingAttribute = geometry.getAttribute("position");
    const existingColorAttribute = geometry.getAttribute("color");
    const nextPointCount = positions.length / 3;
    if (
      existingAttribute
      && existingAttribute instanceof THREE.BufferAttribute
      && existingAttribute.itemSize === 3
      && existingAttribute.array.length === positions.length
    ) {
      (existingAttribute.array as Float32Array).set(positions);
      existingAttribute.needsUpdate = true;
      existingAttribute.count = nextPointCount;
      geometry.setDrawRange(0, nextPointCount);
    } else {
      const nextAttribute = new THREE.Float32BufferAttribute(positions, 3);
      nextAttribute.setUsage(THREE.DynamicDrawUsage);
      geometry.setAttribute("position", nextAttribute);
      geometry.setDrawRange(0, nextPointCount);
    }
    if (pointColors) {
      if (
        existingColorAttribute
        && existingColorAttribute instanceof THREE.BufferAttribute
        && existingColorAttribute.itemSize === 3
        && existingColorAttribute.array.length === pointColors.length
      ) {
        (existingColorAttribute.array as Float32Array).set(pointColors);
        existingColorAttribute.needsUpdate = true;
        existingColorAttribute.count = nextPointCount;
      } else {
        geometry.setAttribute("color", new THREE.BufferAttribute(pointColors, 3));
      }
    } else {
      if (existingColorAttribute) {
        geometry.deleteAttribute("color");
      }
    }
    geometry.computeBoundingSphere();
    const material = points.material;
    if (material && !Array.isArray(material)) {
      material.color = new THREE.Color(useLayeredColors ? "#ffffff" : pointColorForDisplay(latestDisplay));
      material.size = safePointCloudSize(latestDisplay);
      material.vertexColors = useLayeredColors;
      material.opacity = 0.96;
      material.transparent = true;
      material.depthWrite = true;
      material.depthTest = true;
      material.needsUpdate = true;
    }
  }
  sourceFrameByTopic.set(topic, normalizeFrameId(message?.header?.frame_id));
  sourceStampMsByTopic.set(topic, extractHeaderStampMs(message));
  cacheTopicLocalMatrix(topic, composeLocalMatrix());
  applyObjectFrameTransform(topic, points, message?.header?.frame_id, sourceStampMsByTopic.get(topic) ?? null);
  points.visible = true;
}

function clearInteractionPreview() {
  if (interactionPreviewGroup) {
    clearThreeObject(interactionPreviewGroup);
    interactionPreviewGroup = null;
  }
}

function buildInteractionPreview(startPoint: THREE.Vector3, endPoint: THREE.Vector3) {
  if (!scene) {
    return;
  }

  clearInteractionPreview();
  const group = new THREE.Group();
  const deltaX = endPoint.x - startPoint.x;
  const deltaY = endPoint.y - startPoint.y;
  const yaw = Math.atan2(deltaY, deltaX || 1e-6);
  const length = Math.max(0.25, Math.hypot(deltaX, deltaY));

  const anchor = new THREE.Mesh(
    new THREE.CircleGeometry(0.12, 20),
    new THREE.MeshBasicMaterial({ color: currentInteractionMode.value === "initialpose" ? "#31d28a" : "#f6a237" })
  );
  anchor.position.set(startPoint.x, startPoint.y, 0.02);
  group.add(anchor);

  const arrow = new THREE.ArrowHelper(
    new THREE.Vector3(Math.cos(yaw), Math.sin(yaw), 0),
    new THREE.Vector3(startPoint.x, startPoint.y, 0.05),
    length,
    currentInteractionMode.value === "initialpose" ? "#31d28a" : "#f6a237",
    0.26,
    0.14
  );
  group.add(arrow);

  scene.add(group);
  interactionPreviewGroup = group;
}

function worldPointFromPointer(event: Pick<PointerEvent, "clientX" | "clientY">) {
  if (!camera || !renderer) {
    return null;
  }
  const rect = renderer.domElement.getBoundingClientRect();
  const x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
  const y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
  raycaster.setFromCamera({ x, y }, camera);
  const point = new THREE.Vector3();
  const hit = raycaster.ray.intersectPlane(interactionPlane, point);
  return hit ? point.clone() : null;
}

function handlePointerDown(event: PointerEvent) {
  if (currentInteractionMode.value === "none") {
    return;
  }
  if (event.pointerType === "mouse" && event.button !== 0) {
    return;
  }
  const point = worldPointFromPointer(event);
  if (!point) {
    return;
  }
  activeInteractionPointerId = event.pointerId;
  interactionStartPoint = point;
  interactionCurrentPoint = point.clone();
  renderer?.domElement.setPointerCapture(event.pointerId);
  syncControlLockState();
  buildInteractionPreview(interactionStartPoint, interactionCurrentPoint);
  event.preventDefault();
}

function handlePointerMove(event: PointerEvent) {
  if (!interactionStartPoint || currentInteractionMode.value === "none" || activeInteractionPointerId !== event.pointerId) {
    return;
  }
  const point = worldPointFromPointer(event);
  if (!point) {
    return;
  }
  interactionCurrentPoint = point;
  buildInteractionPreview(interactionStartPoint, interactionCurrentPoint);
}

function finishInteraction(emitResult: boolean) {
  if (!interactionStartPoint) {
    return;
  }
  const endPoint = interactionCurrentPoint || interactionStartPoint.clone();
  const deltaX = endPoint.x - interactionStartPoint.x;
  const deltaY = endPoint.y - interactionStartPoint.y;
  const yaw = Math.atan2(deltaY, deltaX || 1e-6);
  const mode = currentInteractionMode.value;
  const targetX = interactionStartPoint.x;
  const targetY = interactionStartPoint.y;
  clearInteractionPreview();
  interactionStartPoint = null;
  interactionCurrentPoint = null;
  activeInteractionPointerId = null;
  syncControlLockState();

  if (!emitResult || mode === "none") {
    return;
  }
  emit("interactionComplete", {
    mode,
    x: targetX,
    y: targetY,
    yaw,
  });
}

function handlePointerUp(event: PointerEvent) {
  if (activeInteractionPointerId !== event.pointerId) {
    return;
  }
  renderer?.domElement.releasePointerCapture(event.pointerId);
  finishInteraction(true);
}

function handlePointerCancel(event?: PointerEvent) {
  if (event && activeInteractionPointerId !== event.pointerId) {
    return;
  }
  if (event) {
    renderer?.domElement.releasePointerCapture(event.pointerId);
  }
  if (!interactionStartPoint) {
    return;
  }
  finishInteraction(false);
}

function quaternionToYaw(rotation: any) {
  const x = Number(rotation?.x ?? 0);
  const y = Number(rotation?.y ?? 0);
  const z = Number(rotation?.z ?? 0);
  const w = Number(rotation?.w ?? 1);
  const sinyCosp = 2 * (w * z + x * y);
  const cosyCosp = 1 - 2 * (y * y + z * z);
  return Math.atan2(sinyCosp, cosyCosp);
}

function formatHudCoordinate(value: number) {
  return Number.isFinite(value) ? value.toFixed(3) : "-";
}

function updateBaseLinkHud() {
  if (connectionLabel.value !== "已连接") {
    baseLinkHudText.value = "等待 rosbridge 连接";
    return;
  }

  const baseLinkTransform = resolveFrameTransformToFixed("base_link");
  if (baseLinkTransform) {
    const position = new THREE.Vector3();
    const quaternion = new THREE.Quaternion();
    const scale = new THREE.Vector3();
    baseLinkTransform.decompose(position, quaternion, scale);
    baseLinkHudText.value = [
      `frame: ${currentFixedFrame()} <- base_link`,
      `x: ${formatHudCoordinate(position.x)}`,
      `y: ${formatHudCoordinate(position.y)}`,
      `z: ${formatHudCoordinate(position.z)}`,
      `yaw: ${formatHudCoordinate(quaternionToYaw(quaternion))} rad`,
    ].join(" | ");
    return;
  }

  const poseAnchor = resolvePrimaryPoseAnchor();
  if (poseAnchor) {
    baseLinkHudText.value = [
      `frame: ${poseAnchor.frameId}`,
      `x: ${formatHudCoordinate(poseAnchor.x)}`,
      `y: ${formatHudCoordinate(poseAnchor.y)}`,
      `z: ${formatHudCoordinate(poseAnchor.z)}`,
      `yaw: ${formatHudCoordinate(poseAnchor.yaw)} rad`,
      "来源: pose",
    ].join(" | ");
    return;
  }

  baseLinkHudText.value = "base_link 位姿暂不可用";
}

function createCircleLine(radius: number, color: string, dashed = false) {
  const points: THREE.Vector3[] = [];
  const segments = 96;
  for (let index = 0; index <= segments; index += 1) {
    const angle = (index / segments) * Math.PI * 2;
    points.push(new THREE.Vector3(Math.cos(angle) * radius, Math.sin(angle) * radius, 0.03));
  }
  const geometry = new THREE.BufferGeometry().setFromPoints(points);
  const material = dashed
    ? new THREE.LineDashedMaterial({ color, dashSize: 0.22, gapSize: 0.12, transparent: true, opacity: 0.9 })
    : new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.95 });
  const line = new THREE.LineLoop(geometry, material);
  if (line instanceof THREE.Line && "computeLineDistances" in line) {
    line.computeLineDistances();
  }
  return line;
}

function createIgnoreZoneOutline() {
  const { xMin, xMax, yMin, yMax } = OBSTACLE_ZONE_DEFAULTS.ignoreZone;
  const points = [
    new THREE.Vector3(xMin, yMin, 0.035),
    new THREE.Vector3(xMax, yMin, 0.035),
    new THREE.Vector3(xMax, yMax, 0.035),
    new THREE.Vector3(xMin, yMax, 0.035),
  ];
  const geometry = new THREE.BufferGeometry().setFromPoints(points);
  return new THREE.LineLoop(
    geometry,
    new THREE.LineBasicMaterial({ color: "#8ea1ba", transparent: true, opacity: 0.88 })
  );
}

function obstacleStateFromMessage(message: any): ObstacleZoneState {
  const rawValue = typeof message?.data === "number"
    ? message.data
    : typeof message?.data === "string"
      ? Number(message.data)
      : typeof message?.state === "number"
        ? message.state
        : Number.NaN;
  const code = Number.isFinite(rawValue) ? Math.max(0, Math.min(2, Math.round(rawValue))) : 0;
  if (code === 2) {
    return { code, label: "danger_zone" };
  }
  if (code === 1) {
    return { code, label: "calm_zone" };
  }
  return { code: 0, label: "clear" };
}

function resolvePrimaryPoseAnchor() {
  const poseDisplays = props.displays.filter((display) => display.kind === "pose");
  if (poseDisplays.length === 0) {
    return null;
  }
  const preferredDisplay = poseDisplays
    .slice()
    .sort((left, right) => {
      const leftScore = left.topic.includes("ndt_pose") ? 0 : left.topic.includes("pose") ? 1 : 2;
      const rightScore = right.topic.includes("ndt_pose") ? 0 : right.topic.includes("pose") ? 1 : 2;
      if (leftScore !== rightScore) {
        return leftScore - rightScore;
      }
      return left.topic.localeCompare(right.topic, "zh-CN");
    })
    .find((display) => poseAnchorByTopic.has(display.topic));
  return preferredDisplay ? poseAnchorByTopic.get(preferredDisplay.topic) ?? null : null;
}

function resolveNdtPoseAnchor() {
  const preferredTopic = props.displays
    .filter((display) => display.kind === "pose" && display.topic.includes("ndt_pose"))
    .map((display) => display.topic)
    .find((topic) => poseAnchorByTopic.has(topic));
  if (!preferredTopic) {
    return null;
  }
  return poseAnchorByTopic.get(preferredTopic) ?? null;
}

function focusCameraOnAnchor(anchor: NavPoseAnchor) {
  if (!camera || !controls) {
    return { ok: false, message: "三维主视图尚未初始化。" };
  }
  const transformMatrix = resolveFrameTransformToFixed(anchor.frameId, null);
  if (!transformMatrix) {
    return { ok: false, message: `缺少 ${anchor.frameId} 到 ${currentFixedFrame()} 的 TF，无法聚焦定位位姿。` };
  }

  const target = new THREE.Vector3(anchor.x, anchor.y, anchor.z);
  target.applyMatrix4(transformMatrix);

  const currentOffset = camera.position.clone().sub(controls.target);
  const currentDistance = currentOffset.length();
  const desiredDistance = Number.isFinite(currentDistance) ? Math.max(2, currentDistance) : 8;
  const currentHorizontalRadius = currentOffset.clone().setZ(0).length();
  const fallbackHorizontalRadius = Math.min(desiredDistance * 0.42, Math.max(0.9, desiredDistance * 0.22));
  const horizontalRadius = Math.min(
    Math.max(currentHorizontalRadius, fallbackHorizontalRadius),
    Math.max(0.9, desiredDistance * 0.92)
  );
  const verticalDistance = Math.sqrt(Math.max(0.36, (desiredDistance * desiredDistance) - (horizontalRadius * horizontalRadius)));

  const frameRotation = new THREE.Quaternion();
  const framePosition = new THREE.Vector3();
  const frameScale = new THREE.Vector3();
  transformMatrix.decompose(framePosition, frameRotation, frameScale);
  const poseRotation = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), anchor.yaw);
  const worldPoseRotation = frameRotation.clone().multiply(poseRotation);
  const poseForward = new THREE.Vector3(1, 0, 0).applyQuaternion(worldPoseRotation).setZ(0);
  const horizontalDirection = poseForward.lengthSq() > 1e-6 ? poseForward.normalize().multiplyScalar(-horizontalRadius) : new THREE.Vector3(-horizontalRadius, 0, 0);
  const nextOffset = new THREE.Vector3(horizontalDirection.x, horizontalDirection.y, Math.max(0.6, verticalDistance));

  camera.up.set(0, 0, 1);
  camera.position.copy(target.clone().add(nextOffset));
  controls.target.copy(target);
  camera.lookAt(target);
  camera.updateProjectionMatrix();
  controls.update();

  sceneStatus.value = `镜头已对准定位位姿: ${anchor.topic}`;
  return { ok: true, message: `镜头已移动到 ${anchor.topic} 上方。` };
}

function focusOnNdtPose() {
  const anchor = resolveNdtPoseAnchor();
  if (!anchor) {
    return { ok: false, message: "当前还没有收到 /ndt_pose 的有效位姿，暂时无法定位镜头。" };
  }
  return focusCameraOnAnchor(anchor);
}

function handleFocusButtonClick() {
  focusOnNdtPose();
}

function applyObstacleZoneStyle(group: THREE.Group, state: ObstacleZoneState) {
  const detectionRing = group.getObjectByName("detection-ring") as THREE.Line | null;
  const calmRing = group.getObjectByName("calm-ring") as THREE.Line | null;
  const dangerRing = group.getObjectByName("danger-ring") as THREE.Line | null;
  const calmFill = group.getObjectByName("calm-fill") as THREE.Mesh | null;
  const dangerFill = group.getObjectByName("danger-fill") as THREE.Mesh | null;

  const calmActive = state.code === 1;
  const dangerActive = state.code === 2;

  (detectionRing?.material as THREE.Material | undefined)?.setValues?.({
    opacity: dangerActive ? 0.98 : calmActive ? 0.92 : 0.72,
  });
  (calmRing?.material as THREE.Material | undefined)?.setValues?.({
    color: calmActive ? "#ffe178" : "#e4c45d",
    opacity: calmActive ? 1 : 0.76,
  });
  (dangerRing?.material as THREE.Material | undefined)?.setValues?.({
    color: dangerActive ? "#ff5f76" : "#df6b84",
    opacity: dangerActive ? 1 : 0.78,
  });
  (calmFill?.material as THREE.Material | undefined)?.setValues?.({
    opacity: calmActive ? 0.2 : 0.1,
    color: calmActive ? "#ffe178" : "#f1cf6a",
  });
  (dangerFill?.material as THREE.Material | undefined)?.setValues?.({
    opacity: dangerActive ? 0.26 : 0.1,
    color: dangerActive ? "#ff5f76" : "#ff7f94",
  });
}

function buildObstacleZoneGroup(state: ObstacleZoneState) {
  const group = new THREE.Group();

  const detectionRing = createCircleLine(OBSTACLE_ZONE_DEFAULTS.detectionRange, "#5c88bc", true);
  detectionRing.name = "detection-ring";
  group.add(detectionRing);

  const calmFill = new THREE.Mesh(
    new THREE.CircleGeometry(OBSTACLE_ZONE_DEFAULTS.calmRadius, 72),
    new THREE.MeshBasicMaterial({ color: "#f1cf6a", transparent: true, opacity: 0.1, side: THREE.DoubleSide, depthWrite: false })
  );
  calmFill.name = "calm-fill";
  calmFill.position.z = 0.015;
  group.add(calmFill);

  const calmRing = createCircleLine(OBSTACLE_ZONE_DEFAULTS.calmRadius, "#e4c45d");
  calmRing.name = "calm-ring";
  group.add(calmRing);

  const dangerFill = new THREE.Mesh(
    new THREE.CircleGeometry(OBSTACLE_ZONE_DEFAULTS.dangerRadius, 72),
    new THREE.MeshBasicMaterial({ color: "#ff7f94", transparent: true, opacity: 0.1, side: THREE.DoubleSide, depthWrite: false })
  );
  dangerFill.name = "danger-fill";
  dangerFill.position.z = 0.02;
  group.add(dangerFill);

  const dangerRing = createCircleLine(OBSTACLE_ZONE_DEFAULTS.dangerRadius, "#df6b84");
  dangerRing.name = "danger-ring";
  group.add(dangerRing);

  const ignoreOutline = createIgnoreZoneOutline();
  ignoreOutline.name = "ignore-zone";
  group.add(ignoreOutline);

  applyObstacleZoneStyle(group, state);
  return group;
}

function refreshAllObstacleZones() {
  props.displays
    .filter((display) => display.kind === "obstacle_zone")
    .forEach((display) => {
      const latestMessage = latestMessageByTopic.get(display.topic);
      if (latestMessage) {
        renderObstacleZone(display.topic, latestMessage);
      }
    });
}

function renderPose(topic: string, message: any) {
  if (!scene) {
    return;
  }
  const pose = message?.pose?.pose ?? message?.pose ?? {};
  const position = pose?.position ?? {};
  const orientation = pose?.orientation ?? {};
  const yaw = quaternionToYaw(orientation);
  const frameId = normalizeFrameId(message?.header?.frame_id) || currentFixedFrame();
  const display = getDisplayByTopic(topic) ?? {
    topic,
    messageType: "geometry_msgs/msg/PoseStamped",
    kind: "pose" as const,
    label: topic,
  };

  let group = poseObjectByTopic.get(topic) as THREE.Group | undefined;
  if (!group) {
    group = new THREE.Group();
    group.add(createPoseMarker(poseColorForDisplay(display), 1));
    scene.add(group);
    poseObjectByTopic.set(topic, group);
  }

  const marker = group.children[0] as THREE.Group | undefined;
  const body = marker?.getObjectByName("pose-body") as THREE.Mesh | null;
  if (body) {
    body.rotation.z = yaw - Math.PI / 2;
    body.position.set(Number(position.x ?? 0), Number(position.y ?? 0), 0.34);
  }
  const tail = marker?.getObjectByName("pose-tail") as THREE.Mesh | null;
  if (tail) {
    tail.position.set(Number(position.x ?? 0), Number(position.y ?? 0), 0.02);
  }

  sourceFrameByTopic.set(topic, frameId);
  sourceStampMsByTopic.set(topic, extractHeaderStampMs(message));
  cacheTopicLocalMatrix(topic, composeLocalMatrix());
  applyObjectFrameTransform(topic, group, frameId, sourceStampMsByTopic.get(topic) ?? null);
  group.visible = true;
  poseAnchorByTopic.set(topic, {
    topic,
    frameId,
    x: Number(position.x ?? 0),
    y: Number(position.y ?? 0),
    z: Number(position.z ?? 0),
    yaw,
  });
  refreshAllObstacleZones();
  updateBaseLinkHud();
}

function createPoseMarker(color: string, scale: number) {
  const marker = new THREE.Group();
  const body = new THREE.Mesh(
    new THREE.ConeGeometry(0.22 * scale, 0.68 * scale, 18),
    new THREE.MeshStandardMaterial({ color })
  );
  body.name = "pose-body";
  marker.add(body);

  const tail = new THREE.Mesh(
    new THREE.CircleGeometry(0.12 * scale, 16),
    new THREE.MeshBasicMaterial({ color })
  );
  tail.name = "pose-tail";
  marker.add(tail);
  return marker;
}

function renderPoseArray(topic: string, message: any) {
  if (!scene) {
    return;
  }
  const poses = Array.isArray(message?.poses) ? message.poses : [];
  const frameId = normalizeFrameId(message?.header?.frame_id) || currentFixedFrame();
  const display = getDisplayByTopic(topic) ?? {
    topic,
    messageType: "geometry_msgs/msg/PoseArray",
    kind: "pose_array" as const,
    label: topic,
  };

  let group = poseObjectByTopic.get(topic) as THREE.Group | undefined;
  if (!group) {
    group = new THREE.Group();
    scene.add(group);
    poseObjectByTopic.set(topic, group);
  }
  while (group.children.length > poses.length) {
    const child = group.children.pop();
    if (child) {
      clearThreeObject(child);
    }
  }
  while (group.children.length < poses.length) {
    group.add(createPoseMarker(poseColorForDisplay(display), 0.72));
  }

  poses.forEach((pose: any, index: number) => {
    const position = pose?.position ?? {};
    const orientation = pose?.orientation ?? {};
    const yaw = quaternionToYaw(orientation);
    const marker = group!.children[index] as THREE.Group;
    marker.visible = true;
    const body = marker.getObjectByName("pose-body") as THREE.Mesh | null;
    if (body) {
      body.rotation.z = yaw - Math.PI / 2;
      body.position.set(Number(position.x ?? 0), Number(position.y ?? 0), 0.25);
    }
    const tail = marker.getObjectByName("pose-tail") as THREE.Mesh | null;
    if (tail) {
      tail.position.set(Number(position.x ?? 0), Number(position.y ?? 0), 0.018);
    }
  });

  sourceFrameByTopic.set(topic, frameId);
  sourceStampMsByTopic.set(topic, extractHeaderStampMs(message));
  cacheTopicLocalMatrix(topic, composeLocalMatrix());
  applyObjectFrameTransform(topic, group, frameId, sourceStampMsByTopic.get(topic) ?? null);
  group.visible = true;
  updateBaseLinkHud();
}

function buildTfLabelSprite(label: string, sizeScale: number) {
  const canvas = document.createElement("canvas");
  const context = canvas.getContext("2d");
  if (!context) {
    return null;
  }
  const fontSize = 28;
  context.font = `600 ${fontSize}px sans-serif`;
  const metrics = context.measureText(label);
  const width = Math.max(96, Math.ceil(metrics.width + 28));
  const height = 48;
  canvas.width = width;
  canvas.height = height;

  const drawContext = canvas.getContext("2d");
  if (!drawContext) {
    return null;
  }
  drawContext.font = `600 ${fontSize}px sans-serif`;
  drawContext.fillStyle = "rgba(8, 17, 29, 0.82)";
  drawContext.strokeStyle = "rgba(47, 140, 255, 0.42)";
  drawContext.lineWidth = 2;
  drawContext.beginPath();
  drawContext.roundRect(1, 1, width - 2, height - 2, 10);
  drawContext.fill();
  drawContext.stroke();
  drawContext.fillStyle = "#f5f8ff";
  drawContext.fillText(label, 14, 32);

  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  const material = new THREE.SpriteMaterial({
    map: texture,
    transparent: true,
    depthWrite: false,
  });
  const sprite = new THREE.Sprite(material);
  sprite.scale.set(sizeScale * (width / 80), sizeScale * (height / 80), 1);
  return sprite;
}

function ensureTfFrameNode(topic: string, frameName: string, display: NavViewerDisplay | null) {
  let frameNodeMap = tfFrameNodeCacheByTopic.get(topic);
  if (!frameNodeMap) {
    frameNodeMap = new Map<string, THREE.Group>();
    tfFrameNodeCacheByTopic.set(topic, frameNodeMap);
  }
  let frameNode = frameNodeMap.get(frameName);
  if (frameNode) {
    return frameNode;
  }

  frameNode = new THREE.Group();
  frameNode.name = `tf-frame-${frameName}`;

  const axes = new THREE.AxesHelper(0.6);
  axes.name = "tf-axes";
  frameNode.add(axes);

  const point = new THREE.Mesh(
    new THREE.SphereGeometry(0.06, 12, 12),
    new THREE.MeshBasicMaterial({ color: "#8ea1ba" })
  );
  point.name = "tf-point";
  frameNode.add(point);

  if (display?.tfShowNames !== false) {
    const label = buildTfLabelSprite(frameName, safeTfLabelSize(display));
    if (label) {
      label.name = "tf-label";
      frameNode.add(label);
    }
  }

  frameNodeMap.set(frameName, frameNode);
  return frameNode;
}

function updateTfFrameNode(frameNode: THREE.Group, frameName: string, position: THREE.Vector3, quaternion: THREE.Quaternion, display: NavViewerDisplay | null) {
  frameNode.visible = true;
  const axes = frameNode.getObjectByName("tf-axes") as THREE.AxesHelper | null;
  if (axes) {
    axes.position.copy(position);
    axes.quaternion.copy(quaternion);
  }

  const point = frameNode.getObjectByName("tf-point") as THREE.Mesh | null;
  if (point) {
    point.position.copy(position);
  }

  const showNames = display?.tfShowNames !== false;
  let label = frameNode.getObjectByName("tf-label") as THREE.Sprite | null;
  if (!label && showNames) {
    label = buildTfLabelSprite(frameName, safeTfLabelSize(display ?? undefined as never));
    if (label) {
      label.name = "tf-label";
      frameNode.add(label);
    }
  }
  if (label) {
    label.visible = showNames;
    label.position.set(position.x, position.y, position.z + 0.22);
    const sizeScale = safeTfLabelSize(display ?? undefined as never);
    const texture = (label.material as THREE.SpriteMaterial | undefined)?.map;
    const width = texture?.image?.width ?? 80;
    const height = texture?.image?.height ?? 40;
    label.scale.set(sizeScale * (width / 80), sizeScale * (height / 80), 1);
  }
}

function renderTf(topic: string) {
  if (!scene) {
    return;
  }

  const display = getDisplayByTopic(topic);
  const visibleFrames = new Set(display?.tfVisibleFrames ?? []);
  const showAllFrames = visibleFrames.size === 0;
  let group = tfGroupByTopic.get(topic);
  if (!group) {
    group = new THREE.Group();
    scene.add(group);
    tfGroupByTopic.set(topic, group);
  }
  const frameNodeMap = tfFrameNodeCacheByTopic.get(topic) ?? new Map<string, THREE.Group>();
  const frames = tfFramesForTopic(topic)
    .filter((frameName) => showAllFrames || visibleFrames.has(frameName))
    .sort((left, right) => left.localeCompare(right, "zh-CN"));
  const activeFrames = new Set(frames);

  frameNodeMap.forEach((frameNode, frameName) => {
    if (!activeFrames.has(frameName)) {
      frameNode.visible = false;
    }
  });

  frames.forEach((frameName) => {
    const transformMatrix = resolveFrameTransformToFixed(frameName, null, topic);
    if (!transformMatrix) {
      const hiddenNode = frameNodeMap.get(frameName);
      if (hiddenNode) {
        hiddenNode.visible = false;
      }
      return;
    }
    const position = new THREE.Vector3();
    const quaternion = new THREE.Quaternion();
    const scale = new THREE.Vector3();
    transformMatrix.decompose(position, quaternion, scale);
    const frameNode = ensureTfFrameNode(topic, frameName, display);
    if (frameNode.parent !== group) {
      group.add(frameNode);
    }
    updateTfFrameNode(frameNode, frameName, position, quaternion, display);
  });
  group.visible = true;
}

function renderLaser(topic: string, message: any) {
  if (!scene) {
    return;
  }

  const ranges = Array.isArray(message?.ranges) ? message.ranges : [];
  const angleMin = Number(message?.angle_min ?? 0);
  const angleIncrement = Number(message?.angle_increment ?? 0);
  if (ranges.length === 0 || angleIncrement === 0) {
    return;
  }

  const positions: number[] = [];
  ranges.forEach((rangeValue: unknown, index: number) => {
    const range = Number(rangeValue);
    if (!Number.isFinite(range) || range <= 0) {
      return;
    }
    const angle = angleMin + angleIncrement * index;
    positions.push(Math.cos(angle) * range, Math.sin(angle) * range, 0.08);
  });
  const oldLaser = laserByTopic.get(topic);
  if (oldLaser) {
    clearThreeObject(oldLaser);
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  const material = new THREE.PointsMaterial({
    color: "#ffdd57",
    size: 0.05,
    sizeAttenuation: true,
  });
  const points = new THREE.Points(geometry, material);
  sourceFrameByTopic.set(topic, normalizeFrameId(message?.header?.frame_id));
  sourceStampMsByTopic.set(topic, extractHeaderStampMs(message));
  cacheTopicLocalMatrix(topic, composeLocalMatrix());
  applyObjectFrameTransform(topic, points, message?.header?.frame_id, sourceStampMsByTopic.get(topic) ?? null);
  scene.add(points);
  laserByTopic.set(topic, points);
}

function markerLifetimeMs(message: any) {
  const sec = Number(message?.lifetime?.sec ?? 0);
  const nanosec = Number(message?.lifetime?.nanosec ?? 0);
  if (!Number.isFinite(sec) || !Number.isFinite(nanosec)) {
    return 0;
  }
  return Math.max(0, sec * 1000 + nanosec / 1e6);
}

function markerColor(message: any, fallbackColor: string) {
  const alpha = Number(message?.color?.a ?? 1);
  const red = Number(message?.color?.r ?? Number.NaN);
  const green = Number(message?.color?.g ?? Number.NaN);
  const blue = Number(message?.color?.b ?? Number.NaN);
  if ([red, green, blue].every((value) => Number.isFinite(value))) {
    return {
      color: new THREE.Color(
        Math.min(1, Math.max(0, red)),
        Math.min(1, Math.max(0, green)),
        Math.min(1, Math.max(0, blue)),
      ),
      opacity: Math.min(1, Math.max(0, Number.isFinite(alpha) ? alpha : 1)),
    };
  }
  return {
    color: new THREE.Color(fallbackColor),
    opacity: 1,
  };
}

function markerQuaternion(message: any) {
  return new THREE.Quaternion(
    Number(message?.pose?.orientation?.x ?? 0),
    Number(message?.pose?.orientation?.y ?? 0),
    Number(message?.pose?.orientation?.z ?? 0),
    Number(message?.pose?.orientation?.w ?? 1),
  );
}

function markerPosition(message: any) {
  return new THREE.Vector3(
    Number(message?.pose?.position?.x ?? 0),
    Number(message?.pose?.position?.y ?? 0),
    Number(message?.pose?.position?.z ?? 0),
  );
}

function buildMarkerLine(points: any[], color: THREE.Color, opacity: number, closed = false, lineWidth = 0.05) {
  const positions = points.flatMap((point: any) => [
    Number(point?.x ?? 0),
    Number(point?.y ?? 0),
    Number(point?.z ?? 0),
  ]);
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  const material = new THREE.LineBasicMaterial({
    color,
    transparent: opacity < 1,
    opacity,
  });
  const line = closed
    ? new THREE.LineLoop(geometry, material)
    : new THREE.Line(geometry, material);
  line.userData.lineWidth = lineWidth;
  return line;
}

function buildMarkerSphereList(points: any[], scale: any, colors: any[], fallbackColor: THREE.Color, fallbackOpacity: number) {
  const group = new THREE.Group();
  const radius = Math.max(0.01, Number(scale?.x ?? 0.1) / 2);
  points.forEach((point: any, index: number) => {
    const colorInfo = colors[index]
      ? markerColor({ color: colors[index] }, fallbackColor.getStyle())
      : { color: fallbackColor, opacity: fallbackOpacity };
    const mesh = new THREE.Mesh(
      new THREE.SphereGeometry(radius, 12, 10),
      new THREE.MeshStandardMaterial({
        color: colorInfo.color,
        transparent: colorInfo.opacity < 1,
        opacity: colorInfo.opacity,
      }),
    );
    mesh.position.set(Number(point?.x ?? 0), Number(point?.y ?? 0), Number(point?.z ?? 0));
    group.add(mesh);
  });
  return group;
}

function buildMarkerArrow(message: any, color: THREE.Color, opacity: number) {
  const group = new THREE.Group();
  const points = Array.isArray(message?.points) ? message.points : [];
  const start = points.length >= 1 ? new THREE.Vector3(Number(points[0]?.x ?? 0), Number(points[0]?.y ?? 0), Number(points[0]?.z ?? 0)) : new THREE.Vector3();
  const end = points.length >= 2 ? new THREE.Vector3(Number(points[1]?.x ?? 0), Number(points[1]?.y ?? 0), Number(points[1]?.z ?? 0)) : new THREE.Vector3(0.4, 0, 0);
  const direction = end.clone().sub(start);
  const length = Math.max(0.05, direction.length());
  const normalized = direction.lengthSq() > 1e-8 ? direction.normalize() : new THREE.Vector3(1, 0, 0);
  const arrow = new THREE.ArrowHelper(
    normalized,
    start,
    length,
    color,
    Math.max(0.08, Number(message?.scale?.z ?? 0.18)),
    Math.max(0.04, Number(message?.scale?.y ?? 0.12)),
  );
  arrow.name = "marker-arrow";
  arrow.line.material.transparent = opacity < 1;
  arrow.line.material.opacity = opacity;
  arrow.cone.material.transparent = opacity < 1;
  arrow.cone.material.opacity = opacity;
  group.add(arrow);
  return group;
}

function buildMarkerObject(display: NavViewerDisplay, message: any) {
  const fallback = markerColor(message, markerColorForDisplay(display));
  const type = Number(message?.type ?? -1);
  const points = Array.isArray(message?.points) ? message.points : [];
  if (type === 0) {
    return buildMarkerArrow(message, fallback.color, fallback.opacity);
  }
  if (type === 2) {
    const mesh = new THREE.Mesh(
      new THREE.SphereGeometry(Math.max(0.01, Number(message?.scale?.x ?? 0.15) / 2), 18, 14),
      new THREE.MeshStandardMaterial({
        color: fallback.color,
        transparent: fallback.opacity < 1,
        opacity: fallback.opacity,
      }),
    );
    mesh.position.copy(markerPosition(message));
    mesh.quaternion.copy(markerQuaternion(message));
    return mesh;
  }
  if (type === 3) {
    const geometry = new THREE.CylinderGeometry(
      Math.max(0.01, Number(message?.scale?.x ?? 0.2) / 2),
      Math.max(0.01, Number(message?.scale?.y ?? Number(message?.scale?.x ?? 0.2)) / 2),
      Math.max(0.01, Number(message?.scale?.z ?? 0.3)),
      24,
    );
    // ROS Marker 的圆柱沿 z 轴，Three.js CylinderGeometry 默认沿 y 轴，这里先把几何朝向对齐。
    geometry.rotateX(Math.PI / 2);
    const mesh = new THREE.Mesh(
      geometry,
      new THREE.MeshStandardMaterial({
        color: fallback.color,
        transparent: fallback.opacity < 1,
        opacity: fallback.opacity,
        depthWrite: false,
        depthTest: false,
      }),
    );
    mesh.renderOrder = 40;
    mesh.position.copy(markerPosition(message));
    mesh.quaternion.copy(markerQuaternion(message));
    return mesh;
  }
  if (type === 4 && points.length >= 2) {
    return buildMarkerLine(points, fallback.color, fallback.opacity, false, Number(message?.scale?.x ?? 0.05));
  }
  if (type === 5 && points.length >= 2) {
    return buildMarkerLine(points, fallback.color, fallback.opacity, false, Number(message?.scale?.x ?? 0.05));
  }
  if (type === 7 && points.length >= 1) {
    return buildMarkerSphereList(points, message?.scale, Array.isArray(message?.colors) ? message.colors : [], fallback.color, fallback.opacity);
  }
  return null;
}

function markerEntryKey(message: any) {
  const namespace = String(message?.ns ?? "").trim();
  const id = Number(message?.id ?? 0);
  return `${namespace}:${id}`;
}

function ensureMarkerTopicGroup(topic: string) {
  let group = markerObjectByTopic.get(topic) as THREE.Group | undefined;
  if (group) {
    return group;
  }
  group = new THREE.Group();
  group.name = `marker-topic-${topic}`;
  group.userData.markerEntries = new Map<string, THREE.Object3D>();
  scene?.add(group);
  markerObjectByTopic.set(topic, group);
  return group;
}

function removeMarkerEntry(topic: string, entryKey: string) {
  const group = markerObjectByTopic.get(topic) as THREE.Group | undefined;
  const entryMap = group?.userData?.markerEntries as Map<string, THREE.Object3D> | undefined;
  if (!group || !entryMap) {
    return;
  }
  const existing = entryMap.get(entryKey);
  if (!existing) {
    return;
  }
  group.remove(existing);
  existing.traverse((child) => {
    const mesh = child as THREE.Mesh;
    if (mesh.geometry) {
      mesh.geometry.dispose();
    }
    const material = mesh.material;
    if (Array.isArray(material)) {
      material.forEach((item) => disposeMaterialResources(item));
    } else {
      disposeMaterialResources(material ?? null);
    }
  });
  entryMap.delete(entryKey);
  if (entryMap.size <= 0) {
    disposeTopic(topic);
  }
}

function renderMarker(display: NavViewerDisplay, message: any) {
  if (!scene) {
    return;
  }
  const topic = display.topic;
  const action = Number(message?.action ?? 0);
  const entryKey = markerEntryKey(message);
  if (action === 3) {
    disposeTopic(topic);
    return;
  }
  if (action === 2) {
    removeMarkerEntry(topic, entryKey);
    return;
  }
  const markerObject = buildMarkerObject(display, message);
  if (!markerObject) {
    return;
  }
  const group = ensureMarkerTopicGroup(topic);
  const entryMap = group.userData.markerEntries as Map<string, THREE.Object3D>;
  const previous = entryMap.get(entryKey);
  if (previous) {
    group.remove(previous);
    previous.traverse((child) => {
      const mesh = child as THREE.Mesh;
      if (mesh.geometry) {
        mesh.geometry.dispose();
      }
      const material = mesh.material;
      if (Array.isArray(material)) {
        material.forEach((item) => disposeMaterialResources(item));
      } else {
        disposeMaterialResources(material ?? null);
      }
    });
  }
  group.add(markerObject);
  entryMap.set(entryKey, markerObject);
  sourceFrameByTopic.set(topic, normalizeFrameId(message?.header?.frame_id) || currentFixedFrame());
  sourceStampMsByTopic.set(topic, extractHeaderStampMs(message));
  cacheTopicLocalMatrix(topic, composeLocalMatrix());
  applyObjectFrameTransform(topic, group, sourceFrameByTopic.get(topic), sourceStampMsByTopic.get(topic) ?? null);
  group.visible = true;

  const lifetimeMs = markerLifetimeMs(message);
  const shouldAutoRemove = lifetimeMs > 0 && lifetimeMs >= 800;
  if (shouldAutoRemove) {
    window.setTimeout(() => {
      const latestGroup = markerObjectByTopic.get(topic) as THREE.Group | undefined;
      const latestEntryMap = latestGroup?.userData?.markerEntries as Map<string, THREE.Object3D> | undefined;
      if (latestEntryMap?.get(entryKey) === markerObject) {
        removeMarkerEntry(topic, entryKey);
      }
    }, lifetimeMs + 80);
  }
}

function renderTwist(display: NavViewerDisplay, message: any) {
  if (!scene) {
    return;
  }
  const anchor = resolvePrimaryPoseAnchor();
  if (!anchor) {
    sceneStatus.value = `等待位姿后绘制速度箭头: ${display.topic}`;
    return;
  }
  const linearX = Number(message?.linear?.x ?? 0);
  const linearY = Number(message?.linear?.y ?? 0);
  const linearZ = Number(message?.linear?.z ?? 0);
  const speedVector = new THREE.Vector3(linearX, linearY, linearZ);
  const speed = speedVector.length();
  const topic = display.topic;

  let group = twistObjectByTopic.get(topic) as THREE.Group | undefined;
  if (!group) {
    group = new THREE.Group();
    group.name = "twist-group";
    const arrow = new THREE.ArrowHelper(
      new THREE.Vector3(1, 0, 0),
      new THREE.Vector3(),
      0.3,
      twistColorForDisplay(display),
      0.18,
      0.1,
    );
    arrow.name = "twist-arrow";
    group.add(arrow);
    scene.add(group);
    twistObjectByTopic.set(topic, group);
  }

  const arrow = group.getObjectByName("twist-arrow") as THREE.ArrowHelper | null;
  if (arrow) {
    const direction = speed > 1e-6 ? speedVector.clone().normalize() : new THREE.Vector3(1, 0, 0);
    arrow.setDirection(direction);
    arrow.setLength(Math.max(0.18, speed), 0.18, 0.1);
    arrow.setColor(new THREE.Color(twistColorForDisplay(display)));
  }
  group.position.set(anchor.x, anchor.y, Math.max(anchor.z + 0.18, 0.18));
  group.quaternion.setFromAxisAngle(new THREE.Vector3(0, 0, 1), anchor.yaw);
  sourceFrameByTopic.set(topic, anchor.frameId);
  sourceStampMsByTopic.set(topic, extractHeaderStampMs(message));
  cacheTopicLocalMatrix(topic, composeLocalMatrix(group.position.clone(), group.quaternion.clone()));
  applyObjectFrameTransform(topic, group, anchor.frameId, sourceStampMsByTopic.get(topic) ?? null);
  group.visible = true;
}

function renderObstacleZone(topic: string, message: any) {
  if (!scene) {
    return;
  }
  const anchor = resolvePrimaryPoseAnchor();
  let zoneGroup = obstacleZoneGroupByTopic.get(topic);
  if (!anchor) {
    if (zoneGroup) {
      zoneGroup.visible = false;
    }
    sceneStatus.value = `等待位姿后绘制风险区: ${topic}`;
    return;
  }

  const state = obstacleStateFromMessage(message);
  if (!zoneGroup) {
    zoneGroup = buildObstacleZoneGroup(state);
    scene.add(zoneGroup);
    obstacleZoneGroupByTopic.set(topic, zoneGroup);
  }
  applyObstacleZoneStyle(zoneGroup, state);
  zoneGroup.position.set(anchor.x, anchor.y, Math.max(0.02, anchor.z + 0.01));
  zoneGroup.rotation.z = anchor.yaw;

  sourceFrameByTopic.set(topic, anchor.frameId);
  sourceStampMsByTopic.set(topic, null);
  cacheTopicLocalMatrix(topic, composeLocalMatrix(zoneGroup.position.clone(), zoneGroup.quaternion.clone()));
  applyObjectFrameTransform(topic, zoneGroup, anchor.frameId, null);
  zoneGroup.visible = true;
  sceneStatus.value = `已更新风险区: ${topic} (${state.label})`;
}

function ingestTfMessage(topic: string, message: any) {
  const transforms = Array.isArray(message?.transforms) ? message.transforms : [];
  const normalizedTopic = normalizeTfTopicKey(topic);
  const topicHistoryMap = tfHistoryMapForTopic(normalizedTopic, true);
  if (!topicHistoryMap) {
    return;
  }
  const isStaticTopic = normalizedTopic === "tf_static";
  const currentTimeMs = Date.now();
  transforms.forEach((item: any) => {
    const childFrame = normalizeFrameId(item?.child_frame_id);
    const parentFrame = normalizeFrameId(item?.header?.frame_id);
    if (!childFrame || !parentFrame) {
      return;
    }
    const nextSample: TfTransformSample = {
      parentFrame,
      matrixToParent: buildTransformMatrix(item?.transform?.translation, item?.transform?.rotation),
      stampMs: isStaticTopic ? null : extractHeaderStampMs(item),
      staticTransform: isStaticTopic,
    };
    const history = topicHistoryMap.get(childFrame) ?? [];
    const nextHistory = [...history.filter((sample) => sample.staticTransform !== isStaticTopic), nextSample]
      .filter((sample) => sample.staticTransform || sample.stampMs === null || currentTimeMs - sample.stampMs <= maxTfHistoryAgeMs)
      .slice(-maxTfHistorySamplesPerFrame);
    topicHistoryMap.set(childFrame, nextHistory);
  });
  emitTfFrames(topic);
  updateBaseLinkHud();
}

function ensureSupportTfSubscriptions() {
  if (!rosAdapter || !canConsumeTopicData.value) {
    return;
  }
  ["/tf", "/tf_static"].forEach((topic) => {
    if (supportTfUnsubscribeMap.has(topic) || unsubscribeMap.has(topic)) {
      return;
    }
    const unsubscribe = rosAdapter.subscribe(topic, "tf2_msgs/msg/TFMessage", (message) => {
      ingestTfMessage(topic, message);
      updateTopicTransforms();
      props.displays.forEach((display) => {
        if (display.kind === "tf") {
          renderTf(display.topic);
        }
      });
    });
    supportTfUnsubscribeMap.set(topic, unsubscribe);
  });
}

function ensureDisplaySubscription(display: NavViewerDisplay) {
  if (
    !rosAdapter ||
    !canConsumeTopicData.value ||
    unsubscribeMap.has(display.topic) ||
    (display.kind === "tf" && supportTfUnsubscribeMap.has(display.topic))
  ) {
    return;
  }

  const unsubscribe = rosAdapter.subscribe(display.topic, display.messageType, (message) => {
    const latestDisplay = getDisplayByTopic(display.topic) || display;
    if (!shouldConsumeDisplayMessage(latestDisplay)) {
      return;
    }
    latestMessageByTopic.set(latestDisplay.topic, message);
    renderDisplayMessage(latestDisplay, message);
  }, subscriptionOptionsForDisplay(display));

  unsubscribeMap.set(display.topic, unsubscribe);
}

function renderDisplayMessage(display: NavViewerDisplay, message: any) {
  if (display.kind === "map") {
    renderOccupancyGrid(display.topic, message);
    sceneStatus.value = `已渲染地图: ${display.topic}`;
    return;
  }
  if (display.kind === "path") {
    renderPath(display.topic, message);
    sceneStatus.value = `已更新路径: ${display.topic}`;
    return;
  }
  if (display.kind === "bspline") {
    renderBspline(display, message);
    sceneStatus.value = `已更新 B-spline 轨迹: ${display.topic}`;
    return;
  }
  if (display.kind === "pointcloud") {
    renderPointCloud(display, message);
    sceneStatus.value = `已更新点云: ${display.topic}`;
    return;
  }
  if (display.kind === "laser") {
    renderLaser(display.topic, message);
    sceneStatus.value = `已更新激光: ${display.topic}`;
    return;
  }
  if (display.kind === "tf") {
    ingestTfMessage(display.topic, message);
    renderTf(display.topic);
    sceneStatus.value = `已更新 TF: ${display.topic}`;
    return;
  }
  if (display.kind === "pose") {
    renderPose(display.topic, message);
    sceneStatus.value = `已更新位姿: ${display.topic}`;
    return;
  }
  if (display.kind === "pose_array") {
    renderPoseArray(display.topic, message);
    sceneStatus.value = `已更新位姿数组: ${display.topic}`;
    return;
  }
  if (display.kind === "obstacle_zone") {
    renderObstacleZone(display.topic, message);
    return;
  }
  if (display.kind === "marker") {
    renderMarker(display, message);
    sceneStatus.value = `已更新 Marker: ${display.topic}`;
    return;
  }
  if (display.kind === "twist") {
    renderTwist(display, message);
    sceneStatus.value = `已更新速度箭头: ${display.topic}`;
    return;
  }
  sceneStatus.value = `暂不支持可视化: ${display.topic}`;
}

function emitRosLog(level: "info" | "warning" | "error", message: string) {
  emit("rosLog", {
    source: "三维主视图",
    level,
    message,
  });
}

function buildSharedRosConfig(): RosLiveConfig {
  return {
    provider: props.provider,
    url: props.url,
    timeoutMs: props.timeoutMs,
    autoReconnect: true,
    reconnectBaseDelayMs: 3000,
    reconnectMaxDelayMs: 30000,
    reconnectMaxAttempts: 4,
    sharedKey: buildSharedRosKey("ros-nav-test", props.provider, props.url, props.timeoutMs),
    adapterName: "ROS 测试工作台共享连接",
  };
}

async function reconnectAndResubscribe() {
  reconnectTimer = undefined;
  unsubscribeMap.forEach((unsubscribe) => unsubscribe());
  unsubscribeMap.clear();
  supportTfUnsubscribeMap.forEach((unsubscribe) => unsubscribe());
  supportTfUnsubscribeMap.clear();
  clearAllTopicVisuals();
  tfTransformHistoryByTopic.clear();
  props.displays
    .filter((display) => display.kind === "tf")
    .forEach((display) => emit("tfFramesChange", { topic: display.topic, frames: [] }));

  rosAdapter?.disconnect();
  rosAdapter = createSharedRosLiveAdapter({
    ...buildSharedRosConfig(),
    adapterName: "三维主视图",
    onStatusChange: (snapshot) => {
      connectionLabel.value = snapshot.connected ? "已连接" : snapshot.reconnecting ? "重连中" : "未连接";
      sceneStatus.value = snapshot.message;
      updateBaseLinkHud();
      if (snapshot.connected) {
        ensureSupportTfSubscriptions();
        props.displays.forEach((display) => ensureDisplaySubscription(display));
      }
    },
    onError: (event) => {
      emitRosLog(
        event.recoverable ? "warning" : "error",
        `${event.scope}: ${event.message}${event.detail ? ` (${event.detail})` : ""}`
      );
    },
  });

  if (!props.url && props.provider !== "mock") {
    connectionLabel.value = "未配置地址";
    sceneStatus.value = "请先填写 rosbridge 地址";
    updateBaseLinkHud();
    emitRosLog("warning", "三维主视图未配置 rosbridge 地址，未启动连接。");
    return;
  }

  try {
    await rosAdapter.connect();
    const snapshot = rosAdapter.getConnectionSnapshot();
    connectionLabel.value = snapshot.connected ? "已连接" : "未连接";
    sceneStatus.value = snapshot.message;
    updateBaseLinkHud();
    ensureSupportTfSubscriptions();
    props.displays.forEach((display) => ensureDisplaySubscription(display));
    emitRosLog("info", `三维主视图连接成功: ${snapshot.message}`);
  } catch (error) {
    connectionLabel.value = "连接失败";
    sceneStatus.value = (error as Error).message;
    clearAllTopicVisuals();
    updateBaseLinkHud();
    emitRosLog("error", `三维主视图连接失败: ${(error as Error).message}`);
  }
}

function scheduleReconnectAndResubscribe() {
  if (reconnectTimer) {
    window.clearTimeout(reconnectTimer);
  }
  reconnectTimer = window.setTimeout(() => {
    void reconnectAndResubscribe();
  }, 120);
}

watch(
  () => [props.provider, props.url, props.timeoutMs, props.fixedFrame],
  () => scheduleReconnectAndResubscribe()
);

watch(
  () => props.reconnectToken,
  () => scheduleReconnectAndResubscribe()
);

watch(
  () => props.displays,
  (nextDisplays, previousDisplays) => {
    if (!canConsumeTopicData.value) {
      clearAllTopicVisuals();
      if (connectionLabel.value === "已连接" && nextDisplays.length === 0) {
        sceneStatus.value = "等待显示项";
      }
      return;
    }

    const nextTopics = new Set(nextDisplays.map((item) => item.topic));
    const previousTopics = new Set((previousDisplays ?? []).map((item) => item.topic));

    previousTopics.forEach((topic) => {
      if (!nextTopics.has(topic)) {
        disposeTopic(topic);
      }
    });

      nextDisplays.forEach((display) => ensureDisplaySubscription(display));
      syncMapDisplayConfigs(nextDisplays);
      syncPointCloudDisplayConfigs(nextDisplays);
      syncPathDisplayConfigs(nextDisplays);
      syncPoseDisplayConfigs(nextDisplays);
      syncMarkerDisplayConfigs(nextDisplays);
      syncTwistDisplayConfigs(nextDisplays);
      nextDisplays
        .filter((display) => display.kind === "tf")
        .forEach((display) => renderTf(display.topic));
    if (nextDisplays.length === 0) {
      sceneStatus.value = "等待显示项";
    }
  },
  { deep: true }
);

watch(
  () => currentInteractionMode.value,
  () => {
    finishInteraction(false);
    syncControlLockState();
  }
);

defineExpose<NavViewerExpose>({
  focusOnNdtPose,
});

onMounted(async () => {
  initializeScene();
  resizeObserver = new ResizeObserver(() => fitRendererSize());
  if (mountRef.value) {
    resizeObserver.observe(mountRef.value);
  }
  renderer?.domElement.addEventListener("pointerdown", handlePointerDown);
  renderer?.domElement.addEventListener("pointermove", handlePointerMove);
  renderer?.domElement.addEventListener("pointerup", handlePointerUp);
  renderer?.domElement.addEventListener("pointercancel", handlePointerCancel);
  renderer?.domElement.addEventListener("pointerleave", handlePointerCancel);
  syncControlLockState();
  scheduleReconnectAndResubscribe();
});

onBeforeUnmount(() => {
  window.cancelAnimationFrame(animationFrame);
  if (reconnectTimer) {
    window.clearTimeout(reconnectTimer);
    reconnectTimer = undefined;
  }
  resizeObserver?.disconnect();
  renderer?.domElement.removeEventListener("pointerdown", handlePointerDown);
  renderer?.domElement.removeEventListener("pointermove", handlePointerMove);
  renderer?.domElement.removeEventListener("pointerup", handlePointerUp);
  renderer?.domElement.removeEventListener("pointercancel", handlePointerCancel);
  renderer?.domElement.removeEventListener("pointerleave", handlePointerCancel);
  unsubscribeMap.forEach((unsubscribe) => unsubscribe());
  unsubscribeMap.clear();
  supportTfUnsubscribeMap.forEach((unsubscribe) => unsubscribe());
  supportTfUnsubscribeMap.clear();
  rosAdapter?.disconnect();
  rosAdapter = null;
  teardownRenderer();
});
</script>

<template>
  <div class="nav-viewer-shell">
    <div class="nav-viewer-toolbar">
      <span class="status-pill" :class="{ success: connectionLabel === '已连接' }">{{ connectionLabel }}</span>
      <span class="nav-viewer-meta">Fixed Frame: {{ fixedFrame }}</span>
      <span class="nav-viewer-meta">显示项: {{ hudDisplayCount }}</span>
    </div>

    <div class="nav-viewer-stage">
      <div ref="mountRef" class="nav-viewer-canvas-host"></div>
      <div class="nav-viewer-base-link-hud" :class="`tone-${baseLinkHudTone}`">
        <span class="nav-viewer-base-link-title">机器狗位置</span>
        <span class="nav-viewer-base-link-text">{{ baseLinkHudText }}</span>
      </div>
      <button class="nav-viewer-focus-button" type="button" aria-label="定位图示" title="定位图示" @click="handleFocusButtonClick">
        <svg class="nav-viewer-focus-icon" viewBox="0 0 128 128" aria-hidden="true">
          <defs>
            <filter id="navFocusGlow" x="-30%" y="-30%" width="160%" height="160%">
              <feGaussianBlur stdDeviation="2.4" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
            <radialGradient id="navFocusCore" cx="50%" cy="50%" r="50%">
              <stop offset="0%" stop-color="#ebffff" />
              <stop offset="58%" stop-color="#61ecff" />
              <stop offset="100%" stop-color="#0aa8d7" />
            </radialGradient>
          </defs>
          <g filter="url(#navFocusGlow)">
            <circle cx="64" cy="64" r="36" class="nav-focus-ring outer" />
            <circle cx="64" cy="64" r="29" class="nav-focus-ring inner" />
            <circle cx="64" cy="64" r="16" fill="url(#navFocusCore)" class="nav-focus-core" />
            <path class="nav-focus-mark north" d="M64 8 L67 34 L64 49 L61 34 Z" />
            <path class="nav-focus-mark south" d="M64 120 L67 94 L64 79 L61 94 Z" />
            <path class="nav-focus-mark west" d="M8 64 L34 61 L49 64 L34 67 Z" />
            <path class="nav-focus-mark east" d="M120 64 L94 61 L79 64 L94 67 Z" />
            <path class="nav-focus-arc" d="M24 49 A43 43 0 0 1 49 24" />
            <path class="nav-focus-arc" d="M79 24 A43 43 0 0 1 104 49" />
            <path class="nav-focus-arc" d="M24 79 A43 43 0 0 0 49 104" />
            <path class="nav-focus-arc" d="M79 104 A43 43 0 0 0 104 79" />
          </g>
        </svg>
      </button>
    </div>

    <div class="nav-viewer-footer">
      <span class="nav-viewer-status">{{ sceneStatus }}</span>
      <span v-if="connectionLabel !== '已连接' || hudDisplayCount === 0" class="nav-viewer-status">
        {{ emptyStateText }}
      </span>
      <span v-if="interactionHintText" class="nav-viewer-status accent">{{ interactionHintText }}</span>
    </div>
  </div>
</template>
