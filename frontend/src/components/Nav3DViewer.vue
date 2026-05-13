<!-- 功能说明：导航测试页三维主视图，负责把 ROS 常用话题渲染到统一 3D 窗口。 -->
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

import type { NavViewerDisplay } from "../lib/ros/displayRegistry";
import { createRosLiveAdapter } from "../lib/ros/liveAdapter";

const props = defineProps<{
  provider: string;
  url: string;
  timeoutMs: number;
  fixedFrame: string;
  displays: NavViewerDisplay[];
  interactionMode?: "none" | "initialpose" | "navgoal";
}>();

const emit = defineEmits<{
  interactionComplete: [payload: { mode: "initialpose" | "navgoal"; x: number; y: number; yaw: number }];
  tfFramesChange: [payload: { topic: string; frames: string[] }];
}>();

const mountRef = ref<HTMLDivElement | null>(null);
const connectionLabel = ref("未连接");
const sceneStatus = ref("等待显示项");

let renderer: THREE.WebGLRenderer | null = null;
let scene: THREE.Scene | null = null;
let camera: THREE.PerspectiveCamera | null = null;
let controls: OrbitControls | null = null;
let animationFrame = 0;
let rosAdapter: ReturnType<typeof createRosLiveAdapter> | null = null;
let resizeObserver: ResizeObserver | null = null;
let lastViewportWidth = 0;
let lastViewportHeight = 0;
let interactionStartPoint: THREE.Vector3 | null = null;
let interactionCurrentPoint: THREE.Vector3 | null = null;
let interactionPreviewGroup: THREE.Group | null = null;

const unsubscribeMap = new Map<string, () => void>();
const supportTfUnsubscribeMap = new Map<string, () => void>();
const mapMeshByTopic = new Map<string, THREE.Object3D>();
const mapTextureByTopic = new Map<string, THREE.CanvasTexture>();
const pathLineByTopic = new Map<string, THREE.Line>();
const tfGroupByTopic = new Map<string, THREE.Group>();
const poseObjectByTopic = new Map<string, THREE.Object3D>();
const pointCloudByTopic = new Map<string, THREE.Points>();
const laserByTopic = new Map<string, THREE.Points>();
const lastMessageTimeByTopic = new Map<string, number>();
const latestMessageByTopic = new Map<string, any>();
const sourceFrameByTopic = new Map<string, string>();
const baseLocalMatrixByTopic = new Map<string, THREE.Matrix4>();
const tfTransformByChildFrame = new Map<string, { parentFrame: string; matrixToParent: THREE.Matrix4 }>();
const tfFrameSignatureByTopic = new Map<string, string>();
const raycaster = new THREE.Raycaster();
const interactionPlane = new THREE.Plane(new THREE.Vector3(0, 0, 1), 0);

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

function animate() {
  if (!renderer || !scene || !camera) {
    return;
  }
  animationFrame = window.requestAnimationFrame(animate);
  controls?.update();
  renderer.render(scene, camera);
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
      material.forEach((item) => item.dispose());
    } else {
      material?.dispose?.();
    }
  });
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

  const poseObject = poseObjectByTopic.get(topic);
  if (poseObject) {
    clearThreeObject(poseObject);
    poseObjectByTopic.delete(topic);
  }

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

  lastMessageTimeByTopic.delete(topic);
  latestMessageByTopic.delete(topic);
  sourceFrameByTopic.delete(topic);
  baseLocalMatrixByTopic.delete(topic);
  tfFrameSignatureByTopic.delete(topic);
}

function clearAllTopicVisuals() {
  [
    ...mapMeshByTopic.keys(),
    ...pathLineByTopic.keys(),
    ...tfGroupByTopic.keys(),
    ...poseObjectByTopic.keys(),
    ...pointCloudByTopic.keys(),
    ...laserByTopic.keys(),
  ].forEach((topic) => disposeTopic(topic));
}

function getDisplayByTopic(topic: string) {
  return props.displays.find((display) => display.topic === topic) || null;
}

function normalizeFrameId(frameId: unknown) {
  return String(frameId ?? "").trim().replace(/^\/+/, "");
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

function resolveFrameTransformToFixed(frameId: unknown, trail = new Set<string>()): THREE.Matrix4 | null {
  const sourceFrame = normalizeFrameId(frameId);
  const fixedFrame = currentFixedFrame();
  if (!sourceFrame || sourceFrame === fixedFrame) {
    return new THREE.Matrix4().identity();
  }
  if (trail.has(sourceFrame)) {
    return null;
  }
  const link = tfTransformByChildFrame.get(sourceFrame);
  if (!link) {
    return null;
  }
  trail.add(sourceFrame);
  const parentMatrix = resolveFrameTransformToFixed(link.parentFrame, trail);
  trail.delete(sourceFrame);
  if (!parentMatrix) {
    return null;
  }
  return parentMatrix.clone().multiply(link.matrixToParent);
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

function cacheTopicLocalTransform(topic: string, object: THREE.Object3D) {
  object.updateMatrix();
  baseLocalMatrixByTopic.set(topic, object.matrix.clone());
}

function applyObjectFrameTransform(topic: string, object: THREE.Object3D, frameId: unknown) {
  const transformMatrix = resolveFrameTransformToFixed(frameId);
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
  mapMeshByTopic.forEach((object, topic) => applyObjectFrameTransform(topic, object, sourceFrameByTopic.get(topic)));
  pathLineByTopic.forEach((object, topic) => applyObjectFrameTransform(topic, object, sourceFrameByTopic.get(topic)));
  poseObjectByTopic.forEach((object, topic) => applyObjectFrameTransform(topic, object, sourceFrameByTopic.get(topic)));
  pointCloudByTopic.forEach((object, topic) => applyObjectFrameTransform(topic, object, sourceFrameByTopic.get(topic)));
  laserByTopic.forEach((object, topic) => applyObjectFrameTransform(topic, object, sourceFrameByTopic.get(topic)));
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
    material.size = safePointCloudSize(display);
    material.color = new THREE.Color(pointColorForDisplay(display));
    material.needsUpdate = true;
  });
}

function emitTfFrames(topic: string) {
  const frames = Array.from(tfTransformByChildFrame.keys()).sort((left, right) => left.localeCompare(right, "zh-CN"));
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

function renderOccupancyGrid(topic: string, message: any) {
  if (!scene) {
    return;
  }

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
    opacity: 0.94,
    side: THREE.DoubleSide,
  });
  const plane = new THREE.Mesh(geometry, material);
  plane.position.set((width * resolution) / 2, (height * resolution) / 2, -0.02);

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
  cacheTopicLocalTransform(topic, root);
  applyObjectFrameTransform(topic, root, message?.header?.frame_id);

  scene.add(root);
  mapMeshByTopic.set(topic, root);
  mapTextureByTopic.set(topic, texture);
}

function renderPath(topic: string, message: any) {
  if (!scene) {
    return;
  }
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

  const oldLine = pathLineByTopic.get(topic);
  if (oldLine) {
    clearThreeObject(oldLine);
  }

  const geometry = new THREE.BufferGeometry().setFromPoints(points);
  const material = new THREE.LineBasicMaterial({ color: "#f6a237", linewidth: 2 });
  const line = new THREE.Line(geometry, material);
  sourceFrameByTopic.set(topic, normalizeFrameId(message?.header?.frame_id));
  cacheTopicLocalTransform(topic, line);
  applyObjectFrameTransform(topic, line, message?.header?.frame_id);
  scene.add(line);
  pathLineByTopic.set(topic, line);
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

function renderPointCloud(display: NavViewerDisplay, message: any) {
  if (!scene) {
    return;
  }
  const latestDisplay = getDisplayByTopic(display.topic) || display;
  const topic = latestDisplay.topic;

  const fields = Array.isArray(message?.fields) ? message.fields : [];
  const pointStep = Number(message?.point_step ?? 0);
  const width = Number(message?.width ?? 0);
  const height = Number(message?.height ?? 1);
  const bytes = normalizePointCloudBytes(message?.data);
  if (pointStep <= 0 || width <= 0 || !bytes || bytes.byteLength < pointStep) {
    return;
  }

  const xOffset = resolveFieldOffset(fields, "x");
  const yOffset = resolveFieldOffset(fields, "y");
  const zOffset = resolveFieldOffset(fields, "z");
  if (xOffset < 0 || yOffset < 0 || zOffset < 0) {
    return;
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
  const oldCloud = pointCloudByTopic.get(topic);
  if (oldCloud) {
    clearThreeObject(oldCloud);
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  const material = new THREE.PointsMaterial({
    color: pointColorForDisplay(latestDisplay),
    size: safePointCloudSize(latestDisplay),
    sizeAttenuation: true,
  });
  const points = new THREE.Points(geometry, material);
  sourceFrameByTopic.set(topic, normalizeFrameId(message?.header?.frame_id));
  cacheTopicLocalTransform(topic, points);
  applyObjectFrameTransform(topic, points, message?.header?.frame_id);
  scene.add(points);
  pointCloudByTopic.set(topic, points);
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

function worldPointFromMouse(event: MouseEvent) {
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

function handlePointerDown(event: MouseEvent) {
  if (event.button !== 0 || currentInteractionMode.value === "none") {
    return;
  }
  const point = worldPointFromMouse(event);
  if (!point) {
    return;
  }
  interactionStartPoint = point;
  interactionCurrentPoint = point.clone();
  controls && (controls.enabled = false);
  buildInteractionPreview(interactionStartPoint, interactionCurrentPoint);
  event.preventDefault();
}

function handlePointerMove(event: MouseEvent) {
  if (!interactionStartPoint || currentInteractionMode.value === "none") {
    return;
  }
  const point = worldPointFromMouse(event);
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
  controls && (controls.enabled = true);

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

function handlePointerUp(event: MouseEvent) {
  if (event.button !== 0) {
    return;
  }
  finishInteraction(true);
}

function handlePointerLeave() {
  if (!interactionStartPoint) {
    return;
  }
  finishInteraction(true);
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

function renderPose(topic: string, message: any) {
  if (!scene) {
    return;
  }
  const pose = message?.pose?.pose ?? message?.pose ?? {};
  const position = pose?.position ?? {};
  const orientation = pose?.orientation ?? {};
  const yaw = quaternionToYaw(orientation);

  const oldObject = poseObjectByTopic.get(topic);
  if (oldObject) {
    clearThreeObject(oldObject);
  }

  const group = new THREE.Group();

  const body = new THREE.Mesh(
    new THREE.ConeGeometry(0.22, 0.68, 18),
    new THREE.MeshStandardMaterial({ color: "#2f8cff" })
  );
  body.rotation.z = yaw - Math.PI / 2;
  body.position.set(Number(position.x ?? 0), Number(position.y ?? 0), 0.34);
  group.add(body);

  const tail = new THREE.Mesh(
    new THREE.CircleGeometry(0.12, 16),
    new THREE.MeshBasicMaterial({ color: "#31d28a" })
  );
  tail.position.set(Number(position.x ?? 0), Number(position.y ?? 0), 0.02);
  group.add(tail);

  sourceFrameByTopic.set(topic, normalizeFrameId(message?.header?.frame_id));
  cacheTopicLocalTransform(topic, group);
  applyObjectFrameTransform(topic, group, message?.header?.frame_id);
  scene.add(group);
  poseObjectByTopic.set(topic, group);
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

function renderTf(topic: string) {
  if (!scene) {
    return;
  }

  const display = getDisplayByTopic(topic);
  const visibleFrames = new Set(display?.tfVisibleFrames ?? []);
  const showAllFrames = visibleFrames.size === 0;
  const oldGroup = tfGroupByTopic.get(topic);
  if (oldGroup) {
    clearThreeObject(oldGroup);
  }

  const group = new THREE.Group();
  const frames = Array.from(tfTransformByChildFrame.keys())
    .filter((frameName) => showAllFrames || visibleFrames.has(frameName))
    .sort((left, right) => left.localeCompare(right, "zh-CN"))
    .slice(0, 80);

  frames.forEach((frameName, index) => {
    const transformMatrix = resolveFrameTransformToFixed(frameName);
    if (!transformMatrix) {
      return;
    }
    const position = new THREE.Vector3();
    const quaternion = new THREE.Quaternion();
    const scale = new THREE.Vector3();
    transformMatrix.decompose(position, quaternion, scale);

    const axes = new THREE.AxesHelper(index === 0 ? 0.9 : 0.5);
    axes.position.copy(position);
    axes.quaternion.copy(quaternion);
    group.add(axes);

    const point = new THREE.Mesh(
      new THREE.SphereGeometry(index === 0 ? 0.08 : 0.05, 12, 12),
      new THREE.MeshBasicMaterial({ color: index === 0 ? "#ffffff" : "#8ea1ba" })
    );
    point.position.copy(position);
    group.add(point);

    if (display?.tfShowNames !== false) {
      const label = buildTfLabelSprite(frameName, safeTfLabelSize(display));
      if (label) {
        label.position.set(position.x, position.y, position.z + 0.22);
        group.add(label);
      }
    }
  });

  scene.add(group);
  tfGroupByTopic.set(topic, group);
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
  cacheTopicLocalTransform(topic, points);
  applyObjectFrameTransform(topic, points, message?.header?.frame_id);
  scene.add(points);
  laserByTopic.set(topic, points);
}

function ingestTfMessage(topic: string, message: any) {
  const transforms = Array.isArray(message?.transforms) ? message.transforms : [];
  transforms.forEach((item: any) => {
    const childFrame = normalizeFrameId(item?.child_frame_id);
    const parentFrame = normalizeFrameId(item?.header?.frame_id);
    if (!childFrame || !parentFrame) {
      return;
    }
    tfTransformByChildFrame.set(childFrame, {
      parentFrame,
      matrixToParent: buildTransformMatrix(item?.transform?.translation, item?.transform?.rotation),
    });
  });
  emitTfFrames(topic);
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
  });

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
  sceneStatus.value = `暂不支持可视化: ${display.topic}`;
}

async function reconnectAndResubscribe() {
  unsubscribeMap.forEach((unsubscribe) => unsubscribe());
  unsubscribeMap.clear();
  supportTfUnsubscribeMap.forEach((unsubscribe) => unsubscribe());
  supportTfUnsubscribeMap.clear();
  clearAllTopicVisuals();
  tfTransformByChildFrame.clear();
  props.displays
    .filter((display) => display.kind === "tf")
    .forEach((display) => emit("tfFramesChange", { topic: display.topic, frames: [] }));

  rosAdapter?.disconnect();
  rosAdapter = createRosLiveAdapter({
    provider: props.provider,
    url: props.url,
    timeoutMs: props.timeoutMs,
  });

  if (!props.url && props.provider !== "mock") {
    connectionLabel.value = "未配置地址";
    sceneStatus.value = "请先填写 rosbridge 地址";
    return;
  }

  try {
    await rosAdapter.connect();
    const snapshot = rosAdapter.getConnectionSnapshot();
    connectionLabel.value = snapshot.connected ? "已连接" : "未连接";
    sceneStatus.value = snapshot.message;
    ensureSupportTfSubscriptions();
    props.displays.forEach((display) => ensureDisplaySubscription(display));
  } catch (error) {
    connectionLabel.value = "连接失败";
    sceneStatus.value = (error as Error).message;
    clearAllTopicVisuals();
  }
}

watch(
  () => [props.provider, props.url, props.timeoutMs, props.fixedFrame],
  async () => {
    await reconnectAndResubscribe();
  }
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
    syncPointCloudDisplayConfigs(nextDisplays);
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
  }
);

onMounted(async () => {
  initializeScene();
  resizeObserver = new ResizeObserver(() => fitRendererSize());
  if (mountRef.value) {
    resizeObserver.observe(mountRef.value);
  }
  renderer?.domElement.addEventListener("mousedown", handlePointerDown);
  renderer?.domElement.addEventListener("mousemove", handlePointerMove);
  renderer?.domElement.addEventListener("mouseup", handlePointerUp);
  renderer?.domElement.addEventListener("mouseleave", handlePointerLeave);
  await reconnectAndResubscribe();
});

onBeforeUnmount(() => {
  window.cancelAnimationFrame(animationFrame);
  resizeObserver?.disconnect();
  renderer?.domElement.removeEventListener("mousedown", handlePointerDown);
  renderer?.domElement.removeEventListener("mousemove", handlePointerMove);
  renderer?.domElement.removeEventListener("mouseup", handlePointerUp);
  renderer?.domElement.removeEventListener("mouseleave", handlePointerLeave);
  unsubscribeMap.forEach((unsubscribe) => unsubscribe());
  unsubscribeMap.clear();
  supportTfUnsubscribeMap.forEach((unsubscribe) => unsubscribe());
  supportTfUnsubscribeMap.clear();
  rosAdapter?.disconnect();
  controls?.dispose();
  renderer?.dispose();
  lastViewportWidth = 0;
  lastViewportHeight = 0;
});
</script>

<template>
  <div class="nav-viewer-shell">
    <div class="nav-viewer-toolbar">
      <span class="status-pill" :class="{ success: connectionLabel === '已连接' }">{{ connectionLabel }}</span>
      <span class="nav-viewer-meta">Fixed Frame: {{ fixedFrame }}</span>
      <span class="nav-viewer-meta">显示项: {{ hudDisplayCount }}</span>
    </div>

    <div ref="mountRef" class="nav-viewer-canvas-host"></div>

    <div class="nav-viewer-footer">
      <span class="nav-viewer-status">{{ sceneStatus }}</span>
      <span v-if="connectionLabel !== '已连接' || hudDisplayCount === 0" class="nav-viewer-status">
        {{ emptyStateText }}
      </span>
      <span v-if="interactionHintText" class="nav-viewer-status accent">{{ interactionHintText }}</span>
    </div>
  </div>
</template>
