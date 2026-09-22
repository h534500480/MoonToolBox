<!-- 功能说明：导航测试页三维主视图，负责把 ROS 常用话题渲染到统一 3D 窗口。 -->
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import * as THREE from "three";
import { createPlatformArena } from "../lib/scene/platformArena";
import { platformState } from "../platform/ui";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { CombinedPoseControls } from "../lib/scene/combinedPoseControls";
import { poseVisualScale } from "../lib/scene/poseVisualScale";
import { routeInsertionYaw } from "../lib/navigationTasks";

import { raycastRosNavOfflineMap } from "../api/client";
import type { NavViewerDisplay } from "../lib/ros/displayRegistry";
import {
  createOfflineVoxelRender,
  voxelSurfaceColor,
} from "../lib/ros/offlineVoxelRender";
import {
  configureVoxelGrowthAttributes,
  createVoxelGrowthGeometry,
  createVoxelGrowthMaterial,
  setVoxelGrowthMaterialMode,
  updateVoxelGrowthTime,
} from "../lib/ros/voxelGrowth";
import {
  createSharedRosLiveAdapter,
  type RosLiveConfig,
} from "../lib/ros/liveAdapter";

import type {
  TaskPose,
  TaskPoint,
  TaskScene,
  TaskRouteInsertion,
} from "../lib/navigationTasks";

type OfflineMapDisplayMode = "voxel" | "pointcloud" | "render";

interface OfflineMapVisualSettings {
  displayMode?: OfflineMapDisplayMode;
  pointSize?: number;
  pointColor?: string;
  voxelColor?: string;
}

interface NavViewerExpose extends TaskScene {
  focusOnNdtPose: () => { ok: boolean; message: string };
  attachOfflineMapPointCloud: (payload: OfflineMapPointCloudPayload) => {
    ok: boolean;
    message: string;
  };
  clearOfflineMapPointCloud: () => void;
  setOfflineMapDisplayMode: (mode: OfflineMapDisplayMode) => {
    ok: boolean;
    message: string;
  };
  updateOfflineMapVisualSettings: (settings: OfflineMapVisualSettings) => void;
  attachInitialPosePointCloud: (payload: InitialPosePointCloudPayload) => {
    ok: boolean;
    message: string;
  };
  updateInitialPosePointCloudSize: (pointSize: number) => {
    ok: boolean;
    message: string;
  };
  getInitialPoseCandidate: () => InitialPoseCandidatePayload | null;
  clearInitialPoseCandidate: () => void;
}

const props = defineProps<{
  provider: string;
  url: string;
  timeoutMs: number;
  fixedFrame: string;
  robotPoseFrame?: string;
  displays: NavViewerDisplay[];
  interactionMode?: "none" | "initialpose" | "navgoal" | "waypoint";
  taskPoints?: TaskPoint[];
  taskEditing?: boolean;
  reconnectToken?: number;
  initialPoseBaseHeightOffsetM?: number;
  initialPoseGroundNormalRadiusM?: number;
  initialPoseGroundMaxSlopeDeg?: number;
  offlineClipPanelOpen?: boolean;
}>();

const emit = defineEmits<{
  taskPoseChange: [pose: TaskPose];
  taskPosePlaced: [pose: TaskPose];
  taskPointSelect: [point: TaskPoint];
  taskRouteInsert: [insertion: TaskRouteInsertion];
  interactionComplete: [
    payload: {
      mode: "initialpose" | "navgoal";
      x: number;
      y: number;
      z?: number;
      roll?: number;
      pitch?: number;
      yaw: number;
    },
  ];
  tfFramesChange: [payload: { topic: string; frames: string[] }];
  rosLog: [
    payload: {
      source: string;
      level: "info" | "warning" | "error";
      message: string;
    },
  ];
}>();

interface InitialPosePointCloudPayload {
  topic: string;
  message: any;
  color?: string;
  pointSize?: number;
  pointColorMode?: "solid" | "layered";
}

interface InitialPoseCandidatePayload {
  x: number;
  y: number;
  z: number;
  roll: number;
  pitch: number;
  yaw: number;
}

interface BoundsPayload {
  xmin: number;
  xmax: number;
  ymin: number;
  ymax: number;
  zmin: number;
  zmax: number;
}

interface PointCloudRenderResult {
  ok: boolean;
  message: string;
  warningSignature?: string;
}

interface OfflineMapInfoPayload {
  yaml_path: string;
  image_path: string;
  resolution: number;
  origin: number[];
  width: number;
  height: number;
  bounds: BoundsPayload;
}

interface OfflineMapPointCloudPayload {
  pcd: {
    path: string;
    input_points: number;
    sampled_count: number;
    voxel_leaf_m: number;
    input_bounds: BoundsPayload;
    sampled_bounds: BoundsPayload;
    points: number[][];
  };
  occupancy?: {
    voxel_m: number;
    occupied_count: number;
    voxels: number[][];
  };
  map: OfflineMapInfoPayload | null;
}

interface SceneFadeMaterialState {
  material: THREE.Material;
  from: number;
  to: number;
}

interface SceneFadeItem {
  object: THREE.Object3D;
  startedAt: number;
  durationMs: number;
  disposeAfter: boolean;
  materials: SceneFadeMaterialState[];
}

interface OfflineRenderEnvironmentTransition {
  startedAt: number;
  durationMs: number;
  from: number;
  to: number;
  disposeOnDone: boolean;
}

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
  receivedAtMs: number;
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

let arena: ReturnType<typeof createPlatformArena> | null = null;
let lastFrameTime = performance.now();
let lastRobotPose: THREE.Matrix4 | null = null;
let hasConnected = false;
let previousDemo = true;
let renderer: THREE.WebGLRenderer | null = null;
let scene: THREE.Scene | null = null;
let camera: THREE.PerspectiveCamera | null = null;
let controls: OrbitControls | null = null;
let transformControls: CombinedPoseControls | null = null;
let transformControlsHelper: THREE.Object3D | null = null;
let animationFrame = 0;
let rosAdapter: ReturnType<typeof createSharedRosLiveAdapter> | null = null;
let resizeObserver: ResizeObserver | null = null;
let reconnectTimer: number | undefined;
let lastViewportWidth = 0;
let lastViewportHeight = 0;
let interactionStartPoint: THREE.Vector3 | null = null;
let interactionCurrentPoint: THREE.Vector3 | null = null;
let interactionStartGroundNormal: THREE.Vector3 | null = null;
let interactionStartGroundMessage = "";
let interactionPreviewGroup: THREE.Group | null = null;
let initialPoseCandidateGroup: THREE.Group | null = null;
let initialPosePointCloud: THREE.Points | null = null;
let offlineMapGroup: THREE.Group | null = null;
let offlineMapPoints: THREE.Points | null = null;
let offlineMapVoxelMesh: THREE.InstancedMesh | null = null;
let offlineVoxelRender: ReturnType<typeof createOfflineVoxelRender> | null =
  null;
let offlineMapRawPositions: Float32Array | null = null;
let offlineMapVoxelCenters: Float32Array | null = null;
let offlineMapVoxelSize = 0.1;
let offlineMapPointSize = 0.06;
let offlineMapPointColor = "#d7dee8";
let offlineMapVoxelColor = "#a79d86";
let offlineVoxelAnimationStartMs = 0;
let offlineVoxelAnimationDurationSeconds = 0;
let offlineVoxelAnimationVersion = 0;
let offlineRenderEnvironmentTransition: OfflineRenderEnvironmentTransition | null =
  null;
let offlineSceneAnchorStartMs = 0;
let offlineSceneAnchorUntilMs = 0;
let offlineMapOriginalBounds: BoundsPayload | null = null;
let offlineMapClipBounds: BoundsPayload | null = null;
let offlineClipDragStartX = 0;
let offlineClipDragStartY = 0;
let offlineClipDragFace: keyof BoundsPayload | null = null;
let offlineClipDragStartValue = 0;
let webglContextLost = false;

const unsubscribeMap = new Map<string, () => void>();
const supportTfUnsubscribeMap = new Map<string, () => void>();
const mapMeshByTopic = new Map<string, THREE.Object3D>();
const mapTextureByTopic = new Map<string, THREE.CanvasTexture>();
const sceneFadeItems: SceneFadeItem[] = [];
const pathLineByTopic = new Map<string, THREE.Line>();
const tfGroupByTopic = new Map<string, THREE.Group>();
const tfFrameNodeCacheByTopic = new Map<string, Map<string, THREE.Group>>();
const poseObjectByTopic = new Map<string, THREE.Object3D>();
const poseAnchorByTopic = new Map<string, NavPoseAnchor>();
const pointCloudByTopic = new Map<string, THREE.Points>();
const pointCloudWarningSignatureByTopic = new Map<string, string>();
const laserByTopic = new Map<string, THREE.Points>();
const markerObjectByTopic = new Map<string, THREE.Object3D>();
const twistObjectByTopic = new Map<string, THREE.Object3D>();
const obstacleZoneGroupByTopic = new Map<string, THREE.Group>();
const lastMessageTimeByTopic = new Map<string, number>();
const latestMessageByTopic = new Map<string, any>();
const sourceFrameByTopic = new Map<string, string>();
const sourceStampMsByTopic = new Map<string, number | null>();
const baseLocalMatrixByTopic = new Map<string, THREE.Matrix4>();
const tfTransformHistoryByTopic = new Map<
  string,
  Map<string, TfTransformSample[]>
>();
const tfFrameSignatureByTopic = new Map<string, string>();
const raycaster = new THREE.Raycaster();
const interactionPlane = new THREE.Plane(new THREE.Vector3(0, 0, 1), 0);
const maxTfHistorySamplesPerFrame = 240;
const maxTfHistoryAgeMs = 30000;
const robotPoseTfTopic = "/display/tf";
const supportTfTopics = [robotPoseTfTopic, "/tf", "/tf_static"];

const hudDisplayCount = computed(() => props.displays.length);
const currentInteractionMode = computed(() => props.interactionMode || "none");
const canConsumeTopicData = computed(() => connectionLabel.value === "已连接");
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
    return "初始化定位模式: 左键点击地图并拖动方向，松开后生成候选位姿。";
  }
  if (currentInteractionMode.value === "waypoint")
    return "任务点位：点击地图并拖动设置朝向，松开后可用控件微调。";
  if (currentInteractionMode.value === "navgoal") {
    return "导航目标模式: 左键点击地图并拖动方向，松开后下发 /nav2_goal_request。";
  }
  return "";
});
const baseLinkHudTone = computed(() => {
  if (connectionLabel.value !== "已连接") {
    return "warning";
  }
  return baseLinkHudText.value.includes("等待") ||
    baseLinkHudText.value.includes("不可用")
    ? "warning"
    : "success";
});
const offlineClipActive = ref(false);
const activeOfflineClipFace = ref<keyof BoundsPayload | null>(null);
// 悬停高亮状态：与 activeOfflineClipFace 共同驱动同轴读数行亮起
const hoveredOfflineClipFace = ref<keyof BoundsPayload | null>(null);
// 裁剪边界响应式镜像：offlineMapClipBounds 是普通对象，模板读数依赖此副本驱动刷新
const offlineClipBoundsView = ref<BoundsPayload | null>(null);
const offlineMapDisplayMode = ref<OfflineMapDisplayMode>("voxel");

// 面板展开状态由父组件侧边工具栏统一管理（与话题列表互斥）
const offlineClipPanelVisible = computed(
  () => offlineClipActive.value && props.offlineClipPanelOpen !== false,
);

// 悬停或拖拽中的面所在轴，用于读数行联动高亮
const highlightedOfflineClipAxis = computed<"x" | "y" | "z" | null>(() => {
  const face = activeOfflineClipFace.value ?? hoveredOfflineClipFace.value;
  return face ? clipAxisForFace(face) : null;
});

function setHoveredOfflineClipFace(face: keyof BoundsPayload | null) {
  hoveredOfflineClipFace.value = face;
}

function syncOfflineClipBoundsView() {
  offlineClipBoundsView.value = offlineMapClipBounds
    ? { ...offlineMapClipBounds }
    : null;
}
const offlineVoxelBaseColor = new THREE.Color(offlineMapVoxelColor);
const offlineVoxelColor = new THREE.Color();

function hasOfflineMapRaycastCache() {
  return Boolean(offlineMapRawPositions && offlineMapRawPositions.length > 0);
}

function initializeScene() {
  const host = mountRef.value;
  if (!host) {
    return;
  }

  scene = new THREE.Scene();
  scene.background = new THREE.Color("#e8e4da");
  scene.up.set(0, 0, 1);
  scene.fog = new THREE.Fog("#e8e4da", 34, 80);

  camera = new THREE.PerspectiveCamera(38, 1, 0.1, 500);
  camera.up.set(0, 0, 1);
  camera.position.set(-8.2, -8.2, 9);
  camera.lookAt(0, 0, 0);

  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.setClearColor("#e8e4da", 1);
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFShadowMap;
  renderer.domElement.style.display = "block";
  renderer.domElement.style.width = "100%";
  renderer.domElement.style.height = "100%";
  renderer.domElement.addEventListener(
    "webglcontextlost",
    handleWebglContextLost,
    false,
  );
  renderer.domElement.addEventListener(
    "webglcontextrestored",
    handleWebglContextRestored,
    false,
  );
  host.appendChild(renderer.domElement);

  controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.target.set(0, 0, 0.25);
  controls.dampingFactor = 0.08;
  controls.rotateSpeed = 0.55;
  controls.screenSpacePanning = false;
  controls.mouseButtons.LEFT = THREE.MOUSE.ROTATE;
  controls.mouseButtons.RIGHT = THREE.MOUSE.PAN;

  transformControls = new CombinedPoseControls(
    camera,
    renderer.domElement,
    (dragging) => {
      if (controls) controls.enabled = !dragging;
    },
    () => {
      const candidate = getInitialPoseCandidate();
      if (!candidate) {
        return;
      }
      if (props.taskEditing) {
        emit("taskPoseChange", candidate);
        return;
      }
      sceneStatus.value = `初始化候选: x=${candidate.x.toFixed(3)}, y=${candidate.y.toFixed(3)}, z=${candidate.z.toFixed(3)}, roll=${candidate.roll.toFixed(2)}, pitch=${candidate.pitch.toFixed(2)}, yaw=${candidate.yaw.toFixed(2)}`;
    },
    (event) => !!pickTaskMarker(event),
  );
  transformControlsHelper = transformControls.getHelper();
  transformControlsHelper.visible = false;
  scene.add(transformControlsHelper);

  arena = createPlatformArena(scene);
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

function animate() {
  if (!renderer || !scene || !camera || webglContextLost) {
    return;
  }
  animationFrame = window.requestAnimationFrame(animate);
  const now = performance.now();
  const dt = (now - lastFrameTime) / 1000;
  lastFrameTime = now;
  const connected = connectionLabel.value === "已连接";
  if (connected) hasConnected = true;
  const demo = !hasConnected && !hasOfflineMapRaycastCache();
  const anchoringOfflineScene = now < offlineSceneAnchorUntilMs;
  const keepDemoControls = demo || anchoringOfflineScene;
  platformState.demo = keepDemoControls;
  platformState.connected = connected;
  platformState.lidarActive =
    connected && Date.now() - platformState.lidarAt < 3000;
  const robotTf = connected ? resolveRobotTfPose() : null;
  const tf = robotTf?.matrix ?? null;
  const anchor = resolvePrimaryPoseAnchor();
  const poseObject = anchor ? poseObjectByTopic.get(anchor.topic) : null;
  if (tf) lastRobotPose = tf.clone();
  else if (connected && poseObject?.visible) {
    poseObject.updateMatrixWorld();
    lastRobotPose = poseObject.matrixWorld.clone();
  }
  const offlineFallbackPose =
    !connected && hasOfflineMapRaycastCache() ? new THREE.Matrix4() : null;
  arena?.update(dt, demo, connected, lastRobotPose ?? offlineFallbackPose);
  arena?.setDemoOpacity(
    demo ? 1 : anchoringOfflineScene ? 1 - offlineSceneAnchorProgress(now) : 0,
  );
  updateOfflineAnchorCamera(now);
  controls!.enablePan = !keepDemoControls;
  controls!.minDistance = keepDemoControls ? 5 : 0.1;
  controls!.maxDistance = keepDemoControls ? 17 : 10000;
  controls!.minPolarAngle = keepDemoControls ? 0.5 : 0.01;
  controls!.maxPolarAngle = keepDemoControls ? 1.12 : Math.PI - 0.01;
  if (keepDemoControls !== previousDemo) {
    scene.fog = keepDemoControls ? new THREE.Fog("#e8e4da", 34, 80) : null;
    previousDemo = keepDemoControls;
  }
  updateOfflineVoxelGrowthFrame(now);
  updateSceneFadeItems(now);
  if (lastRobotPose && !demo) {
    const p = new THREE.Vector3(),
      q = new THREE.Quaternion(),
      scale = new THREE.Vector3();
    lastRobotPose.decompose(p, q, scale);
    platformState.pose = `x  ${p.x.toFixed(3)}    y  ${p.y.toFixed(3)}\nz  ${p.z.toFixed(3)}    yaw  ${quaternionToYaw(q).toFixed(3)}${connected ? "" : "\n连接断开 · 最后有效位姿"}`;
    if (robotTf?.fallback)
      platformState.pose += "\n使用 base_link · body 暂不可用";
  }
  // 拖动位姿时冻结相机阻尼，避免选中控件前残留的相机运动改变拖动平面。
  if (!transformControls?.dragging) controls?.update();
  transformControls?.updateScale();
  updateTaskMarkerScales();
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
  object.parent?.remove(object);
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

function materialFadeValue(material: THREE.Material) {
  if (
    material instanceof THREE.ShaderMaterial &&
    material.uniforms.uFade &&
    typeof material.uniforms.uFade.value === "number"
  ) {
    return material.uniforms.uFade.value;
  }
  return material.opacity;
}

function setMaterialFadeValue(material: THREE.Material, value: number) {
  if (
    material instanceof THREE.ShaderMaterial &&
    material.uniforms.uFade &&
    typeof material.uniforms.uFade.value === "number"
  ) {
    material.uniforms.uFade.value = value;
    return;
  }
  material.transparent = true;
  material.opacity = value;
  material.needsUpdate = true;
}

function collectObjectMaterials(object: THREE.Object3D) {
  const materials = new Set<THREE.Material>();
  object.traverse((child) => {
    const material = (child as THREE.Mesh).material;
    if (Array.isArray(material)) {
      material.forEach((item) => materials.add(item));
    } else if (material) {
      materials.add(material);
    }
  });
  return [...materials];
}

function queueObjectFade(
  object: THREE.Object3D,
  to: number,
  durationMs: number,
  disposeAfter: boolean,
) {
  const materials = collectObjectMaterials(object).map((material) => ({
    material,
    from: materialFadeValue(material),
    to,
  }));
  materials.forEach(({ material, from }) => {
    setMaterialFadeValue(material, from);
  });
  sceneFadeItems.push({
    object,
    startedAt: performance.now(),
    durationMs,
    disposeAfter,
    materials,
  });
}

function updateSceneFadeItems(now: number) {
  for (let index = sceneFadeItems.length - 1; index >= 0; index -= 1) {
    const item = sceneFadeItems[index];
    const progress = THREE.MathUtils.clamp(
      (now - item.startedAt) / item.durationMs,
      0,
      1,
    );
    item.materials.forEach(({ material, from, to }) => {
      setMaterialFadeValue(material, THREE.MathUtils.lerp(from, to, progress));
    });
    if (progress < 1) {
      continue;
    }
    sceneFadeItems.splice(index, 1);
    if (item.disposeAfter) {
      clearThreeObject(item.object);
    }
  }
}

function clearSceneFadeItems() {
  while (sceneFadeItems.length > 0) {
    const item = sceneFadeItems.pop();
    if (item?.disposeAfter) {
      clearThreeObject(item.object);
    }
  }
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
  arena?.dispose();
  arena = null;
  clearInteractionPreview();
  clearInitialPoseCandidate();
  clearOfflineMapPointCloud();
  clearAllTopicVisuals();
  clearSceneFadeItems();
  tfTransformHistoryByTopic.clear();
  tfFrameNodeCacheByTopic.clear();
  if (renderer?.domElement) {
    renderer.domElement.removeEventListener(
      "webglcontextlost",
      handleWebglContextLost,
    );
    renderer.domElement.removeEventListener(
      "webglcontextrestored",
      handleWebglContextRestored,
    );
  }
  controls?.dispose();
  controls = null;
  transformControls?.dispose();
  transformControls = null;
  if (transformControlsHelper) {
    scene?.remove(transformControlsHelper);
    transformControlsHelper = null;
  }
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
  pointCloudWarningSignatureByTopic.delete(topic);

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

function replaceObjectGeometry<
  T extends THREE.Object3D & { geometry?: THREE.BufferGeometry | null },
>(object: T, nextGeometry: THREE.BufferGeometry) {
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
  return String(frameId ?? "")
    .trim()
    .replace(/^\/+/, "");
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
  return ["tf_static", normalizedTopic].filter(
    (item, index, array) => item && array.indexOf(item) === index,
  );
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
  return Array.from(frameSet).sort((left, right) =>
    left.localeCompare(right, "zh-CN"),
  );
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

/**
 * 返回用于机器人模型、HUD 和任务取点的 TF 子坐标系。
 * 该值由 ROS 接入设置提供；保留 body 默认值以兼容没有保存此项的旧配置。
 */
function currentRobotPoseFrame() {
  return normalizeFrameId(props.robotPoseFrame || "body") || "body";
}
let lastRobotTfNotice = "";
/** 三处机器人位姿入口共用相同解析；仅兼容旧默认 body，不猜测任意自定义坐标系。 */
function resolveRobotTfPose() {
  const requested = currentRobotPoseFrame();
  const resolve = (frame: string) =>
    resolveFrameTransformToFixed(frame, null, robotPoseTfTopic) ||
    resolveFrameTransformToFixed(frame);
  let matrix = resolve(requested);
  let frame = requested;
  if (
    !matrix &&
    requested === "body" &&
    tfSamplesForFrame(robotPoseTfTopic, requested).length === 0 &&
    tfSamplesForFrame("/tf", requested).length === 0
  ) {
    matrix = resolve("base_link");
    if (matrix) frame = "base_link";
  }
  if (!matrix) return null;
  if (frame !== requested && lastRobotTfNotice !== frame) {
    emitRosLog(
      "warning",
      "机器人坐标系 body 未收到 TF，当前使用完整 base_link 变换链；可在 ROS 接入设置中指定机器人坐标系。",
    );
  }
  lastRobotTfNotice = frame;
  return { matrix, frame, fallback: frame !== requested };
}

function buildTransformMatrix(translation: any, rotation: any) {
  const position = new THREE.Vector3(
    Number(translation?.x ?? 0),
    Number(translation?.y ?? 0),
    Number(translation?.z ?? 0),
  );
  const quaternion = new THREE.Quaternion(
    Number(rotation?.x ?? 0),
    Number(rotation?.y ?? 0),
    Number(rotation?.z ?? 0),
    Number(rotation?.w ?? 1),
  );
  const matrix = new THREE.Matrix4();
  matrix.compose(position, quaternion, new THREE.Vector3(1, 1, 1));
  return matrix;
}

function selectTfTransformSample(
  frameId: string,
  targetStampMs: number | null,
  tfTopic = "/tf",
) {
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

function resolveFrameTransformToFixed(
  frameId: unknown,
  targetStampMs: number | null = null,
  tfTopic = "/tf",
  trail = new Set<string>(),
): THREE.Matrix4 | null {
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
  const parentMatrix = resolveFrameTransformToFixed(
    sample.parentFrame,
    targetStampMs,
    tfTopic,
    trail,
  );
  trail.delete(sourceFrame);
  if (!parentMatrix) {
    return null;
  }
  return parentMatrix.clone().multiply(sample.matrixToParent);
}

function transformPositionArrayInPlace(
  positions: number[],
  transformMatrix: THREE.Matrix4 | null,
) {
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
  scale: THREE.Vector3 = new THREE.Vector3(1, 1, 1),
) {
  const matrix = new THREE.Matrix4();
  matrix.compose(position, quaternion, scale);
  return matrix;
}

function applyObjectFrameTransform(
  topic: string,
  object: THREE.Object3D,
  frameId: unknown,
  targetStampMs: number | null = null,
  tfTopic = "/tf",
) {
  const transformMatrix = resolveFrameTransformToFixed(
    frameId,
    targetStampMs,
    tfTopic,
  );
  const baseMatrix =
    baseLocalMatrixByTopic.get(topic) ?? new THREE.Matrix4().identity();
  const finalMatrix = transformMatrix
    ? transformMatrix.clone().multiply(baseMatrix)
    : baseMatrix.clone();
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
  mapMeshByTopic.forEach((object, topic) =>
    applyObjectFrameTransform(
      topic,
      object,
      sourceFrameByTopic.get(topic),
      sourceStampMsByTopic.get(topic) ?? null,
    ),
  );
  pathLineByTopic.forEach((object, topic) =>
    applyObjectFrameTransform(
      topic,
      object,
      sourceFrameByTopic.get(topic),
      sourceStampMsByTopic.get(topic) ?? null,
    ),
  );
  poseObjectByTopic.forEach((object, topic) =>
    applyObjectFrameTransform(
      topic,
      object,
      sourceFrameByTopic.get(topic),
      sourceStampMsByTopic.get(topic) ?? null,
    ),
  );
  pointCloudByTopic.forEach((object, topic) =>
    applyObjectFrameTransform(
      topic,
      object,
      sourceFrameByTopic.get(topic),
      sourceStampMsByTopic.get(topic) ?? null,
    ),
  );
  laserByTopic.forEach((object, topic) =>
    applyObjectFrameTransform(
      topic,
      object,
      sourceFrameByTopic.get(topic),
      sourceStampMsByTopic.get(topic) ?? null,
    ),
  );
  markerObjectByTopic.forEach((object, topic) =>
    applyObjectFrameTransform(
      topic,
      object,
      sourceFrameByTopic.get(topic),
      sourceStampMsByTopic.get(topic) ?? null,
    ),
  );
  twistObjectByTopic.forEach((object, topic) =>
    applyObjectFrameTransform(
      topic,
      object,
      sourceFrameByTopic.get(topic),
      sourceStampMsByTopic.get(topic) ?? null,
    ),
  );
  obstacleZoneGroupByTopic.forEach((object, topic) =>
    applyObjectFrameTransform(
      topic,
      object,
      sourceFrameByTopic.get(topic),
      sourceStampMsByTopic.get(topic) ?? null,
    ),
  );
}

function safePointCloudSize(display: NavViewerDisplay) {
  const value = Number(display.pointSize ?? 0.08);
  if (!Number.isFinite(value)) {
    return 0.08;
  }
  return Math.min(0.6, Math.max(0.01, value));
}

function safePointCloudEmissiveIntensity(display: NavViewerDisplay) {
  const value = Number(display.pointEmissiveIntensity ?? 0);
  if (!Number.isFinite(value)) {
    return 0;
  }
  return Math.min(3, Math.max(0, value));
}

function safeTfLabelSize(display?: NavViewerDisplay) {
  const value = Number(display?.tfLabelSize ?? 0.5);
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

function amplifiedPointColor(colorText: string, intensity: number) {
  const color = new THREE.Color(colorText);
  color.multiplyScalar(1 + intensity * 0.75);
  return color;
}

function applyPointCloudMaterialConfig(
  material: THREE.PointsMaterial,
  display: NavViewerDisplay,
  useLayeredColors = pointColorModeForDisplay(display) === "layered",
) {
  const emissiveIntensity = safePointCloudEmissiveIntensity(display);
  material.vertexColors = useLayeredColors;
  material.color = useLayeredColors
    ? amplifiedPointColor("#ffffff", emissiveIntensity)
    : amplifiedPointColor(pointColorForDisplay(display), emissiveIntensity);
  material.size = safePointCloudSize(display);
  material.opacity = emissiveIntensity > 0 ? 0.98 : 0.96;
  material.transparent = true;
  material.depthWrite = emissiveIntensity <= 0;
  material.depthTest = true;
  material.blending =
    emissiveIntensity > 0 ? THREE.AdditiveBlending : THREE.NormalBlending;
  material.toneMapped = emissiveIntensity <= 0;
  material.needsUpdate = true;
}

function syncPointCloudLayeredColorAttribute(
  points: THREE.Points,
  display: NavViewerDisplay,
) {
  const geometry = points.geometry;
  const positionAttribute = geometry.getAttribute("position");
  if (
    pointColorModeForDisplay(display) !== "layered" ||
    !positionAttribute ||
    !(positionAttribute instanceof THREE.BufferAttribute) ||
    positionAttribute.itemSize !== 3
  ) {
    return;
  }
  const positions = Array.from(positionAttribute.array as ArrayLike<number>);
  const colors = buildPointCloudColorBuffer(
    positions,
    pointColorForDisplay(display),
    safePointCloudEmissiveIntensity(display),
  );
  const colorAttribute = geometry.getAttribute("color");
  if (
    colorAttribute &&
    colorAttribute instanceof THREE.BufferAttribute &&
    colorAttribute.itemSize === 3 &&
    colorAttribute.array.length === colors.length
  ) {
    (colorAttribute.array as Float32Array).set(colors);
    colorAttribute.needsUpdate = true;
  } else {
    geometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));
  }
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

function normalizeOccupancyGridData(data: unknown) {
  if (Array.isArray(data)) {
    return data;
  }
  if (ArrayBuffer.isView(data) && "length" in data) {
    return Array.from(data as unknown as ArrayLike<number>);
  }
  return [];
}

function syncPointCloudDisplayConfigs(displays: NavViewerDisplay[]) {
  displays.forEach((display) => {
    if (display.kind !== "pointcloud") {
      return;
    }
    const points = pointCloudByTopic.get(display.topic);
    const material = points?.material as THREE.PointsMaterial | undefined;
    if (!points || !material || Array.isArray(material)) {
      return;
    }
    syncPointCloudLayeredColorAttribute(points, display);
    applyPointCloudMaterialConfig(material, display);
  });
}

function syncPathDisplayConfigs(displays: NavViewerDisplay[]) {
  displays.forEach((display) => {
    if (display.kind !== "path" && display.kind !== "bspline") {
      return;
    }
    const line = pathLineByTopic.get(display.topic);
    const material = line?.material as THREE.LineBasicMaterial | undefined;
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
    const root = twistObjectByTopic.get(display.topic) as
      THREE.Group | undefined;
    if (!root) {
      return;
    }
    const arrow = root.getObjectByName(
      "twist-arrow",
    ) as THREE.ArrowHelper | null;
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
      (material as THREE.MeshStandardMaterial | THREE.MeshBasicMaterial).color =
        color;
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
  const hzLimit = Math.max(
    0,
    Math.round(Number(latestDisplay.hzLimit ?? 0) || 0),
  );
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
  const data = normalizeOccupancyGridData(message?.data);
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
    queueObjectFade(oldMesh, 0, 450, true);
    mapMeshByTopic.delete(topic);
  }
  mapTextureByTopic.delete(topic);

  const geometry = new THREE.PlaneGeometry(
    width * resolution,
    height * resolution,
  );
  const targetOpacity = mapOpacityForDisplay(
    display ?? {
      topic,
      messageType: "nav_msgs/msg/OccupancyGrid",
      kind: "map",
      label: topic,
    },
  );
  const material = new THREE.MeshBasicMaterial({
    map: texture,
    transparent: true,
    opacity: 0,
    side: THREE.DoubleSide,
    depthWrite: false,
    polygonOffset: true,
    polygonOffsetFactor: 1,
    polygonOffsetUnits: 1,
  });
  const plane = new THREE.Mesh(geometry, material);
  plane.position.set(
    (width * resolution) / 2,
    (height * resolution) / 2,
    -0.05,
  );

  const root = new THREE.Group();
  root.position.set(originX, originY, originZ);
  root.quaternion.set(
    Number(originRotation.x ?? 0),
    Number(originRotation.y ?? 0),
    Number(originRotation.z ?? 0),
    Number(originRotation.w ?? 1),
  );
  root.add(plane);
  sourceFrameByTopic.set(topic, normalizeFrameId(message?.header?.frame_id));
  sourceStampMsByTopic.set(topic, extractHeaderStampMs(message));
  cacheTopicLocalMatrix(
    topic,
    composeLocalMatrix(root.position.clone(), root.quaternion.clone()),
  );
  applyObjectFrameTransform(
    topic,
    root,
    message?.header?.frame_id,
    sourceStampMsByTopic.get(topic) ?? null,
  );

  scene.add(root);
  mapMeshByTopic.set(topic, root);
  mapTextureByTopic.set(topic, texture);
  queueObjectFade(root, targetOpacity, 650, false);
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
      Number(position.z ?? 0) + 0.05,
    );
  });

  const geometry = new THREE.BufferGeometry().setFromPoints(points);
  let line = pathLineByTopic.get(topic);
  if (!line) {
    const material = new THREE.LineBasicMaterial({
      color: pathColorForDisplay(
        display ?? {
          topic,
          messageType: "nav_msgs/Path",
          kind: "path",
          label: topic,
        },
      ),
      linewidth: 2,
    });
    line = new THREE.Line(geometry, material);
    scene.add(line);
    pathLineByTopic.set(topic, line);
  } else {
    replaceObjectGeometry(line, geometry);
    const material = line.material as THREE.LineBasicMaterial;
    if (material && !Array.isArray(material)) {
      material.color = new THREE.Color(
        pathColorForDisplay(
          display ?? {
            topic,
            messageType: "nav_msgs/Path",
            kind: "path",
            label: topic,
          },
        ),
      );
      material.needsUpdate = true;
    }
  }
  sourceFrameByTopic.set(topic, normalizeFrameId(message?.header?.frame_id));
  sourceStampMsByTopic.set(topic, extractHeaderStampMs(message));
  cacheTopicLocalMatrix(topic, composeLocalMatrix());
  applyObjectFrameTransform(
    topic,
    line,
    message?.header?.frame_id,
    sourceStampMsByTopic.get(topic) ?? null,
  );
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
    return controlPoints.flatMap((point: any) => [
      Number(point?.x ?? 0),
      Number(point?.y ?? 0),
      Number(point?.z ?? 0),
    ]);
  }

  const degree = Math.max(1, order - 1);
  const knots = Array.isArray(message?.knots)
    ? message.knots
        .map((value: unknown) => Number(value))
        .filter((value: number) => Number.isFinite(value))
    : [];
  const expectedKnotCount = controlPoints.length + order;
  if (knots.length < expectedKnotCount) {
    return controlPoints.flatMap((point: any) => [
      Number(point?.x ?? 0),
      Number(point?.y ?? 0),
      Number(point?.z ?? 0),
    ]);
  }

  const start = knots[Math.min(degree, knots.length - 1)];
  const end = knots[Math.max(degree, knots.length - degree - 1)];
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) {
    return controlPoints.flatMap((point: any) => [
      Number(point?.x ?? 0),
      Number(point?.y ?? 0),
      Number(point?.z ?? 0),
    ]);
  }

  const points = controlPoints.map(
    (point: any) =>
      new THREE.Vector3(
        Number(point?.x ?? 0),
        Number(point?.y ?? 0),
        Number(point?.z ?? 0),
      ),
  );
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
    const work = Array.from({ length: degree + 1 }, (_, index) =>
      points[span - degree + index].clone(),
    );
    for (let level = 1; level <= degree; level += 1) {
      for (let index = degree; index >= level; index -= 1) {
        const knotLeft = knots[span - degree + index];
        const knotRight = knots[span + 1 + index - level];
        const denominator = knotRight - knotLeft;
        const alpha =
          denominator > 1e-6 ? (clampedT - knotLeft) / denominator : 0;
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
    geometry.setAttribute(
      "position",
      new THREE.Float32BufferAttribute(sampledPositions, 3),
    );
    const material = new THREE.LineBasicMaterial({
      color: pathColorForDisplay(latestDisplay),
    });
    line = new THREE.Line(geometry, material);
    scene?.add(line);
    pathLineByTopic.set(topic, line);
  } else {
    replaceObjectGeometry(
      line,
      new THREE.BufferGeometry().setAttribute(
        "position",
        new THREE.Float32BufferAttribute(sampledPositions, 3),
      ),
    );
    const material = line.material as THREE.LineBasicMaterial;
    if (material && !Array.isArray(material)) {
      material.color = new THREE.Color(pathColorForDisplay(latestDisplay));
      material.needsUpdate = true;
    }
  }
  sourceFrameByTopic.set(
    topic,
    normalizeFrameId(message?.header?.frame_id) || currentFixedFrame(),
  );
  sourceStampMsByTopic.set(topic, extractHeaderStampMs(message));
  cacheTopicLocalMatrix(topic, composeLocalMatrix());
  applyObjectFrameTransform(
    topic,
    line,
    sourceFrameByTopic.get(topic),
    sourceStampMsByTopic.get(topic) ?? null,
  );
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
  const match = fields.find(
    (field: { name: string }) =>
      String(field?.name ?? "").toLowerCase() === fieldName,
  );
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
function buildPointCloudColorBuffer(
  positions: number[],
  baseColorText: string,
  emissiveIntensity = 0,
) {
  const pointCount = Math.floor(positions.length / 3);
  const colors = new Float32Array(pointCount * 3);
  if (pointCount <= 0) {
    return colors;
  }

  const statsSampleCount = Math.min(pointCount, 1024);
  const statsSampleStep = Math.max(
    1,
    Math.floor(pointCount / statsSampleCount),
  );
  const zSamples: number[] = [];
  for (let index = 0; index < positions.length; index += 3) {
    const z = positions[index + 2];
    if (
      (index / 3) % statsSampleStep === 0 &&
      zSamples.length < statsSampleCount
    ) {
      zSamples.push(z);
    }
  }

  const baseColor = new THREE.Color(baseColorText);
  const baseHsl = { h: 0, s: 0, l: 0 };
  baseColor.getHSL(baseHsl);
  const sortedZValues = [...zSamples].sort((left, right) => left - right);
  const medianIndex = Math.floor(sortedZValues.length / 2);
  const medianZ = sortedZValues[medianIndex];
  const upperQuartileZ =
    sortedZValues[
      Math.min(
        sortedZValues.length - 1,
        Math.floor(sortedZValues.length * 0.75),
      )
    ];
  const upperReferenceRange = Math.max(
    0.08,
    upperQuartileZ - medianZ,
    sortedZValues[sortedZValues.length - 1] - medianZ,
  );
  const complementaryColor = new THREE.Color().setHSL(
    (baseHsl.h + 0.5) % 1,
    Math.min(1, Math.max(0.45, baseHsl.s * 0.95 + 0.06)),
    Math.min(0.68, Math.max(0.26, baseHsl.l * 0.9)),
  );
  const color = new THREE.Color();
  const colorBoost = 1 + Math.min(3, Math.max(0, emissiveIntensity)) * 0.75;

  for (
    let pointIndex = 0, index = 0;
    index < positions.length;
    index += 3, pointIndex += 1
  ) {
    const z = positions[index + 2];
    const relativeHeight = (z - medianZ) / upperReferenceRange;
    const positiveHeightRatio = Math.min(1, Math.max(0, relativeHeight));
    const negativeHeightRatio = Math.min(
      1,
      Math.max(0, -relativeHeight * 0.45),
    );
    const obstacleBlend = positiveHeightRatio * positiveHeightRatio;
    color
      .copy(baseColor)
      .lerp(complementaryColor, Math.min(0.82, obstacleBlend * 0.78));
    const currentHsl = color.getHSL({ h: 0, s: 0, l: 0 });
    const saturation = Math.min(
      1,
      Math.max(
        0.38,
        currentHsl.s + obstacleBlend * 0.08 - negativeHeightRatio * 0.04,
      ),
    );
    const lightness = Math.min(
      0.72,
      Math.max(
        0.24,
        currentHsl.l - obstacleBlend * 0.06 - negativeHeightRatio * 0.02,
      ),
    );
    color.setHSL(currentHsl.h, saturation, lightness);
    color.multiplyScalar(colorBoost);
    const offset = pointIndex * 3;
    colors[offset] = color.r;
    colors[offset + 1] = color.g;
    colors[offset + 2] = color.b;
  }
  return colors;
}

function boundsSize(bounds: BoundsPayload, axis: "x" | "y" | "z") {
  if (axis === "x") {
    return Math.max(0, bounds.xmax - bounds.xmin);
  }
  if (axis === "y") {
    return Math.max(0, bounds.ymax - bounds.ymin);
  }
  return Math.max(0, bounds.zmax - bounds.zmin);
}

function cloneBounds(bounds: BoundsPayload): BoundsPayload {
  return {
    xmin: Number(bounds.xmin),
    xmax: Number(bounds.xmax),
    ymin: Number(bounds.ymin),
    ymax: Number(bounds.ymax),
    zmin: Number(bounds.zmin),
    zmax: Number(bounds.zmax),
  };
}

function createMapYamlReference(mapInfo: OfflineMapInfoPayload | null) {
  if (!mapInfo) {
    return null;
  }
  const origin = Array.isArray(mapInfo.origin) ? mapInfo.origin : [0, 0, 0];
  const originX = Number(origin[0] ?? 0);
  const originY = Number(origin[1] ?? 0);
  const yaw = Number(origin[2] ?? 0);
  const widthM = Number(mapInfo.width) * Number(mapInfo.resolution);
  const heightM = Number(mapInfo.height) * Number(mapInfo.resolution);
  if (
    !Number.isFinite(widthM) ||
    !Number.isFinite(heightM) ||
    widthM <= 0 ||
    heightM <= 0
  ) {
    return null;
  }

  const group = new THREE.Group();
  group.name = "offline-map-yaml-reference";
  const centerLocal = new THREE.Vector3(
    widthM / 2,
    heightM / 2,
    -0.015,
  ).applyAxisAngle(new THREE.Vector3(0, 0, 1), yaw);
  group.position.set(
    originX + centerLocal.x,
    originY + centerLocal.y,
    centerLocal.z,
  );
  group.rotation.z = yaw;

  const planeMaterial = new THREE.MeshBasicMaterial({
    color: "#ffffff",
    transparent: true,
    opacity: 0.34,
    depthWrite: false,
    side: THREE.DoubleSide,
  });
  const plane = new THREE.Mesh(
    new THREE.PlaneGeometry(widthM, heightM),
    planeMaterial,
  );
  plane.name = "offline-map-yaml-plane";
  group.add(plane);

  if (mapInfo.image_path) {
    const textureUrl = `/api/files/pgm-image?path=${encodeURIComponent(mapInfo.image_path)}`;
    new THREE.TextureLoader().load(
      textureUrl,
      (texture) => {
        texture.colorSpace = THREE.SRGBColorSpace;
        texture.needsUpdate = true;
        planeMaterial.map = texture;
        planeMaterial.color = new THREE.Color("#ffffff");
        planeMaterial.needsUpdate = true;
      },
      undefined,
      () => {
        planeMaterial.color = new THREE.Color("#18283b");
        planeMaterial.opacity = 0.18;
        planeMaterial.needsUpdate = true;
      },
    );
  }

  const halfW = widthM / 2;
  const halfH = heightM / 2;
  const borderPoints = [
    new THREE.Vector3(-halfW, -halfH, 0.005),
    new THREE.Vector3(halfW, -halfH, 0.005),
    new THREE.Vector3(halfW, halfH, 0.005),
    new THREE.Vector3(-halfW, halfH, 0.005),
    new THREE.Vector3(-halfW, -halfH, 0.005),
  ];
  const border = new THREE.Line(
    new THREE.BufferGeometry().setFromPoints(borderPoints),
    new THREE.LineBasicMaterial({
      color: "#8cd867",
      transparent: true,
      opacity: 0.86,
    }),
  );
  border.name = "offline-map-yaml-border";
  group.add(border);
  return group;
}

function updateOfflineMapGeometry() {
  if (!offlineMapClipBounds) {
    return;
  }
  updateOfflineMapPointCloudGeometry();
  updateOfflineMapVoxelGeometry();
}

function disposeOfflineVoxelRender() {
  offlineVoxelRender?.dispose();
  offlineVoxelRender = null;
  offlineRenderEnvironmentTransition = null;
  if (offlineMapVoxelMesh) {
    setVoxelGrowthMaterialMode(offlineMapVoxelMesh.material, "voxel");
    updateVoxelGrowthTime(
      offlineMapVoxelMesh.material,
      offlineVoxelAnimationDurationSeconds || 9999,
    );
  }
}

function currentOfflineRenderEnvironmentProgress(now = performance.now()) {
  if (!offlineRenderEnvironmentTransition) {
    return offlineMapDisplayMode.value === "render" ? 1 : 0;
  }
  const transition = offlineRenderEnvironmentTransition;
  const progress = THREE.MathUtils.clamp(
    (now - transition.startedAt) / transition.durationMs,
    0,
    1,
  );
  return THREE.MathUtils.lerp(transition.from, transition.to, progress);
}

function startOfflineRenderEnvironmentTransition(
  to: number,
  disposeOnDone: boolean,
  from = currentOfflineRenderEnvironmentProgress(),
) {
  offlineRenderEnvironmentTransition = {
    startedAt: performance.now(),
    durationMs: 650,
    from,
    to,
    disposeOnDone,
  };
}

function updateOfflineRenderEnvironmentTransition(now: number) {
  if (!offlineVoxelRender || !offlineRenderEnvironmentTransition) {
    return;
  }
  const transition = offlineRenderEnvironmentTransition;
  const progress = THREE.MathUtils.clamp(
    (now - transition.startedAt) / transition.durationMs,
    0,
    1,
  );
  offlineVoxelRender.setTransitionProgress(
    THREE.MathUtils.lerp(transition.from, transition.to, progress),
  );
  if (progress < 1) {
    return;
  }
  const shouldDispose = transition.disposeOnDone;
  offlineRenderEnvironmentTransition = null;
  if (shouldDispose) {
    disposeOfflineVoxelRender();
  }
}

function syncOfflineVoxelRender() {
  if (offlineMapDisplayMode.value !== "render") {
    return;
  }
  if (!scene || !renderer || !offlineMapVoxelMesh) {
    return;
  }
  setVoxelGrowthMaterialMode(offlineMapVoxelMesh.material, "render");
  if (!offlineVoxelRender) {
    offlineVoxelRender = createOfflineVoxelRender(
      scene,
      renderer,
      offlineMapVoxelMesh,
    );
    startOfflineRenderEnvironmentTransition(1, false, 0);
  } else {
    offlineVoxelRender.update();
  }
}

function updateOfflineMapVisibility() {
  if (offlineMapPoints) {
    offlineMapPoints.visible = offlineMapDisplayMode.value === "pointcloud";
  }
  if (offlineMapVoxelMesh) {
    offlineMapVoxelMesh.visible =
      offlineMapDisplayMode.value === "voxel" ||
      offlineMapDisplayMode.value === "render";
  }
  syncOfflineVoxelRender();
}

function offlineModeObject(mode: OfflineMapDisplayMode) {
  if (mode === "pointcloud") {
    return offlineMapPoints;
  }
  return offlineMapVoxelMesh;
}

function offlineModeTargetFade(mode: OfflineMapDisplayMode) {
  return mode === "pointcloud" ? 0.88 : 1;
}

function fadeOfflineModeObjects(
  previousMode: OfflineMapDisplayMode,
  nextMode: OfflineMapDisplayMode,
) {
  const previousObject = offlineModeObject(previousMode);
  const nextObject = offlineModeObject(nextMode);
  if (!previousObject || !nextObject || previousObject === nextObject) {
    return;
  }
  previousObject.visible = true;
  nextObject.visible = true;
  const nextMaterialTargets = collectObjectMaterials(nextObject).map(
    (material) => ({
      material,
      target: offlineModeTargetFade(nextMode),
    }),
  );
  nextMaterialTargets.forEach(({ material }) =>
    setMaterialFadeValue(material, 0),
  );
  queueObjectFade(previousObject, 0, 320, false);
  sceneFadeItems.push({
    object: nextObject,
    startedAt: performance.now(),
    durationMs: 420,
    disposeAfter: false,
    materials: nextMaterialTargets.map(({ material, target }) => ({
      material,
      from: 0,
      to: target,
    })),
  });
}

function restartOfflineVoxelGrowth(options: { anchorDemo?: boolean } = {}) {
  if (!offlineMapVoxelMesh) {
    return;
  }
  offlineVoxelAnimationStartMs = performance.now();
  updateVoxelGrowthTime(offlineMapVoxelMesh.material, 0);
  if (options.anchorDemo) {
    offlineSceneAnchorStartMs = offlineVoxelAnimationStartMs;
    offlineSceneAnchorUntilMs =
      offlineVoxelAnimationStartMs +
      Math.max(offlineVoxelAnimationDurationSeconds * 1000, 650);
  }
}

function settleOfflineVoxelGrowth() {
  if (!offlineMapVoxelMesh) {
    return;
  }
  const durationSeconds = offlineVoxelAnimationDurationSeconds || 9999;
  offlineVoxelAnimationStartMs = performance.now() - durationSeconds * 1000;
  updateVoxelGrowthTime(offlineMapVoxelMesh.material, durationSeconds);
  if (offlineMapDisplayMode.value === "render" && offlineVoxelRender) {
    offlineVoxelRender.setTransitionProgress(1);
  }
}

function currentOfflineVoxelVisualCenter() {
  if (lastRobotPose) {
    const position = new THREE.Vector3();
    lastRobotPose.decompose(
      position,
      new THREE.Quaternion(),
      new THREE.Vector3(),
    );
    return new THREE.Vector2(position.x, position.y);
  }
  if (controls) {
    return new THREE.Vector2(controls.target.x, controls.target.y);
  }
  return new THREE.Vector2(0, 0);
}

function updateOfflineVoxelGrowthFrame(now: number) {
  if (!offlineMapVoxelMesh || !offlineMapVoxelMesh.visible) {
    updateOfflineRenderEnvironmentTransition(now);
    return;
  }
  const elapsedSeconds = Math.max(
    0,
    (now - offlineVoxelAnimationStartMs) / 1000,
  );
  updateVoxelGrowthTime(offlineMapVoxelMesh.material, elapsedSeconds);
  if (offlineMapDisplayMode.value === "render" && offlineVoxelRender) {
    updateOfflineRenderEnvironmentTransition(now);
  } else {
    updateOfflineRenderEnvironmentTransition(now);
  }
  if (offlineMapDisplayMode.value === "render" && renderer) {
    renderer.shadowMap.needsUpdate = true;
  }
}

function offlineSceneAnchorProgress(now: number) {
  if (offlineSceneAnchorUntilMs <= offlineSceneAnchorStartMs) {
    return 1;
  }
  return THREE.MathUtils.clamp(
    (now - offlineSceneAnchorStartMs) /
      (offlineSceneAnchorUntilMs - offlineSceneAnchorStartMs),
    0,
    1,
  );
}

function updateOfflineAnchorCamera(now: number) {
  if (!controls || !camera || !arena || now >= offlineSceneAnchorUntilMs) {
    return;
  }
  const robotPosition = arena.getRobotPosition();
  const target = new THREE.Vector3(robotPosition.x, robotPosition.y, 0.25);
  const previousTarget = controls.target.clone();
  controls.target.lerp(target, 0.08);
  camera.position.add(controls.target.clone().sub(previousTarget));
}

function updateOfflineMapPointCloudGeometry() {
  if (!offlineMapRawPositions || !offlineMapPoints || !offlineMapClipBounds) {
    return;
  }
  const bounds = offlineMapClipBounds;
  const positions: number[] = [];
  for (let index = 0; index < offlineMapRawPositions.length; index += 3) {
    const x = offlineMapRawPositions[index];
    const y = offlineMapRawPositions[index + 1];
    const z = offlineMapRawPositions[index + 2];
    if (
      x < bounds.xmin ||
      x > bounds.xmax ||
      y < bounds.ymin ||
      y > bounds.ymax ||
      z < bounds.zmin ||
      z > bounds.zmax
    ) {
      continue;
    }
    positions.push(x, y, z);
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute(
    "position",
    new THREE.Float32BufferAttribute(positions, 3),
  );
  geometry.setAttribute(
    "color",
    new THREE.BufferAttribute(
      buildPointCloudColorBuffer(positions, offlineMapPointColor),
      3,
    ),
  );
  geometry.computeBoundingSphere();
  replaceObjectGeometry(offlineMapPoints, geometry);
  const material = offlineMapPoints.material;
  if (!Array.isArray(material)) {
    material.vertexColors = true;
    material.needsUpdate = true;
  }
  updateOfflineMapVisibility();
  sceneStatus.value = `离线地图点云显示 ${Math.floor(positions.length / 3)} / ${Math.floor(offlineMapRawPositions.length / 3)} 点`;
}

function updateOfflineMapVoxelGeometry(
  options: { animate?: boolean; anchorDemo?: boolean } = {},
) {
  if (
    !offlineMapVoxelCenters ||
    !offlineMapVoxelMesh ||
    !offlineMapClipBounds
  ) {
    return;
  }
  const bounds = offlineMapClipBounds;
  const matrix = new THREE.Matrix4();
  const scale = new THREE.Vector3(
    offlineMapVoxelSize * 0.94,
    offlineMapVoxelSize * 0.94,
    offlineMapVoxelSize * 0.94,
  );
  const rotation = new THREE.Quaternion();
  const visibleCenters: number[] = [];
  let visibleCount = 0;
  for (let index = 0; index < offlineMapVoxelCenters.length; index += 3) {
    const x = offlineMapVoxelCenters[index];
    const y = offlineMapVoxelCenters[index + 1];
    const z = offlineMapVoxelCenters[index + 2];
    const half = offlineMapVoxelSize * 0.5;
    if (
      x + half < bounds.xmin ||
      x - half > bounds.xmax ||
      y + half < bounds.ymin ||
      y - half > bounds.ymax ||
      z + half < bounds.zmin ||
      z - half > bounds.zmax
    ) {
      continue;
    }
    matrix.compose(new THREE.Vector3(x, y, z), rotation, scale);
    offlineMapVoxelMesh.setMatrixAt(visibleCount, matrix);
    offlineMapVoxelMesh.setColorAt(
      visibleCount,
      voxelSurfaceColor(
        x,
        y,
        z,
        offlineMapVoxelSize,
        offlineVoxelBaseColor,
        offlineVoxelColor,
      ),
    );
    visibleCenters.push(x, y, z);
    visibleCount += 1;
  }
  offlineMapVoxelMesh.instanceMatrix.needsUpdate = true;
  if (offlineMapVoxelMesh.instanceColor) {
    offlineMapVoxelMesh.instanceColor.needsUpdate = true;
  }
  offlineVoxelAnimationDurationSeconds = configureVoxelGrowthAttributes(
    offlineMapVoxelMesh,
    visibleCenters,
    offlineMapVoxelSize,
    (offlineVoxelAnimationVersion += 1),
    currentOfflineVoxelVisualCenter(),
  );
  if (options.animate) {
    restartOfflineVoxelGrowth({ anchorDemo: options.anchorDemo });
  } else {
    settleOfflineVoxelGrowth();
  }
  updateOfflineMapVisibility();
  if (offlineMapDisplayMode.value === "voxel") {
    sceneStatus.value = `离线占据网格显示 ${visibleCount} / ${Math.floor(offlineMapVoxelCenters.length / 3)} 个 voxel`;
  } else if (offlineMapDisplayMode.value === "render") {
    sceneStatus.value = `离线渲染显示 ${visibleCount} / ${Math.floor(offlineMapVoxelCenters.length / 3)} 个 voxel`;
  }
}

function buildOfflineMapVoxelMesh() {
  if (!offlineMapVoxelCenters || offlineMapVoxelCenters.length === 0) {
    return null;
  }
  const voxelCount = Math.floor(offlineMapVoxelCenters.length / 3);
  const geometry = createVoxelGrowthGeometry();
  const material = createVoxelGrowthMaterial("voxel");
  const mesh = new THREE.InstancedMesh(geometry, material, voxelCount);
  mesh.name = "offline-map-voxel-preview";
  mesh.frustumCulled = false;
  mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
  return mesh;
}

function buildVoxelCentersFromPointCloud(
  positions: Float32Array,
  voxelSize: number,
) {
  const occupied = new Map<string, [number, number, number]>();
  const half = voxelSize * 0.5;
  for (let index = 0; index < positions.length; index += 3) {
    const ix = Math.floor(positions[index] / voxelSize + 1e-9);
    const iy = Math.floor(positions[index + 1] / voxelSize + 1e-9);
    const iz = Math.floor(positions[index + 2] / voxelSize + 1e-9);
    const key = `${ix},${iy},${iz}`;
    if (!occupied.has(key)) {
      occupied.set(key, [
        ix * voxelSize + half,
        iy * voxelSize + half,
        iz * voxelSize + half,
      ]);
    }
  }
  const centers = new Float32Array(occupied.size * 3);
  let cursor = 0;
  occupied.forEach((center) => {
    centers[cursor] = center[0];
    centers[cursor + 1] = center[1];
    centers[cursor + 2] = center[2];
    cursor += 3;
  });
  return centers;
}

function setOfflineMapDisplayMode(mode: OfflineMapDisplayMode) {
  if (!offlineMapRawPositions && !offlineMapVoxelCenters) {
    return { ok: false, message: "请先加载离线地图。" };
  }
  const previousMode = offlineMapDisplayMode.value;
  const environmentProgress = currentOfflineRenderEnvironmentProgress();
  offlineMapDisplayMode.value = mode;
  if (previousMode === "render" && mode !== "render" && offlineVoxelRender) {
    offlineVoxelRender.restoreMeshMaterial();
    if (offlineMapVoxelMesh) {
      setVoxelGrowthMaterialMode(offlineMapVoxelMesh.material, "voxel");
      collectObjectMaterials(offlineMapVoxelMesh).forEach((material) =>
        setMaterialFadeValue(material, 1),
      );
      updateVoxelGrowthTime(
        offlineMapVoxelMesh.material,
        offlineVoxelAnimationDurationSeconds || 9999,
      );
    }
  }
  updateOfflineMapVisibility();
  if (mode !== previousMode) {
    fadeOfflineModeObjects(previousMode, mode);
  }
  if (previousMode === "render" && mode !== "render" && offlineVoxelRender) {
    startOfflineRenderEnvironmentTransition(0, true, environmentProgress);
  } else if (
    previousMode !== "render" &&
    mode === "render" &&
    offlineVoxelRender
  ) {
    startOfflineRenderEnvironmentTransition(1, false, environmentProgress);
  }
  if (mode !== previousMode && (mode === "voxel" || mode === "render")) {
    restartOfflineVoxelGrowth();
  }
  if (mode === "voxel" && offlineMapVoxelCenters) {
    sceneStatus.value = `已切换到占据网格显示: ${Math.floor(offlineMapVoxelCenters.length / 3)} 个 voxel。`;
    return { ok: true, message: sceneStatus.value };
  } else if (
    mode === "render" &&
    offlineMapVoxelMesh &&
    offlineMapVoxelCenters
  ) {
    offlineVoxelRender?.update();
    sceneStatus.value = `已切换到渲染显示: ${offlineMapVoxelMesh.count} / ${Math.floor(offlineMapVoxelCenters.length / 3)} 个 voxel。`;
    return { ok: true, message: sceneStatus.value };
  } else if (mode === "pointcloud" && offlineMapRawPositions) {
    sceneStatus.value = `已切换到点云显示: ${Math.floor(offlineMapRawPositions.length / 3)} 点。`;
    return { ok: true, message: sceneStatus.value };
  }
  return { ok: false, message: "当前离线地图缺少对应显示数据。" };
}

/**
 * 更新已经加载的离线地图外观，不重新读取 PCD，避免调整点大小或配色时造成额外加载等待。
 * 颜色只接受由控制器校验后的十六进制值，保证 Three.js 材质始终能正确解析。
 */
function updateOfflineMapVisualSettings(settings: OfflineMapVisualSettings) {
  if (
    typeof settings.pointSize === "number" &&
    Number.isFinite(settings.pointSize)
  ) {
    offlineMapPointSize = settings.pointSize;
    if (
      offlineMapPoints &&
      offlineMapPoints.material instanceof THREE.PointsMaterial
    ) {
      offlineMapPoints.material.size = offlineMapPointSize;
      offlineMapPoints.material.needsUpdate = true;
    }
  }
  if (typeof settings.pointColor === "string" && settings.pointColor) {
    offlineMapPointColor = settings.pointColor;
    updateOfflineMapPointCloudGeometry();
  }
  if (typeof settings.voxelColor === "string" && settings.voxelColor) {
    offlineMapVoxelColor = settings.voxelColor;
    offlineVoxelBaseColor.set(offlineMapVoxelColor);
    updateOfflineMapVoxelGeometry();
  }
  if (settings.displayMode) {
    setOfflineMapDisplayMode(settings.displayMode);
  }
}

function attachOfflineMapPointCloud(payload: OfflineMapPointCloudPayload) {
  if (!scene) {
    return { ok: false, message: "三维场景尚未初始化。" };
  }
  const shouldAnchorDemoTransition =
    !hasConnected && !hasOfflineMapRaycastCache();
  const points = Array.isArray(payload?.pcd?.points) ? payload.pcd.points : [];
  const positions = new Float32Array(points.length * 3);
  let cursor = 0;
  for (const point of points) {
    const x = Number(point?.[0]);
    const y = Number(point?.[1]);
    const z = Number(point?.[2]);
    if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(z)) {
      continue;
    }
    positions[cursor] = x;
    positions[cursor + 1] = y;
    positions[cursor + 2] = z;
    cursor += 3;
  }
  if (cursor <= 0) {
    return { ok: false, message: "离线 PCD 没有可显示的有效点。" };
  }

  clearOfflineMapPointCloud(true);
  offlineMapDisplayMode.value = "voxel";
  offlineMapRawPositions = positions.slice(0, cursor);
  offlineMapVoxelSize = Math.max(
    0.03,
    Number(payload.occupancy?.voxel_m || payload.pcd.voxel_leaf_m || 0.1),
  );
  const voxelCenters = Array.isArray(payload.occupancy?.voxels)
    ? payload.occupancy.voxels
    : [];
  const voxelPositions = new Float32Array(voxelCenters.length * 3);
  let voxelCursor = 0;
  for (const voxel of voxelCenters) {
    const x = Number(voxel?.[0]);
    const y = Number(voxel?.[1]);
    const z = Number(voxel?.[2]);
    if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(z)) {
      continue;
    }
    voxelPositions[voxelCursor] = x;
    voxelPositions[voxelCursor + 1] = y;
    voxelPositions[voxelCursor + 2] = z;
    voxelCursor += 3;
  }
  offlineMapVoxelCenters =
    voxelCursor > 0
      ? voxelPositions.slice(0, voxelCursor)
      : buildVoxelCentersFromPointCloud(
          offlineMapRawPositions,
          offlineMapVoxelSize,
        );
  offlineMapOriginalBounds = cloneBounds(payload.pcd.sampled_bounds);
  offlineMapClipBounds = cloneBounds(payload.pcd.sampled_bounds);
  syncOfflineClipBoundsView();
  offlineClipActive.value = true;
  offlineMapGroup = new THREE.Group();
  offlineMapGroup.name = "offline-map-pointcloud-root";

  const mapReference = createMapYamlReference(payload.map);
  if (mapReference) {
    offlineMapGroup.add(mapReference);
  }

  const geometry = new THREE.BufferGeometry();
  const initialPositions = Array.from(offlineMapRawPositions);
  geometry.setAttribute(
    "position",
    new THREE.Float32BufferAttribute(initialPositions, 3),
  );
  geometry.setAttribute(
    "color",
    new THREE.BufferAttribute(
      buildPointCloudColorBuffer(initialPositions, offlineMapPointColor),
      3,
    ),
  );
  geometry.computeBoundingSphere();
  const material = new THREE.PointsMaterial({
    color: "#ffffff",
    size: offlineMapPointSize,
    sizeAttenuation: true,
    vertexColors: true,
    transparent: true,
    opacity: 0.88,
    depthWrite: true,
    depthTest: true,
  });
  offlineMapPoints = new THREE.Points(geometry, material);
  offlineMapPoints.name = "offline-map-pointcloud-preview";
  offlineMapGroup.add(offlineMapPoints);
  offlineMapVoxelMesh = buildOfflineMapVoxelMesh();
  if (offlineMapVoxelMesh) {
    offlineMapGroup.add(offlineMapVoxelMesh);
    updateOfflineMapVoxelGeometry({
      animate: true,
      anchorDemo: shouldAnchorDemoTransition,
    });
  }
  scene.add(offlineMapGroup);
  setOfflineMapDisplayMode("render");
  const displayedVoxelCount = Math.floor(
    (offlineMapVoxelCenters?.length ?? 0) / 3,
  );
  const sourceVoxelCount =
    payload.occupancy?.occupied_count && payload.occupancy.occupied_count > 0
      ? payload.occupancy.occupied_count
      : displayedVoxelCount;
  sceneStatus.value = `已加载离线地图: ${payload.pcd.sampled_count} / ${payload.pcd.input_points} 点，${displayedVoxelCount} / ${sourceVoxelCount} 个占据 voxel。`;
  return { ok: true, message: sceneStatus.value };
}

function clearOfflineMapPointCloud(fadeOut = false) {
  const groupToClear = offlineMapGroup;
  if (fadeOut && groupToClear) {
    offlineVoxelRender?.dispose({ restoreMaterial: false });
    offlineVoxelRender = null;
    queueObjectFade(groupToClear, 0, 450, true);
  } else {
    disposeOfflineVoxelRender();
    if (groupToClear) {
      clearThreeObject(groupToClear);
    }
  }
  if (offlineMapGroup) {
    offlineMapGroup = null;
  }
  offlineMapPoints = null;
  offlineMapVoxelMesh = null;
  offlineMapRawPositions = null;
  offlineMapVoxelCenters = null;
  offlineMapVoxelSize = 0.1;
  offlineMapOriginalBounds = null;
  offlineMapClipBounds = null;
  syncOfflineClipBoundsView();
  offlineClipActive.value = false;
  activeOfflineClipFace.value = null;
}

function moveOfflineClipFace(face: keyof BoundsPayload, direction: -1 | 1) {
  if (!offlineMapClipBounds || !offlineMapOriginalBounds) {
    sceneStatus.value = "请先加载离线地图点云。";
    return;
  }
  const axis = face.startsWith("x") ? "x" : face.startsWith("y") ? "y" : "z";
  const minKey = `${axis}min` as keyof BoundsPayload;
  const maxKey = `${axis}max` as keyof BoundsPayload;
  const span = Math.max(0.05, boundsSize(offlineMapOriginalBounds, axis));
  const step = Math.max(0.02, span * 0.035);
  const minGap = Math.max(0.02, span * 0.01);
  const originalMin = offlineMapOriginalBounds[minKey];
  const originalMax = offlineMapOriginalBounds[maxKey];
  const nextValue = offlineMapClipBounds[face] + direction * step;
  if (face.endsWith("min")) {
    offlineMapClipBounds[face] = Math.min(
      Math.max(nextValue, originalMin),
      offlineMapClipBounds[maxKey] - minGap,
    );
  } else {
    offlineMapClipBounds[face] = Math.max(
      Math.min(nextValue, originalMax),
      offlineMapClipBounds[minKey] + minGap,
    );
  }
  updateOfflineMapGeometry();
}

function resetOfflineClipBounds() {
  if (!offlineMapOriginalBounds) {
    sceneStatus.value = "请先加载离线地图点云。";
    return;
  }
  offlineMapClipBounds = cloneBounds(offlineMapOriginalBounds);
  syncOfflineClipBoundsView();
  updateOfflineMapGeometry();
}

function clipAxisForFace(face: keyof BoundsPayload) {
  return face.startsWith("x") ? "x" : face.startsWith("y") ? "y" : "z";
}

function setOfflineClipFaceValue(face: keyof BoundsPayload, value: number) {
  if (!offlineMapClipBounds || !offlineMapOriginalBounds) {
    return;
  }
  const axis = clipAxisForFace(face);
  const minKey = `${axis}min` as keyof BoundsPayload;
  const maxKey = `${axis}max` as keyof BoundsPayload;
  const span = Math.max(0.05, boundsSize(offlineMapOriginalBounds, axis));
  const minGap = Math.max(0.02, span * 0.01);
  const originalMin = offlineMapOriginalBounds[minKey];
  const originalMax = offlineMapOriginalBounds[maxKey];
  if (face.endsWith("min")) {
    offlineMapClipBounds[face] = Math.min(
      Math.max(value, originalMin),
      offlineMapClipBounds[maxKey] - minGap,
    );
  } else {
    offlineMapClipBounds[face] = Math.max(
      Math.min(value, originalMax),
      offlineMapClipBounds[minKey] + minGap,
    );
  }
  syncOfflineClipBoundsView();
  updateOfflineMapGeometry();
}

// 手柄方向键映射：按键方向与手柄朝向一致表示扩大该方向裁剪范围，相反则收缩
const offlineClipFaceArrowMap: Record<
  keyof BoundsPayload,
  { expand: string[]; shrink: string[] }
> = {
  xmin: { expand: ["ArrowLeft"], shrink: ["ArrowRight"] },
  xmax: { expand: ["ArrowRight"], shrink: ["ArrowLeft"] },
  ymin: {
    expand: ["ArrowLeft", "ArrowDown"],
    shrink: ["ArrowRight", "ArrowUp"],
  },
  ymax: {
    expand: ["ArrowRight", "ArrowUp"],
    shrink: ["ArrowLeft", "ArrowDown"],
  },
  zmin: { expand: ["ArrowDown"], shrink: ["ArrowUp"] },
  zmax: { expand: ["ArrowUp"], shrink: ["ArrowDown"] },
};

function handleOfflineClipFaceKeydown(
  face: keyof BoundsPayload,
  event: KeyboardEvent,
) {
  if (!offlineClipActive.value) {
    return;
  }
  const arrowKeys = offlineClipFaceArrowMap[face];
  // max 面向正方向扩展为“扩大”，min 面向负方向扩展为“扩大”
  const outwardDirection: 1 | -1 = face.endsWith("max") ? 1 : -1;
  if (arrowKeys.expand.includes(event.key)) {
    event.preventDefault();
    moveOfflineClipFace(face, outwardDirection);
  } else if (arrowKeys.shrink.includes(event.key)) {
    event.preventDefault();
    moveOfflineClipFace(face, -outwardDirection as 1 | -1);
  }
}

function clipDragDirectionMultiplier(face: keyof BoundsPayload) {
  // 左、后、下三个轴的屏幕拖动直觉与基础数值方向相反，单独翻转以保持操作一致。
  return face === "xmin" || face === "ymin" || face === "zmin" ? -1 : 1;
}

function beginOfflineClipFaceDrag(
  face: keyof BoundsPayload,
  event: PointerEvent,
) {
  if (!offlineClipActive.value || !offlineMapClipBounds) {
    sceneStatus.value = "请先加载离线地图点云。";
    return;
  }
  offlineClipDragFace = face;
  offlineClipDragStartX = event.clientX;
  offlineClipDragStartY = event.clientY;
  offlineClipDragStartValue = offlineMapClipBounds[face];
  activeOfflineClipFace.value = face;
  const target = event.currentTarget;
  if (target instanceof HTMLElement) {
    target.setPointerCapture(event.pointerId);
    // pointerdown 被 prevent 后浏览器不会自动聚焦，这里补上以便方向键微调
    target.focus();
  }
}

function dragOfflineClipFace(event: PointerEvent) {
  if (!offlineClipDragFace || !offlineMapOriginalBounds) {
    return;
  }
  const face = offlineClipDragFace;
  const axis = clipAxisForFace(face);
  const span = Math.max(0.05, boundsSize(offlineMapOriginalBounds, axis));
  const deltaX = event.clientX - offlineClipDragStartX;
  const deltaY = event.clientY - offlineClipDragStartY;
  const movementScale = span / 180;
  const projectedDistance = axis === "z" ? -deltaY : deltaX;
  const baseSignedDistance = face.endsWith("min")
    ? -projectedDistance * movementScale
    : projectedDistance * movementScale;
  const signedDistance = baseSignedDistance * clipDragDirectionMultiplier(face);
  setOfflineClipFaceValue(face, offlineClipDragStartValue + signedDistance);
}

function endOfflineClipFaceDrag() {
  offlineClipDragFace = null;
  activeOfflineClipFace.value = null;
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
  const littleEndian = message?.is_bigendian !== true;

  for (let index = 0; index < totalPoints; index += sampleStep) {
    const base = index * pointStep;
    if (base + pointStep > bytes.byteLength) {
      break;
    }

    const x = view.getFloat32(base + xOffset, littleEndian);
    const y = view.getFloat32(base + yOffset, littleEndian);
    const z = view.getFloat32(base + zOffset, littleEndian);
    if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(z)) {
      continue;
    }
    positions.push(x, y, z);
  }
  return positions;
}

function describePointCloud2ForWarning(message: any) {
  const fields = Array.isArray(message?.fields)
    ? message.fields
        .map(
          (field: { name?: string; offset?: number }) =>
            `${String(field?.name ?? "?")}:${String(field?.offset ?? "?")}`,
        )
        .join(",")
    : "none";
  const bytes = normalizePointCloudBytes(message?.data);
  const dataLength = bytes?.byteLength ?? 0;
  return `fields=${fields || "none"}, point_step=${String(message?.point_step ?? "?")}, width=${String(message?.width ?? "?")}, height=${String(message?.height ?? "?")}, data=${dataLength}B`;
}

function renderPointCloud(
  display: NavViewerDisplay,
  message: any,
): PointCloudRenderResult {
  if (!scene) {
    return { ok: false, message: "3D 场景未初始化，暂不能渲染点云。" };
  }
  const latestDisplay = getDisplayByTopic(display.topic) || display;
  const topic = latestDisplay.topic;
  const isCustomPointCloud = Array.isArray(message?.points);
  const positions = Array.isArray(message?.points)
    ? extractCustomPointCloudPositions(message)
    : extractPointCloud2Positions(message);
  if (positions.length === 0) {
    const detail = isCustomPointCloud
      ? `points=${Array.isArray(message?.points) ? message.points.length : 0}`
      : describePointCloud2ForWarning(message);
    return {
      ok: false,
      message: `点云 ${topic} 已收到但没有可渲染 xyz 数据，${detail}`,
      warningSignature: `${topic}:${detail}`,
    };
  }
  platformState.lidarAt = Date.now();
  const useLayeredColors =
    pointColorModeForDisplay(latestDisplay) === "layered";
  const emissiveIntensity = safePointCloudEmissiveIntensity(latestDisplay);
  const pointColors = useLayeredColors
    ? buildPointCloudColorBuffer(
        positions,
        pointColorForDisplay(latestDisplay),
        emissiveIntensity,
      )
    : null;

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
      color: useLayeredColors
        ? amplifiedPointColor("#ffffff", emissiveIntensity)
        : amplifiedPointColor(
            pointColorForDisplay(latestDisplay),
            emissiveIntensity,
          ),
      size: safePointCloudSize(latestDisplay),
      sizeAttenuation: true,
      vertexColors: useLayeredColors,
      transparent: true,
      opacity: emissiveIntensity > 0 ? 0.98 : 0.96,
      depthWrite: emissiveIntensity <= 0,
      depthTest: true,
      blending:
        emissiveIntensity > 0 ? THREE.AdditiveBlending : THREE.NormalBlending,
      toneMapped: emissiveIntensity <= 0,
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
      existingAttribute &&
      existingAttribute instanceof THREE.BufferAttribute &&
      existingAttribute.itemSize === 3 &&
      existingAttribute.array.length === positions.length
    ) {
      (existingAttribute.array as Float32Array).set(positions);
      existingAttribute.needsUpdate = true;

      geometry.setDrawRange(0, nextPointCount);
    } else {
      const nextAttribute = new THREE.Float32BufferAttribute(positions, 3);
      nextAttribute.setUsage(THREE.DynamicDrawUsage);
      geometry.setAttribute("position", nextAttribute);
      geometry.setDrawRange(0, nextPointCount);
    }
    if (pointColors) {
      if (
        existingColorAttribute &&
        existingColorAttribute instanceof THREE.BufferAttribute &&
        existingColorAttribute.itemSize === 3 &&
        existingColorAttribute.array.length === pointColors.length
      ) {
        (existingColorAttribute.array as Float32Array).set(pointColors);
        existingColorAttribute.needsUpdate = true;
      } else {
        geometry.setAttribute(
          "color",
          new THREE.BufferAttribute(pointColors, 3),
        );
      }
    } else {
      if (existingColorAttribute) {
        geometry.deleteAttribute("color");
      }
    }
    geometry.computeBoundingSphere();
    const material = points.material as THREE.PointsMaterial;
    if (material && !Array.isArray(material)) {
      applyPointCloudMaterialConfig(material, latestDisplay, useLayeredColors);
    }
  }
  sourceFrameByTopic.set(topic, normalizeFrameId(message?.header?.frame_id));
  sourceStampMsByTopic.set(topic, extractHeaderStampMs(message));
  cacheTopicLocalMatrix(topic, composeLocalMatrix());
  applyObjectFrameTransform(
    topic,
    points,
    message?.header?.frame_id,
    sourceStampMsByTopic.get(topic) ?? null,
  );
  points.visible = true;
  pointCloudWarningSignatureByTopic.delete(topic);
  return { ok: true, message: `已更新点云: ${topic}` };
}

function candidateQuaternionFromYaw(yaw: number) {
  return new THREE.Quaternion().setFromEuler(new THREE.Euler(0, 0, yaw, "XYZ"));
}

function candidateQuaternionFromGroundNormal(
  yaw: number,
  normal: THREE.Vector3 | null,
) {
  if (!normal || normal.lengthSq() < 1e-8) {
    return candidateQuaternionFromYaw(yaw);
  }
  const zAxis = normal.clone().normalize();
  if (zAxis.z < 0) {
    zAxis.multiplyScalar(-1);
  }
  const horizontalForward = new THREE.Vector3(Math.cos(yaw), Math.sin(yaw), 0);
  const projectedForward = horizontalForward.sub(
    zAxis.clone().multiplyScalar(horizontalForward.dot(zAxis)),
  );
  if (projectedForward.lengthSq() < 1e-8) {
    return candidateQuaternionFromYaw(yaw);
  }
  const xAxis = projectedForward.normalize();
  const yAxis = zAxis.clone().cross(xAxis).normalize();
  const matrix = new THREE.Matrix4().makeBasis(xAxis, yAxis, zAxis);
  return new THREE.Quaternion().setFromRotationMatrix(matrix);
}

function createInitialPoseArrowObject() {
  const group = new THREE.Group();
  group.name = "initial-pose-candidate-visual";

  const anchor = new THREE.Mesh(
    new THREE.CircleGeometry(0.16, 28),
    new THREE.MeshBasicMaterial({
      color: "#31d28a",
      transparent: true,
      opacity: 0.92,
    }),
  );
  anchor.name = "initial-pose-anchor";
  anchor.position.set(0, 0, 0.025);
  group.add(anchor);

  const arrow = new THREE.ArrowHelper(
    new THREE.Vector3(1, 0, 0),
    new THREE.Vector3(0, 0, 0.08),
    1.25,
    "#31d28a",
    0.32,
    0.15,
  );
  arrow.name = "initial-pose-arrow";
  group.add(arrow);

  const zAxis = new THREE.ArrowHelper(
    new THREE.Vector3(0, 0, 1),
    new THREE.Vector3(0, 0, 0.08),
    0.58,
    "#61ecff",
    0.16,
    0.08,
  );
  zAxis.name = "initial-pose-z-axis";
  group.add(zAxis);

  return group;
}

function applyInitialPoseCandidateTransform(
  group: THREE.Group,
  x: number,
  y: number,
  z: number,
  yaw: number,
  normal: THREE.Vector3 | null = null,
) {
  group.position.set(x, y, z);
  group.quaternion.copy(candidateQuaternionFromGroundNormal(yaw, normal));
  group.updateMatrixWorld(true);
}

function ensureInitialPoseCandidateGroup(
  x: number,
  y: number,
  z: number,
  yaw: number,
  normal: THREE.Vector3 | null = null,
) {
  if (!scene) {
    return null;
  }
  if (!initialPoseCandidateGroup) {
    initialPoseCandidateGroup = new THREE.Group();
    initialPoseCandidateGroup.name = "initial-pose-candidate-root";
    initialPoseCandidateGroup.add(createInitialPoseArrowObject());
    scene.add(initialPoseCandidateGroup);
  }
  applyInitialPoseCandidateTransform(
    initialPoseCandidateGroup,
    x,
    y,
    z,
    yaw,
    normal,
  );
  transformControls?.attach(initialPoseCandidateGroup, props.taskEditing);
  if (transformControlsHelper) {
    transformControlsHelper.visible = true;
  }
  return initialPoseCandidateGroup;
}

function clearInitialPoseCandidate() {
  transformControls?.detach();
  if (transformControlsHelper) {
    transformControlsHelper.visible = false;
  }
  if (initialPoseCandidateGroup) {
    clearThreeObject(initialPoseCandidateGroup);
    initialPoseCandidateGroup = null;
  }
  initialPosePointCloud = null;
}

/**
 * 功能说明：
 * 将抓取到的一帧点云转换到 base_link 局部坐标，后续由初始化候选位姿统一控制位置和姿态。
 *
 * 注意事项：
 * 1. TF 齐全时使用 fixed frame 作为中间坐标，避免把当前全局位姿直接烘焙到点云里。
 * 2. TF 不齐全时保留原始点坐标继续预览，现场可据提示判断是否需要补 TF 或改选局部点云话题。
 */
function localizePointCloudPositionsToBase(message: any, positions: number[]) {
  const cloudFrame = normalizeFrameId(message?.header?.frame_id);
  const stampMs = extractHeaderStampMs(message);
  const cloudToFixed = resolveFrameTransformToFixed(cloudFrame, stampMs);
  const baseToFixed = resolveFrameTransformToFixed("base_link", stampMs);
  if (!cloudToFixed || !baseToFixed) {
    return {
      positions,
      localized: false,
      message: cloudFrame
        ? `缺少 ${cloudFrame} 或 base_link 到 ${currentFixedFrame()} 的 TF，已按原始点云局部坐标预览。`
        : "点云缺少 frame_id，已按原始点云局部坐标预览。",
    };
  }

  const cloudToBase = baseToFixed.clone().invert().multiply(cloudToFixed);
  const nextPositions = [...positions];
  transformPositionArrayInPlace(nextPositions, cloudToBase);
  return {
    positions: nextPositions,
    localized: true,
    message: `点云已从 ${cloudFrame || "未知坐标系"} 转成 base_link 局部快照。`,
  };
}

/**
 * 功能说明：
 * 把外层页面抓取的一帧点云绑定到初始化候选位姿上。
 *
 * 用法说明：
 * 1. 必须先通过拖拽生成候选位姿，否则没有可绑定的三维操作中心。
 * 2. 重复抓帧会释放上一帧点云资源，只保留最新一帧，避免浏览器端缓存累积。
 */
function attachInitialPosePointCloud(payload: InitialPosePointCloudPayload) {
  if (!initialPoseCandidateGroup) {
    return { ok: false, message: "请先拖出初始化候选位姿，再抓取点云帧。" };
  }
  const display: NavViewerDisplay = {
    topic: payload.topic || "initial-pose-preview-cloud",
    messageType: "sensor_msgs/msg/PointCloud2",
    kind: "pointcloud",
    label: "初始化点云预览",
    pointSize: payload.pointSize ?? 0.06,
    pointColorMode: payload.pointColorMode ?? "layered",
    color: payload.color ?? "#f4d35e",
  };
  const rawPositions = Array.isArray(payload.message?.points)
    ? extractCustomPointCloudPositions(payload.message)
    : extractPointCloud2Positions(payload.message);
  if (rawPositions.length === 0) {
    return { ok: false, message: "点云帧没有解析到有效 x/y/z 点。" };
  }

  const localized = localizePointCloudPositionsToBase(
    payload.message,
    rawPositions,
  );
  const useLayeredColors = pointColorModeForDisplay(display) === "layered";
  const pointColors = useLayeredColors
    ? buildPointCloudColorBuffer(
        localized.positions,
        pointColorForDisplay(display),
      )
    : null;

  if (initialPosePointCloud) {
    clearThreeObject(initialPosePointCloud);
    initialPosePointCloud = null;
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute(
    "position",
    new THREE.Float32BufferAttribute(localized.positions, 3),
  );
  if (pointColors) {
    geometry.setAttribute("color", new THREE.BufferAttribute(pointColors, 3));
  }
  geometry.computeBoundingSphere();
  const material = new THREE.PointsMaterial({
    color: useLayeredColors ? "#ffffff" : pointColorForDisplay(display),
    size: safePointCloudSize(display),
    sizeAttenuation: true,
    vertexColors: useLayeredColors,
    transparent: true,
    opacity: 0.78,
    depthWrite: false,
    depthTest: true,
  });
  initialPosePointCloud = new THREE.Points(geometry, material);
  initialPosePointCloud.name = "initial-pose-pointcloud-preview";
  initialPoseCandidateGroup.add(initialPosePointCloud);
  initialPoseCandidateGroup.updateMatrixWorld(true);
  sceneStatus.value = `已绑定初始化点云: ${payload.topic}，${Math.floor(localized.positions.length / 3)} 点。${localized.message}`;
  return { ok: true, message: sceneStatus.value };
}

function updateInitialPosePointCloudSize(pointSize: number) {
  if (!initialPosePointCloud) {
    return { ok: false, message: "当前还没有初始化点云预览。" };
  }
  const safeSize = Math.min(0.8, Math.max(0.005, Number(pointSize) || 0.055));
  const material = initialPosePointCloud.material as THREE.PointsMaterial;
  if (Array.isArray(material)) {
    return { ok: false, message: "初始化点云材质格式不支持直接调整点大小。" };
  }
  material.size = safeSize;
  material.needsUpdate = true;
  sceneStatus.value = `初始化点云点大小已调整为 ${safeSize.toFixed(3)}。`;
  return { ok: true, message: sceneStatus.value };
}

function getInitialPoseCandidate() {
  if (!initialPoseCandidateGroup) {
    return null;
  }
  const euler = new THREE.Euler().setFromQuaternion(
    initialPoseCandidateGroup.quaternion,
    "XYZ",
  );
  return {
    x: initialPoseCandidateGroup.position.x,
    y: initialPoseCandidateGroup.position.y,
    z: initialPoseCandidateGroup.position.z,
    roll: euler.x,
    pitch: euler.y,
    yaw: euler.z,
  };
}

function clearInteractionPreview() {
  if (interactionPreviewGroup) {
    clearThreeObject(interactionPreviewGroup);
    interactionPreviewGroup = null;
  }
}

function buildInteractionPreview(
  startPoint: THREE.Vector3,
  endPoint: THREE.Vector3,
) {
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
    new THREE.MeshBasicMaterial({
      color:
        currentInteractionMode.value === "initialpose" ? "#31d28a" : "#f6a237",
    }),
  );
  anchor.position.set(startPoint.x, startPoint.y, startPoint.z + 0.02);
  group.add(anchor);

  const arrow = new THREE.ArrowHelper(
    new THREE.Vector3(Math.cos(yaw), Math.sin(yaw), 0),
    new THREE.Vector3(startPoint.x, startPoint.y, startPoint.z + 0.05),
    length,
    currentInteractionMode.value === "initialpose" ? "#31d28a" : "#f6a237",
    0.26,
    0.14,
  );
  group.add(arrow);

  scene.add(group);
  interactionPreviewGroup = group;
}

function worldPointFromMouse(event: MouseEvent, planeZ = 0) {
  if (!camera || !renderer) {
    return null;
  }
  const rect = renderer.domElement.getBoundingClientRect();
  const x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
  const y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
  raycaster.setFromCamera(new THREE.Vector2(x, y), camera);
  const point = new THREE.Vector3();
  const plane =
    planeZ === 0
      ? interactionPlane
      : new THREE.Plane(new THREE.Vector3(0, 0, 1), -planeZ);
  const hit = raycaster.ray.intersectPlane(plane, point);
  return hit ? point.clone() : null;
}

function rayPayloadFromMouse(event: MouseEvent) {
  if (!camera || !renderer) {
    return null;
  }
  const rect = renderer.domElement.getBoundingClientRect();
  const x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
  const y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
  raycaster.setFromCamera(new THREE.Vector2(x, y), camera);
  return {
    origin: [
      raycaster.ray.origin.x,
      raycaster.ray.origin.y,
      raycaster.ray.origin.z,
    ],
    direction: [
      raycaster.ray.direction.x,
      raycaster.ray.direction.y,
      raycaster.ray.direction.z,
    ],
  };
}

function safeInitialPoseBaseHeightOffset() {
  const value = Number(props.initialPoseBaseHeightOffsetM ?? 0.35);
  return Number.isFinite(value) ? Math.min(3, Math.max(-1, value)) : 0.35;
}

function currentOfflineMapClipBoundsPayload() {
  if (!offlineMapClipBounds) {
    return undefined;
  }
  return cloneBounds(offlineMapClipBounds);
}

async function resolveInitialPoseStartPoint(event: MouseEvent) {
  const fallback = worldPointFromMouse(event, 0);
  interactionStartGroundNormal = null;
  interactionStartGroundMessage = "";
  if (!hasOfflineMapRaycastCache()) {
    return fallback;
  }
  const ray = rayPayloadFromMouse(event);
  if (!ray) {
    return fallback;
  }
  try {
    const result = await raycastRosNavOfflineMap({
      origin: ray.origin,
      direction: ray.direction,
      max_distance_m: 80,
      normal_radius_m: Number(props.initialPoseGroundNormalRadiusM ?? 0.8),
      ground_max_slope_deg: Number(props.initialPoseGroundMaxSlopeDeg ?? 30),
      clip_bounds: currentOfflineMapClipBoundsPayload() as unknown as
        Record<string, number> | undefined,
      use_visible_voxels: true,
    });
    if (
      !result.hit ||
      !Number.isFinite(result.x) ||
      !Number.isFinite(result.y) ||
      !Number.isFinite(result.z)
    ) {
      interactionStartGroundMessage =
        result.message || "射线未命中可靠地面，已回退到平面初始化。";
      return fallback;
    }
    const normal =
      Array.isArray(result.normal) && result.normal.length >= 3
        ? new THREE.Vector3(
            Number(result.normal[0]),
            Number(result.normal[1]),
            Number(result.normal[2]),
          ).normalize()
        : new THREE.Vector3(0, 0, 1);
    interactionStartGroundNormal = normal;
    interactionStartGroundMessage =
      result.message || "已通过离线点云占据射线吸附地面。";
    return new THREE.Vector3(
      Number(result.x),
      Number(result.y),
      Number(result.z) + safeInitialPoseBaseHeightOffset(),
    );
  } catch (error) {
    interactionStartGroundMessage = `离线点云射线吸附失败: ${(error as Error).message}`;
    return fallback;
  }
}

// 离线射线请求可能晚于鼠标松开返回，保留终点并用序号丢弃过期结果。
let taskPickSerial = 0;
let pendingRouteClick: {
  insertion: TaskRouteInsertion;
  x: number;
  y: number;
  mode: string;
  moved: boolean;
} | null = null;
/** 以屏幕像素判定路线命中，避免缩放后世界坐标拾取范围过宽。 */
function pickTaskRoute(event: MouseEvent): TaskRouteInsertion | null {
  if (!props.taskEditing || !camera || !renderer) return null;
  const points = props.taskPoints || [];
  const rect = renderer.domElement.getBoundingClientRect();
  rayPayloadFromMouse(event);
  let best = 8;
  let result: TaskRouteInsertion | null = null;
  for (let i = 0; i < points.length - 1; i++) {
    const a = points[i],
      b = points[i + 1];
    const start = new THREE.Vector3(a.x, a.y, a.z + 0.04);
    const end = new THREE.Vector3(b.x, b.y, b.z + 0.04);
    if (start.distanceToSquared(end) < 1e-10) continue;
    const hit = new THREE.Vector3();
    raycaster.ray.distanceSqToSegment(start, end, undefined, hit);
    const projected = hit.clone().project(camera);
    if (projected.z < -1 || projected.z > 1) continue;
    const distance = Math.hypot(
      rect.left + ((projected.x + 1) * rect.width) / 2 - event.clientX,
      rect.top + ((1 - projected.y) * rect.height) / 2 - event.clientY,
    );
    const t = hit.distanceTo(start) / start.distanceTo(end);
    if (distance >= best || t <= 0.001 || t >= 0.999) continue;
    best = distance;
    result = {
      beforeId: a.id,
      afterId: b.id,
      pose: {
        x: hit.x,
        y: hit.y,
        z: a.z + (b.z - a.z) * t,
        roll: 0,
        pitch: 0,
        yaw: routeInsertionYaw(
          a,
          {
            x: hit.x,
            y: hit.y,
            z: hit.z,
            yaw: Math.atan2(b.y - a.y, b.x - a.x),
          },
          b,
        ),
      },
    };
  }
  return result;
}
let pendingTaskPick: {
  serial: number;
  released: boolean;
  end: MouseEvent;
} | null = null;
async function handlePointerDown(event: MouseEvent) {
  if (!(event instanceof PointerEvent) && performance.now() - lastTouchAt < 800)
    return;
  pendingRouteClick = null;
  if (
    event.button !== 0 ||
    transformControls?.dragging ||
    transformControls?.axis
  )
    return;
  if (["none", "waypoint"].includes(currentInteractionMode.value)) {
    if (taskRouteGroup) {
      const hit = pickTaskMarker(event);
      if (hit) {
        // 选中已有点优先于空白打点，并废弃尚未返回的地面查询。
        taskPickSerial++;
        pendingTaskPick = null;
        finishInteraction(false);
        if (controls) controls.enabled = true;
        emit("taskPointSelect", hit.object.userData.taskPoint);
        return;
      }
    }
    const insertion = pickTaskRoute(event);
    if (insertion) {
      taskPickSerial++;
      pendingTaskPick = null;
      finishInteraction(false);
      pendingRouteClick = {
        insertion,
        x: event.clientX,
        y: event.clientY,
        mode: currentInteractionMode.value,
        moved: false,
      };
      return;
    }
    if (currentInteractionMode.value === "none") return;
  }
  const startedMode = currentInteractionMode.value;
  const request =
    startedMode === "waypoint"
      ? { serial: ++taskPickSerial, released: false, end: event }
      : null;
  if (request) {
    pendingTaskPick = request;
    if (controls) controls.enabled = false;
  }
  const point =
    currentInteractionMode.value === "initialpose" ||
    currentInteractionMode.value === "waypoint"
      ? await resolveInitialPoseStartPoint(event)
      : worldPointFromMouse(event);
  if (
    currentInteractionMode.value !== startedMode ||
    (request && request.serial !== taskPickSerial)
  ) {
    return;
  }
  if (!point) {
    if (request) {
      pendingTaskPick = null;
      if (controls) controls.enabled = true;
    }
    return;
  }
  interactionStartPoint = point;
  interactionCurrentPoint = point.clone();
  controls && (controls.enabled = false);
  buildInteractionPreview(interactionStartPoint, interactionCurrentPoint);
  if (request) {
    pendingTaskPick = null;
    interactionCurrentPoint =
      worldPointFromMouse(request.end, point.z) || point.clone();
    if (request.released) finishInteraction(true);
  }
  event.preventDefault();
}

function handlePointerMove(event: MouseEvent) {
  if (
    pendingRouteClick &&
    Math.hypot(
      event.clientX - pendingRouteClick.x,
      event.clientY - pendingRouteClick.y,
    ) > 5
  )
    pendingRouteClick.moved = true;
  if (pendingTaskPick) pendingTaskPick.end = event;
  if (!interactionStartPoint || currentInteractionMode.value === "none") {
    return;
  }
  const point = worldPointFromMouse(event, interactionStartPoint.z);
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
  const targetZ = interactionStartPoint.z;
  const groundNormal =
    mode === "initialpose" || mode === "waypoint"
      ? (interactionStartGroundNormal?.clone() ?? null)
      : null;
  const candidateQuaternion = candidateQuaternionFromGroundNormal(
    yaw,
    groundNormal,
  );
  const candidateEuler = new THREE.Euler().setFromQuaternion(
    candidateQuaternion,
    "XYZ",
  );
  const groundMessage = interactionStartGroundMessage;
  clearInteractionPreview();
  interactionStartPoint = null;
  interactionCurrentPoint = null;
  interactionStartGroundNormal = null;
  interactionStartGroundMessage = "";
  controls && (controls.enabled = true);

  if (!emitResult || mode === "none") {
    return;
  }
  if (mode === "initialpose") {
    ensureInitialPoseCandidateGroup(
      targetX,
      targetY,
      targetZ,
      yaw,
      groundNormal,
    );
    sceneStatus.value = `已生成初始化候选位姿，可抓取点云并用三维控件微调。${groundMessage ? ` ${groundMessage}` : ""}`;
  }
  if (mode === "waypoint") {
    const pose = {
      x: targetX,
      y: targetY,
      z: targetZ,
      roll: candidateEuler.x,
      pitch: candidateEuler.y,
      yaw: candidateEuler.z,
    };
    editTaskPose(pose);
    emit("taskPosePlaced", pose);
    return;
  }
  emit("interactionComplete", {
    mode,
    x: targetX,
    y: targetY,
    z: targetZ,
    roll: candidateEuler.x,
    pitch: candidateEuler.y,
    yaw: candidateEuler.z,
  });
}

function handlePointerUp(event: MouseEvent) {
  if (!(event instanceof PointerEvent) && performance.now() - lastTouchAt < 800)
    return;
  if (pendingRouteClick) {
    const click = pendingRouteClick;
    pendingRouteClick = null;
    if (
      event.button === 0 &&
      !click.moved &&
      click.mode === currentInteractionMode.value &&
      Math.hypot(event.clientX - click.x, event.clientY - click.y) <= 5 &&
      !transformControls?.dragging
    )
      emit("taskRouteInsert", click.insertion);
    return;
  }
  if (event.button === 0 && pendingTaskPick) {
    pendingTaskPick.released = true;
    pendingTaskPick.end = event;
  }
  if (event.button !== 0) {
    return;
  }
  finishInteraction(true);
}

function handlePointerLeave() {
  pendingRouteClick = null;
  if (pendingTaskPick) pendingTaskPick.released = true;
  if (!interactionStartPoint) {
    return;
  }
  finishInteraction(true);
}

let lastTouchAt = -Infinity;
const sceneTouchPointers = new Set<number>();
let sceneTouchTap: { start: PointerEvent; moved: boolean } | null = null;
/** 触屏轻点选点，拖动与双指手势留给相机；方向通过选中点的旋转控件调整。 */
function sceneTouchDown(event: PointerEvent) {
  if (!["touch", "pen"].includes(event.pointerType)) return;
  lastTouchAt = performance.now();
  sceneTouchPointers.add(event.pointerId);
  sceneTouchTap =
    sceneTouchPointers.size === 1 ? { start: event, moved: false } : null;
}
function sceneTouchMove(event: PointerEvent) {
  if (!["touch", "pen"].includes(event.pointerType)) return;
  lastTouchAt = performance.now();
  if (
    sceneTouchTap &&
    Math.hypot(
      event.clientX - sceneTouchTap.start.clientX,
      event.clientY - sceneTouchTap.start.clientY,
    ) > 6
  )
    sceneTouchTap.moved = true;
}
function sceneTouchUp(event: PointerEvent) {
  if (!["touch", "pen"].includes(event.pointerType)) return;
  lastTouchAt = performance.now();
  sceneTouchPointers.delete(event.pointerId);
  const tap = sceneTouchTap;
  sceneTouchTap = null;
  if (
    event.type === "pointercancel" ||
    !tap ||
    tap.moved ||
    sceneTouchPointers.size ||
    tap.start.pointerId !== event.pointerId
  )
    return;
  void handlePointerDown(tap.start).then(() => handlePointerUp(event));
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

function quaternionFromPoseOrientation(orientation: any) {
  const quaternion = new THREE.Quaternion(
    Number(orientation?.x ?? 0),
    Number(orientation?.y ?? 0),
    Number(orientation?.z ?? 0),
    Number(orientation?.w ?? 1),
  );
  if (quaternion.lengthSq() < 1e-8) {
    return new THREE.Quaternion();
  }
  return quaternion.normalize();
}

function vectorFromPosePosition(position: any) {
  return new THREE.Vector3(
    Number(position?.x ?? 0),
    Number(position?.y ?? 0),
    Number(position?.z ?? 0),
  );
}

function formatHudCoordinate(value: number) {
  return Number.isFinite(value) ? value.toFixed(3) : "-";
}

function updateBaseLinkHud() {
  if (connectionLabel.value !== "已连接") {
    baseLinkHudText.value = "等待 rosbridge 连接";
    return;
  }

  const robotTf = resolveRobotTfPose();
  const baseLinkTransform = robotTf?.matrix;
  if (baseLinkTransform) {
    const position = new THREE.Vector3();
    const quaternion = new THREE.Quaternion();
    const scale = new THREE.Vector3();
    baseLinkTransform.decompose(position, quaternion, scale);
    baseLinkHudText.value = [
      "来源: TF",
      `frame: ${currentFixedFrame()} <- ${robotTf!.frame}`,
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

  baseLinkHudText.value = `${robotPoseTfTopic} 中 ${currentRobotPoseFrame()} 位姿暂不可用`;
}

function createCircleLine(radius: number, color: string, dashed = false) {
  const points: THREE.Vector3[] = [];
  const segments = 96;
  for (let index = 0; index <= segments; index += 1) {
    const angle = (index / segments) * Math.PI * 2;
    points.push(
      new THREE.Vector3(
        Math.cos(angle) * radius,
        Math.sin(angle) * radius,
        0.03,
      ),
    );
  }
  const geometry = new THREE.BufferGeometry().setFromPoints(points);
  const material = dashed
    ? new THREE.LineDashedMaterial({
        color,
        dashSize: 0.22,
        gapSize: 0.12,
        transparent: true,
        opacity: 0.9,
      })
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
    new THREE.LineBasicMaterial({
      color: "#8ea1ba",
      transparent: true,
      opacity: 0.88,
    }),
  );
}

function obstacleStateFromMessage(message: any): ObstacleZoneState {
  const rawValue =
    typeof message?.data === "number"
      ? message.data
      : typeof message?.data === "string"
        ? Number(message.data)
        : typeof message?.state === "number"
          ? message.state
          : Number.NaN;
  const code = Number.isFinite(rawValue)
    ? Math.max(0, Math.min(2, Math.round(rawValue)))
    : 0;
  if (code === 2) {
    return { code, label: "danger_zone" };
  }
  if (code === 1) {
    return { code, label: "calm_zone" };
  }
  return { code: 0, label: "clear" };
}

function resolvePrimaryPoseAnchor() {
  const poseDisplays = props.displays.filter(
    (display) => display.kind === "pose",
  );
  if (poseDisplays.length === 0) {
    return null;
  }
  const preferredDisplay = poseDisplays
    .slice()
    .sort((left, right) => {
      const leftScore = left.topic.includes("ndt_pose")
        ? 0
        : left.topic.includes("pose")
          ? 1
          : 2;
      const rightScore = right.topic.includes("ndt_pose")
        ? 0
        : right.topic.includes("pose")
          ? 1
          : 2;
      if (leftScore !== rightScore) {
        return leftScore - rightScore;
      }
      return left.topic.localeCompare(right.topic, "zh-CN");
    })
    .find((display) => poseAnchorByTopic.has(display.topic));
  return preferredDisplay
    ? (poseAnchorByTopic.get(preferredDisplay.topic) ?? null)
    : null;
}

function resolveNdtPoseAnchor() {
  const preferredTopic = props.displays
    .filter(
      (display) =>
        display.kind === "pose" && display.topic.includes("ndt_pose"),
    )
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
    return {
      ok: false,
      message: `缺少 ${anchor.frameId} 到 ${currentFixedFrame()} 的 TF，无法聚焦定位位姿。`,
    };
  }

  const target = new THREE.Vector3(anchor.x, anchor.y, anchor.z);
  target.applyMatrix4(transformMatrix);

  const currentOffset = camera.position.clone().sub(controls.target);
  const currentDistance = currentOffset.length();
  const desiredDistance = Number.isFinite(currentDistance)
    ? Math.max(2, currentDistance)
    : 8;
  const currentHorizontalRadius = currentOffset.clone().setZ(0).length();
  const fallbackHorizontalRadius = Math.min(
    desiredDistance * 0.42,
    Math.max(0.9, desiredDistance * 0.22),
  );
  const horizontalRadius = Math.min(
    Math.max(currentHorizontalRadius, fallbackHorizontalRadius),
    Math.max(0.9, desiredDistance * 0.92),
  );
  const verticalDistance = Math.sqrt(
    Math.max(
      0.36,
      desiredDistance * desiredDistance - horizontalRadius * horizontalRadius,
    ),
  );

  const frameRotation = new THREE.Quaternion();
  const framePosition = new THREE.Vector3();
  const frameScale = new THREE.Vector3();
  transformMatrix.decompose(framePosition, frameRotation, frameScale);
  const poseRotation = new THREE.Quaternion().setFromAxisAngle(
    new THREE.Vector3(0, 0, 1),
    anchor.yaw,
  );
  const worldPoseRotation = frameRotation.clone().multiply(poseRotation);
  const poseForward = new THREE.Vector3(1, 0, 0)
    .applyQuaternion(worldPoseRotation)
    .setZ(0);
  const horizontalDirection =
    poseForward.lengthSq() > 1e-6
      ? poseForward.normalize().multiplyScalar(-horizontalRadius)
      : new THREE.Vector3(-horizontalRadius, 0, 0);
  const nextOffset = new THREE.Vector3(
    horizontalDirection.x,
    horizontalDirection.y,
    Math.max(0.6, verticalDistance),
  );

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
    return {
      ok: false,
      message: "当前还没有收到 /ndt_pose 的有效位姿，暂时无法定位镜头。",
    };
  }
  return focusCameraOnAnchor(anchor);
}

function applyObstacleZoneStyle(group: THREE.Group, state: ObstacleZoneState) {
  const detectionRing = group.getObjectByName("detection-ring") as THREE.Line<
    THREE.BufferGeometry,
    THREE.LineBasicMaterial
  > | null;
  const calmRing = group.getObjectByName("calm-ring") as THREE.Line<
    THREE.BufferGeometry,
    THREE.LineBasicMaterial
  > | null;
  const dangerRing = group.getObjectByName("danger-ring") as THREE.Line<
    THREE.BufferGeometry,
    THREE.LineBasicMaterial
  > | null;
  const calmFill = group.getObjectByName("calm-fill") as THREE.Mesh | null;
  const dangerFill = group.getObjectByName("danger-fill") as THREE.Mesh | null;

  const calmActive = state.code === 1;
  const dangerActive = state.code === 2;

  (detectionRing?.material as THREE.MeshBasicMaterial | undefined)?.setValues?.(
    {
      opacity: dangerActive ? 0.98 : calmActive ? 0.92 : 0.72,
    },
  );
  (calmRing?.material as THREE.MeshBasicMaterial | undefined)?.setValues?.({
    color: calmActive ? "#ffe178" : "#e4c45d",
    opacity: calmActive ? 1 : 0.76,
  });
  (dangerRing?.material as THREE.MeshBasicMaterial | undefined)?.setValues?.({
    color: dangerActive ? "#ff5f76" : "#df6b84",
    opacity: dangerActive ? 1 : 0.78,
  });
  (calmFill?.material as THREE.MeshBasicMaterial | undefined)?.setValues?.({
    opacity: calmActive ? 0.2 : 0.1,
    color: calmActive ? "#ffe178" : "#f1cf6a",
  });
  (dangerFill?.material as THREE.MeshBasicMaterial | undefined)?.setValues?.({
    opacity: dangerActive ? 0.26 : 0.1,
    color: dangerActive ? "#ff5f76" : "#ff7f94",
  });
}

function buildObstacleZoneGroup(state: ObstacleZoneState) {
  const group = new THREE.Group();

  const detectionRing = createCircleLine(
    OBSTACLE_ZONE_DEFAULTS.detectionRange,
    "#5c88bc",
    true,
  );
  detectionRing.name = "detection-ring";
  group.add(detectionRing);

  const calmFill = new THREE.Mesh(
    new THREE.CircleGeometry(OBSTACLE_ZONE_DEFAULTS.calmRadius, 72),
    new THREE.MeshBasicMaterial({
      color: "#f1cf6a",
      transparent: true,
      opacity: 0.1,
      side: THREE.DoubleSide,
      depthWrite: false,
    }),
  );
  calmFill.name = "calm-fill";
  calmFill.position.z = 0.015;
  group.add(calmFill);

  const calmRing = createCircleLine(
    OBSTACLE_ZONE_DEFAULTS.calmRadius,
    "#e4c45d",
  );
  calmRing.name = "calm-ring";
  group.add(calmRing);

  const dangerFill = new THREE.Mesh(
    new THREE.CircleGeometry(OBSTACLE_ZONE_DEFAULTS.dangerRadius, 72),
    new THREE.MeshBasicMaterial({
      color: "#ff7f94",
      transparent: true,
      opacity: 0.1,
      side: THREE.DoubleSide,
      depthWrite: false,
    }),
  );
  dangerFill.name = "danger-fill";
  dangerFill.position.z = 0.02;
  group.add(dangerFill);

  const dangerRing = createCircleLine(
    OBSTACLE_ZONE_DEFAULTS.dangerRadius,
    "#df6b84",
  );
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
  const posePosition = vectorFromPosePosition(position);
  const poseQuaternion = quaternionFromPoseOrientation(orientation);
  const frameId =
    normalizeFrameId(message?.header?.frame_id) || currentFixedFrame();
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
    body.position.set(0.34, 0, 0);
  }
  const tail = marker?.getObjectByName("pose-tail") as THREE.Mesh | null;
  if (tail) {
    tail.position.set(0, 0, 0);
  }

  sourceFrameByTopic.set(topic, frameId);
  sourceStampMsByTopic.set(topic, extractHeaderStampMs(message));
  cacheTopicLocalMatrix(
    topic,
    composeLocalMatrix(posePosition, poseQuaternion),
  );
  applyObjectFrameTransform(
    topic,
    group,
    frameId,
    sourceStampMsByTopic.get(topic) ?? null,
  );
  group.visible = true;
  poseAnchorByTopic.set(topic, {
    topic,
    frameId,
    x: posePosition.x,
    y: posePosition.y,
    z: posePosition.z,
    yaw,
  });
  refreshAllObstacleZones();
  updateBaseLinkHud();
}

function createPoseMarker(color: string, scale: number) {
  const marker = new THREE.Group();
  const body = new THREE.Mesh(
    new THREE.ConeGeometry(0.22 * scale, 0.68 * scale, 18),
    new THREE.MeshStandardMaterial({ color }),
  );
  body.name = "pose-body";
  body.rotation.z = -Math.PI / 2;
  body.position.set(0.34 * scale, 0, 0);
  marker.add(body);

  const tail = new THREE.Mesh(
    new THREE.CircleGeometry(0.12 * scale, 16),
    new THREE.MeshBasicMaterial({ color }),
  );
  tail.name = "pose-tail";
  tail.position.set(0, 0, 0);
  marker.add(tail);
  return marker;
}

function renderPoseArray(topic: string, message: any) {
  if (!scene) {
    return;
  }
  const poses = Array.isArray(message?.poses) ? message.poses : [];
  const frameId =
    normalizeFrameId(message?.header?.frame_id) || currentFixedFrame();
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
    const posePosition = vectorFromPosePosition(position);
    const poseQuaternion = quaternionFromPoseOrientation(orientation);
    const marker = group!.children[index] as THREE.Group;
    marker.visible = true;
    marker.position.copy(posePosition);
    marker.quaternion.copy(poseQuaternion);
    const body = marker.getObjectByName("pose-body") as THREE.Mesh | null;
    if (body) {
      body.position.set(0.25, 0, 0);
    }
    const tail = marker.getObjectByName("pose-tail") as THREE.Mesh | null;
    if (tail) {
      tail.position.set(0, 0, 0);
    }
  });

  sourceFrameByTopic.set(topic, frameId);
  sourceStampMsByTopic.set(topic, extractHeaderStampMs(message));
  cacheTopicLocalMatrix(topic, composeLocalMatrix());
  applyObjectFrameTransform(
    topic,
    group,
    frameId,
    sourceStampMsByTopic.get(topic) ?? null,
  );
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

function ensureTfFrameNode(
  topic: string,
  frameName: string,
  display: NavViewerDisplay | null,
) {
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
    new THREE.MeshBasicMaterial({ color: "#8ea1ba" }),
  );
  point.name = "tf-point";
  frameNode.add(point);

  if (display?.tfShowNames !== false) {
    const label = buildTfLabelSprite(
      frameName,
      safeTfLabelSize(display ?? undefined),
    );
    if (label) {
      label.name = "tf-label";
      frameNode.add(label);
    }
  }

  frameNodeMap.set(frameName, frameNode);
  return frameNode;
}

function updateTfFrameNode(
  frameNode: THREE.Group,
  frameName: string,
  position: THREE.Vector3,
  quaternion: THREE.Quaternion,
  display: NavViewerDisplay | null,
) {
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
    label = buildTfLabelSprite(
      frameName,
      safeTfLabelSize(display ?? (undefined as never)),
    );
    if (label) {
      label.name = "tf-label";
      frameNode.add(label);
    }
  }
  if (label) {
    label.visible = showNames;
    label.position.set(position.x, position.y, position.z + 0.22);
    const sizeScale = safeTfLabelSize(display ?? (undefined as never));
    const texture = (label.material as THREE.SpriteMaterial | undefined)?.map;
    const width =
      (texture?.image as { width?: number } | undefined)?.width ?? 80;
    const height =
      (texture?.image as { height?: number } | undefined)?.height ?? 40;
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
  // 机器人当前选用的坐标系不能被历史 TF 筛选配置遮蔽，否则 HUD 可解析位姿但三维轴不显示。
  if (
    !showAllFrames &&
    normalizeTfTopicKey(topic) === normalizeTfTopicKey(robotPoseTfTopic)
  ) {
    visibleFrames.add(currentRobotPoseFrame());
  }
  let group = tfGroupByTopic.get(topic);
  if (!group) {
    group = new THREE.Group();
    scene.add(group);
    tfGroupByTopic.set(topic, group);
  }
  const frameNodeMap =
    tfFrameNodeCacheByTopic.get(topic) ?? new Map<string, THREE.Group>();
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
    const transformMatrix = resolveFrameTransformToFixed(
      frameName,
      null,
      topic,
    );
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
  geometry.setAttribute(
    "position",
    new THREE.Float32BufferAttribute(positions, 3),
  );
  const material = new THREE.PointsMaterial({
    color: "#ffdd57",
    size: 0.05,
    sizeAttenuation: true,
  });
  const points = new THREE.Points(geometry, material);
  sourceFrameByTopic.set(topic, normalizeFrameId(message?.header?.frame_id));
  sourceStampMsByTopic.set(topic, extractHeaderStampMs(message));
  cacheTopicLocalMatrix(topic, composeLocalMatrix());
  applyObjectFrameTransform(
    topic,
    points,
    message?.header?.frame_id,
    sourceStampMsByTopic.get(topic) ?? null,
  );
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

function buildMarkerLine(
  points: any[],
  color: THREE.Color,
  opacity: number,
  closed = false,
  lineWidth = 0.05,
) {
  const positions = points.flatMap((point: any) => [
    Number(point?.x ?? 0),
    Number(point?.y ?? 0),
    Number(point?.z ?? 0),
  ]);
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute(
    "position",
    new THREE.Float32BufferAttribute(positions, 3),
  );
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

function buildMarkerSphereList(
  points: any[],
  scale: any,
  colors: any[],
  fallbackColor: THREE.Color,
  fallbackOpacity: number,
) {
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
    mesh.position.set(
      Number(point?.x ?? 0),
      Number(point?.y ?? 0),
      Number(point?.z ?? 0),
    );
    group.add(mesh);
  });
  return group;
}

function buildMarkerArrow(message: any, color: THREE.Color, opacity: number) {
  const group = new THREE.Group();
  const points = Array.isArray(message?.points) ? message.points : [];
  const start =
    points.length >= 1
      ? new THREE.Vector3(
          Number(points[0]?.x ?? 0),
          Number(points[0]?.y ?? 0),
          Number(points[0]?.z ?? 0),
        )
      : new THREE.Vector3();
  const end =
    points.length >= 2
      ? new THREE.Vector3(
          Number(points[1]?.x ?? 0),
          Number(points[1]?.y ?? 0),
          Number(points[1]?.z ?? 0),
        )
      : new THREE.Vector3(0.4, 0, 0);
  const direction = end.clone().sub(start);
  const length = Math.max(0.05, direction.length());
  const normalized =
    direction.lengthSq() > 1e-8
      ? direction.normalize()
      : new THREE.Vector3(1, 0, 0);
  const arrow = new THREE.ArrowHelper(
    normalized,
    start,
    length,
    color,
    Math.max(0.08, Number(message?.scale?.z ?? 0.18)),
    Math.max(0.04, Number(message?.scale?.y ?? 0.12)),
  );
  arrow.name = "marker-arrow";
  (arrow.line.material as THREE.Material).transparent = opacity < 1;
  (arrow.line.material as THREE.Material).opacity = opacity;
  (arrow.cone.material as THREE.Material).transparent = opacity < 1;
  (arrow.cone.material as THREE.Material).opacity = opacity;
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
      new THREE.SphereGeometry(
        Math.max(0.01, Number(message?.scale?.x ?? 0.15) / 2),
        18,
        14,
      ),
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
      Math.max(
        0.01,
        Number(message?.scale?.y ?? Number(message?.scale?.x ?? 0.2)) / 2,
      ),
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
    return buildMarkerLine(
      points,
      fallback.color,
      fallback.opacity,
      false,
      Number(message?.scale?.x ?? 0.05),
    );
  }
  if (type === 5 && points.length >= 2) {
    return buildMarkerLine(
      points,
      fallback.color,
      fallback.opacity,
      false,
      Number(message?.scale?.x ?? 0.05),
    );
  }
  if (type === 7 && points.length >= 1) {
    return buildMarkerSphereList(
      points,
      message?.scale,
      Array.isArray(message?.colors) ? message.colors : [],
      fallback.color,
      fallback.opacity,
    );
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
  const entryMap = group?.userData?.markerEntries as
    Map<string, THREE.Object3D> | undefined;
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
  sourceFrameByTopic.set(
    topic,
    normalizeFrameId(message?.header?.frame_id) || currentFixedFrame(),
  );
  sourceStampMsByTopic.set(topic, extractHeaderStampMs(message));
  cacheTopicLocalMatrix(topic, composeLocalMatrix());
  applyObjectFrameTransform(
    topic,
    group,
    sourceFrameByTopic.get(topic),
    sourceStampMsByTopic.get(topic) ?? null,
  );
  group.visible = true;

  const lifetimeMs = markerLifetimeMs(message);
  const shouldAutoRemove = lifetimeMs > 0 && lifetimeMs >= 800;
  if (shouldAutoRemove) {
    window.setTimeout(() => {
      const latestGroup = markerObjectByTopic.get(topic) as
        THREE.Group | undefined;
      const latestEntryMap = latestGroup?.userData?.markerEntries as
        Map<string, THREE.Object3D> | undefined;
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

  const arrow = group.getObjectByName(
    "twist-arrow",
  ) as THREE.ArrowHelper | null;
  if (arrow) {
    const direction =
      speed > 1e-6
        ? speedVector.clone().normalize()
        : new THREE.Vector3(1, 0, 0);
    arrow.setDirection(direction);
    arrow.setLength(Math.max(0.18, speed), 0.18, 0.1);
    arrow.setColor(new THREE.Color(twistColorForDisplay(display)));
  }
  group.position.set(anchor.x, anchor.y, Math.max(anchor.z + 0.18, 0.18));
  group.quaternion.setFromAxisAngle(new THREE.Vector3(0, 0, 1), anchor.yaw);
  sourceFrameByTopic.set(topic, anchor.frameId);
  sourceStampMsByTopic.set(topic, extractHeaderStampMs(message));
  cacheTopicLocalMatrix(
    topic,
    composeLocalMatrix(group.position.clone(), group.quaternion.clone()),
  );
  applyObjectFrameTransform(
    topic,
    group,
    anchor.frameId,
    sourceStampMsByTopic.get(topic) ?? null,
  );
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
  cacheTopicLocalMatrix(
    topic,
    composeLocalMatrix(
      zoneGroup.position.clone(),
      zoneGroup.quaternion.clone(),
    ),
  );
  applyObjectFrameTransform(topic, zoneGroup, anchor.frameId, null);
  zoneGroup.visible = true;
  sceneStatus.value = `已更新风险区: ${topic} (${state.label})`;
}

function ingestTfMessage(topic: string, message: any) {
  const transforms = Array.isArray(message?.transforms)
    ? message.transforms
    : [];
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
      matrixToParent: buildTransformMatrix(
        item?.transform?.translation,
        item?.transform?.rotation,
      ),
      stampMs: isStaticTopic ? null : extractHeaderStampMs(item),
      // ROS 时钟可与浏览器系统时钟不同步；缓存淘汰只能依据本地实际接收时刻。
      receivedAtMs: currentTimeMs,
      staticTransform: isStaticTopic,
    };
    const history = topicHistoryMap.get(childFrame) ?? [];
    const nextHistory = [
      ...history.filter((sample) => sample.staticTransform !== isStaticTopic),
      nextSample,
    ]
      .filter(
        (sample) =>
          sample.staticTransform ||
          currentTimeMs - sample.receivedAtMs <= maxTfHistoryAgeMs,
      )
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
  supportTfTopics.forEach((topic) => {
    if (supportTfUnsubscribeMap.has(topic) || unsubscribeMap.has(topic)) {
      return;
    }
    const unsubscribe = rosAdapter!.subscribe(
      topic,
      "tf2_msgs/msg/TFMessage",
      (message) => {
        ingestTfMessage(topic, message);
        updateTopicTransforms();
        props.displays.forEach((display) => {
          if (display.kind === "tf") {
            renderTf(display.topic);
          }
        });
      },
    );
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

  const unsubscribe = rosAdapter!.subscribe(
    display.topic,
    display.messageType,
    (message) => {
      const latestDisplay = getDisplayByTopic(display.topic) || display;
      if (!shouldConsumeDisplayMessage(latestDisplay)) {
        return;
      }
      latestMessageByTopic.set(latestDisplay.topic, message);
      renderDisplayMessage(latestDisplay, message);
    },
    subscriptionOptionsForDisplay(display),
  );

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
    const result = renderPointCloud(display, message);
    sceneStatus.value = result.message;
    if (!result.ok && result.warningSignature) {
      const previousSignature = pointCloudWarningSignatureByTopic.get(
        display.topic,
      );
      if (previousSignature !== result.warningSignature) {
        pointCloudWarningSignatureByTopic.set(
          display.topic,
          result.warningSignature,
        );
        emit("rosLog", {
          source: "3DViewer",
          level: "warning",
          message: result.message,
        });
      }
    }
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
    sharedKey: `ros-nav-test:${props.provider}:${props.url}:${props.timeoutMs}`,
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
    .forEach((display) =>
      emit("tfFramesChange", { topic: display.topic, frames: [] }),
    );

  rosAdapter?.disconnect();
  rosAdapter = createSharedRosLiveAdapter({
    ...buildSharedRosConfig(),
    adapterName: "三维主视图",
    onStatusChange: (snapshot) => {
      connectionLabel.value = snapshot.connected
        ? "已连接"
        : snapshot.reconnecting
          ? "重连中"
          : "未连接";
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
        `${event.scope}: ${event.message}${event.detail ? ` (${event.detail})` : ""}`,
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
  () => scheduleReconnectAndResubscribe(),
);

watch(
  () => props.robotPoseFrame,
  () => updateBaseLinkHud(),
);

watch(
  () => props.reconnectToken,
  () => scheduleReconnectAndResubscribe(),
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
    const previousTopics = new Set(
      (previousDisplays ?? []).map((item) => item.topic),
    );

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
  { deep: true },
);

watch(
  () => currentInteractionMode.value,
  () => {
    taskPickSerial++;
    pendingTaskPick = null;
    if (controls) controls.enabled = true;
    finishInteraction(false);
  },
);

watch(
  () => platformState.cameraReset,
  () => {
    if (!camera || !controls) return;
    if (platformState.demo) {
      camera.position.set(-8.2, -8.2, 9);
      controls.target.set(0, 0, 0.25);
    } else {
      focusOnNdtPose();
    }
    controls.update();
  },
);
watch(
  () => props.url,
  (url) => {
    if (!url) {
      hasConnected = false;
      lastRobotPose = null;
      arena?.reset();
      platformState.pose = "等待位姿数据";
    }
  },
);

// 任务覆盖层与 ROS 显示对象独立，切换侧栏不重建场景或连接。
let taskRouteGroup: THREE.Group | null = null;
/** 编号优先于坐标轴拾取，和最终绘制层级保持一致。 */
function pickTaskMarker(event: MouseEvent) {
  if (!props.taskEditing || !taskRouteGroup || !renderer || !camera)
    return null;
  updateTaskMarkerScales();
  taskRouteGroup.updateMatrixWorld(true);
  rayPayloadFromMouse(event);
  return (
    raycaster.intersectObjects(
      taskRouteGroup.children.filter((item) => item.userData.taskPoint),
      false,
    )[0] || null
  );
}
/** 图标世界尺寸缓慢增长，屏幕高度封顶；锚点固定在点位，不随缩放漂移。 */
function updateTaskMarkerScales() {
  if (!camera || !renderer || !taskRouteGroup) return;
  const height = Math.max(1, renderer.domElement.clientHeight);
  taskRouteGroup.children.forEach((object) => {
    if (!(object instanceof THREE.Sprite)) return;
    const distance = camera!.position.distanceTo(object.position);
    const depth = -object.position
      .clone()
      .applyMatrix4(camera!.matrixWorldInverse).z;
    const unitsPerPixel =
      (2 *
        Math.max(0.01, depth) *
        Math.tan(THREE.MathUtils.degToRad(camera!.fov / 2))) /
      height;
    const worldHeight = Math.min(
      0.76 * poseVisualScale(distance),
      56 * unitsPerPixel,
    );
    object.scale.set((worldHeight * 96) / 112, worldHeight, 1);
  });
}
/** 复制当前可解析的真实位姿，断开连接时拒绝使用缓存或演示坐标。 */
function getTaskRobotPose(): TaskPose | null {
  if (connectionLabel.value !== "已连接") return null;
  const matrix = resolveRobotTfPose()?.matrix;
  if (matrix) {
    const position = new THREE.Vector3(),
      rotation = new THREE.Quaternion();
    matrix.decompose(position, rotation, new THREE.Vector3());
    const angles = new THREE.Euler().setFromQuaternion(rotation, "XYZ");
    return {
      x: position.x,
      y: position.y,
      z: position.z,
      yaw: angles.z,
      roll: angles.x,
      pitch: angles.y,
    };
  }
  const anchor = resolvePrimaryPoseAnchor();
  if (!anchor) return null;
  const poseObject = poseObjectByTopic.get(anchor.topic);
  if (!poseObject) return null;
  const angles = new THREE.Euler().setFromQuaternion(
    poseObject.getWorldQuaternion(new THREE.Quaternion()),
    "XYZ",
  );
  return {
    x: anchor.x,
    y: anchor.y,
    z: anchor.z,
    roll: angles.x,
    pitch: angles.y,
    yaw: angles.z,
  };
}
/** 复用初始化的变换控件，但任务候选永远不进入定位发布链路。 */
function editTaskPose(pose: TaskPose) {
  const group = ensureInitialPoseCandidateGroup(
    pose.x,
    pose.y,
    pose.z,
    pose.yaw,
  );
  group?.quaternion.setFromEuler(
    new THREE.Euler(pose.roll ?? 0, pose.pitch ?? 0, pose.yaw, "XYZ"),
  );
  group?.updateMatrixWorld(true);
}
function focusTaskPose(pose: TaskPose) {
  if (!camera || !controls) return;
  const target = new THREE.Vector3(pose.x, pose.y, pose.z);
  camera.position.add(target.clone().sub(controls.target));
  controls.target.copy(target);
  controls.update();
}
/** 编号和虚线表示任务顺序；朝向箭头使用 ROS Z-up 坐标。 */
function rebuildTaskRoute() {
  if (taskRouteGroup) clearThreeObject(taskRouteGroup);
  taskRouteGroup = null;
  if (!scene || !props.taskPoints?.length) return;
  const group = new THREE.Group();
  const points = props.taskPoints;
  points.forEach((point, index) => {
    const color =
      index === 0
        ? "#76b933"
        : index === points.length - 1
          ? "#ef5368"
          : "#2895ef";
    const canvas = document.createElement("canvas");
    canvas.width = 96;
    canvas.height = 112;
    const context = canvas.getContext("2d")!;
    context.fillStyle = color;
    context.beginPath();
    context.arc(48, 45, 36, 0, Math.PI * 2);
    context.fill();
    context.beginPath();
    context.moveTo(32, 73);
    context.lineTo(48, 108);
    context.lineTo(64, 73);
    context.fill();
    context.strokeStyle = "white";
    context.lineWidth = 3;
    context.beginPath();
    context.arc(48, 45, 36, 0, Math.PI * 2);
    context.stroke();
    context.fillStyle = "white";
    context.font = "bold 40px sans-serif";
    context.textAlign = "center";
    context.textBaseline = "middle";
    context.fillText(String(index + 1), 48, 46);
    const marker = new THREE.Sprite(
      new THREE.SpriteMaterial({
        map: new THREE.CanvasTexture(canvas),
        depthTest: false,
        depthWrite: false,
      }),
    );
    marker.position.set(point.x, point.y, point.z + 0.06);
    marker.center.set(0.5, 0);
    marker.scale.set(0.65, 0.76, 1);
    marker.renderOrder = 1000;
    marker.userData.taskPoint = point;
    group.add(marker);
    group.add(
      new THREE.ArrowHelper(
        new THREE.Vector3(1, 0, 0).applyEuler(
          new THREE.Euler(point.roll ?? 0, point.pitch ?? 0, point.yaw, "XYZ"),
        ),
        new THREE.Vector3(point.x, point.y, point.z + 0.05),
        0.7,
        color,
        0.2,
        0.12,
      ),
    );
  });
  if (points.length > 1) {
    const line = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints(
        points.map(
          (point) => new THREE.Vector3(point.x, point.y, point.z + 0.04),
        ),
      ),
      new THREE.LineDashedMaterial({
        color: "#2895ef",
        dashSize: 0.3,
        gapSize: 0.18,
      }),
    );
    line.computeLineDistances();
    group.add(line);
  }
  scene.add(group);
  taskRouteGroup = group;
}
watch(() => props.taskPoints, rebuildTaskRoute, { deep: true });

defineExpose<NavViewerExpose>({
  getTaskRobotPose,
  editTaskPose,
  focusTaskPose,
  focusOnNdtPose,
  attachOfflineMapPointCloud,
  clearOfflineMapPointCloud,
  setOfflineMapDisplayMode,
  updateOfflineMapVisualSettings,
  attachInitialPosePointCloud,
  updateInitialPosePointCloudSize,
  getInitialPoseCandidate,
  clearInitialPoseCandidate,
});

onMounted(async () => {
  initializeScene();
  rebuildTaskRoute();
  resizeObserver = new ResizeObserver(() => fitRendererSize());
  if (mountRef.value) {
    resizeObserver.observe(mountRef.value);
  }
  renderer?.domElement.addEventListener("mousedown", handlePointerDown);
  renderer?.domElement.addEventListener("pointerdown", sceneTouchDown);
  renderer?.domElement.addEventListener("pointermove", sceneTouchMove);
  renderer?.domElement.addEventListener("pointerup", sceneTouchUp);
  renderer?.domElement.addEventListener("pointercancel", sceneTouchUp);
  renderer?.domElement.addEventListener("mousemove", handlePointerMove);
  renderer?.domElement.addEventListener("mouseup", handlePointerUp);
  renderer?.domElement.addEventListener("mouseleave", handlePointerLeave);
  scheduleReconnectAndResubscribe();
});

onBeforeUnmount(() => {
  window.cancelAnimationFrame(animationFrame);
  if (reconnectTimer) {
    window.clearTimeout(reconnectTimer);
    reconnectTimer = undefined;
  }
  resizeObserver?.disconnect();
  renderer?.domElement.removeEventListener("mousedown", handlePointerDown);
  renderer?.domElement.removeEventListener("pointerdown", sceneTouchDown);
  renderer?.domElement.removeEventListener("pointermove", sceneTouchMove);
  renderer?.domElement.removeEventListener("pointerup", sceneTouchUp);
  renderer?.domElement.removeEventListener("pointercancel", sceneTouchUp);
  renderer?.domElement.removeEventListener("mousemove", handlePointerMove);
  renderer?.domElement.removeEventListener("mouseup", handlePointerUp);
  renderer?.domElement.removeEventListener("mouseleave", handlePointerLeave);
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
      <span
        class="status-pill"
        :class="{ success: connectionLabel === '已连接' }"
        >{{ connectionLabel }}</span
      >
      <span class="nav-viewer-meta">Fixed Frame: {{ fixedFrame }}</span>
      <span class="nav-viewer-meta">显示项: {{ hudDisplayCount }}</span>
    </div>

    <div class="nav-viewer-stage">
      <div ref="mountRef" class="nav-viewer-canvas-host"></div>
      <div
        class="nav-offline-clip-widget"
        :class="{ disabled: !offlineClipPanelVisible }"
      >
        <div class="nav-offline-clip-head">
          <span class="nav-offline-clip-title">坐标裁剪</span>
          <span class="nav-offline-clip-hint">拖动轴向裁剪点云</span>
        </div>
        <div
          class="nav-offline-display-toggle"
          role="group"
          aria-label="离线地图显示模式"
        >
          <button
            type="button"
            :class="{ active: offlineMapDisplayMode === 'voxel' }"
            :disabled="!offlineClipActive"
            title="显示占据 voxel 方块"
            @click="setOfflineMapDisplayMode('voxel')"
          >
            占据网格
          </button>
          <button
            type="button"
            :class="{ active: offlineMapDisplayMode === 'pointcloud' }"
            :disabled="!offlineClipActive"
            title="显示下采样点云"
            @click="setOfflineMapDisplayMode('pointcloud')"
          >
            点云
          </button>
          <button
            type="button"
            :class="{ active: offlineMapDisplayMode === 'render' }"
            :disabled="!offlineClipActive"
            title="使用暮光材质和阴影渲染占据 voxel"
            @click="setOfflineMapDisplayMode('render')"
          >
            渲染
          </button>
        </div>
        <div
          class="nav-offline-clip-axis-control"
          :class="
            activeOfflineClipFace
              ? `dragging dragging-${clipAxisForFace(activeOfflineClipFace)}`
              : ''
          "
          aria-label="离线点云六向裁剪"
        >
          <!-- 纯视觉几何层：同心辅助圆与轴向细杆，不承载任何交互 -->
          <svg
            class="clip-axis-geometry"
            viewBox="0 0 170 160"
            aria-hidden="true"
          >
            <circle class="geo-ring" cx="85" cy="80" r="30"></circle>
            <circle class="geo-ring faint" cx="85" cy="80" r="44"></circle>
            <line class="geo-rod rod-x" x1="98" y1="80" x2="128" y2="80"></line>
            <line class="geo-rod rod-x" x1="72" y1="80" x2="42" y2="80"></line>
            <line class="geo-rod rod-z" x1="85" y1="67" x2="85" y2="37"></line>
            <line class="geo-rod rod-z" x1="85" y1="93" x2="85" y2="123"></line>
            <line
              class="geo-rod rod-y"
              x1="94.2"
              y1="69.8"
              x2="116.8"
              y2="47.2"
            ></line>
            <line
              class="geo-rod rod-y"
              x1="75.8"
              y1="90.2"
              x2="53.2"
              y2="112.8"
            ></line>
          </svg>
          <span class="clip-axis-hub" aria-hidden="true"></span>
          <button
            type="button"
            class="clip-axis-arrow axis-x axis-xmin"
            :class="{ active: activeOfflineClipFace === 'xmin' }"
            title="左边界 X−：拖动或 ←→ 键调整"
            @pointerdown.stop.prevent="beginOfflineClipFaceDrag('xmin', $event)"
            @pointermove.stop.prevent="dragOfflineClipFace"
            @pointerup.stop.prevent="endOfflineClipFaceDrag"
            @pointercancel.stop.prevent="endOfflineClipFaceDrag"
            @keydown="handleOfflineClipFaceKeydown('xmin', $event)"
            @mouseenter="setHoveredOfflineClipFace('xmin')"
            @mouseleave="setHoveredOfflineClipFace(null)"
          ></button>
          <button
            type="button"
            class="clip-axis-arrow axis-x axis-xmax"
            :class="{ active: activeOfflineClipFace === 'xmax' }"
            title="右边界 X+：拖动或 ←→ 键调整"
            @pointerdown.stop.prevent="beginOfflineClipFaceDrag('xmax', $event)"
            @pointermove.stop.prevent="dragOfflineClipFace"
            @pointerup.stop.prevent="endOfflineClipFaceDrag"
            @pointercancel.stop.prevent="endOfflineClipFaceDrag"
            @keydown="handleOfflineClipFaceKeydown('xmax', $event)"
            @mouseenter="setHoveredOfflineClipFace('xmax')"
            @mouseleave="setHoveredOfflineClipFace(null)"
          ></button>
          <button
            type="button"
            class="clip-axis-arrow axis-y axis-ymin"
            :class="{ active: activeOfflineClipFace === 'ymin' }"
            title="后边界 Y−：拖动或 ←→ 键调整"
            @pointerdown.stop.prevent="beginOfflineClipFaceDrag('ymin', $event)"
            @pointermove.stop.prevent="dragOfflineClipFace"
            @pointerup.stop.prevent="endOfflineClipFaceDrag"
            @pointercancel.stop.prevent="endOfflineClipFaceDrag"
            @keydown="handleOfflineClipFaceKeydown('ymin', $event)"
            @mouseenter="setHoveredOfflineClipFace('ymin')"
            @mouseleave="setHoveredOfflineClipFace(null)"
          ></button>
          <button
            type="button"
            class="clip-axis-arrow axis-y axis-ymax"
            :class="{ active: activeOfflineClipFace === 'ymax' }"
            title="前边界 Y+：拖动或 ←→ 键调整"
            @pointerdown.stop.prevent="beginOfflineClipFaceDrag('ymax', $event)"
            @pointermove.stop.prevent="dragOfflineClipFace"
            @pointerup.stop.prevent="endOfflineClipFaceDrag"
            @pointercancel.stop.prevent="endOfflineClipFaceDrag"
            @keydown="handleOfflineClipFaceKeydown('ymax', $event)"
            @mouseenter="setHoveredOfflineClipFace('ymax')"
            @mouseleave="setHoveredOfflineClipFace(null)"
          ></button>
          <button
            type="button"
            class="clip-axis-arrow axis-z axis-zmin"
            :class="{ active: activeOfflineClipFace === 'zmin' }"
            title="底面边界 Z−：拖动或 ↑↓ 键调整"
            @pointerdown.stop.prevent="beginOfflineClipFaceDrag('zmin', $event)"
            @pointermove.stop.prevent="dragOfflineClipFace"
            @pointerup.stop.prevent="endOfflineClipFaceDrag"
            @pointercancel.stop.prevent="endOfflineClipFaceDrag"
            @keydown="handleOfflineClipFaceKeydown('zmin', $event)"
            @mouseenter="setHoveredOfflineClipFace('zmin')"
            @mouseleave="setHoveredOfflineClipFace(null)"
          ></button>
          <button
            type="button"
            class="clip-axis-arrow axis-z axis-zmax"
            :class="{ active: activeOfflineClipFace === 'zmax' }"
            title="顶面边界 Z+：拖动或 ↑↓ 键调整"
            @pointerdown.stop.prevent="beginOfflineClipFaceDrag('zmax', $event)"
            @pointermove.stop.prevent="dragOfflineClipFace"
            @pointerup.stop.prevent="endOfflineClipFaceDrag"
            @pointercancel.stop.prevent="endOfflineClipFaceDrag"
            @keydown="handleOfflineClipFaceKeydown('zmax', $event)"
            @mouseenter="setHoveredOfflineClipFace('zmax')"
            @mouseleave="setHoveredOfflineClipFace(null)"
          ></button>
        </div>
        <div v-if="offlineClipBoundsView" class="nav-offline-clip-readout">
          <div
            class="clip-axis-readout"
            :class="{ active: highlightedOfflineClipAxis === 'x' }"
          >
            <span class="clip-axis-tag axis-x">X</span>
            <span class="clip-axis-values"
              >{{ offlineClipBoundsView.xmin.toFixed(2) }} →
              {{ offlineClipBoundsView.xmax.toFixed(2) }} m</span
            >
          </div>
          <div
            class="clip-axis-readout"
            :class="{ active: highlightedOfflineClipAxis === 'y' }"
          >
            <span class="clip-axis-tag axis-y">Y</span>
            <span class="clip-axis-values"
              >{{ offlineClipBoundsView.ymin.toFixed(2) }} →
              {{ offlineClipBoundsView.ymax.toFixed(2) }} m</span
            >
          </div>
          <div
            class="clip-axis-readout"
            :class="{ active: highlightedOfflineClipAxis === 'z' }"
          >
            <span class="clip-axis-tag axis-z">Z</span>
            <span class="clip-axis-values"
              >{{ offlineClipBoundsView.zmin.toFixed(2) }} →
              {{ offlineClipBoundsView.zmax.toFixed(2) }} m</span
            >
          </div>
        </div>
        <button
          class="nav-offline-clip-reset"
          type="button"
          :disabled="!offlineClipActive"
          @click="resetOfflineClipBounds"
        >
          ↻ 重置裁剪
        </button>
      </div>
      <div class="nav-viewer-base-link-hud" :class="`tone-${baseLinkHudTone}`">
        <span class="nav-viewer-base-link-title">机器狗位置</span>
        <span class="nav-viewer-base-link-text">{{ baseLinkHudText }}</span>
      </div>
    </div>

    <div class="nav-viewer-footer">
      <span class="nav-viewer-status">{{ sceneStatus }}</span>
      <span
        v-if="connectionLabel !== '已连接' || hudDisplayCount === 0"
        class="nav-viewer-status"
      >
        {{ emptyStateText }}
      </span>
      <span v-if="interactionHintText" class="nav-viewer-status accent">{{
        interactionHintText
      }}</span>
    </div>
  </div>
</template>
