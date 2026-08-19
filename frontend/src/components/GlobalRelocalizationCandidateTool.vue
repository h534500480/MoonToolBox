<!-- 功能说明：全局重定位离线候选点审核页，承接 PCD 预览、候选点人工编辑和 manual_candidates.yaml 导出流程。 -->
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

import {
  browsePath,
  exportGlobalRelocalizationManual,
  fetchGlobalRelocalizationCandidates,
  fetchGlobalRelocalizationPcdPreview,
  openLocalPath,
  type GlobalRelocalizationCandidateItem,
} from "../api/client";
import type { ToolDefinition } from "../types";

interface CandidatePoint {
  candidate_id: number;
  x: number;
  y: number;
  z: number;
  roll_deg: number;
  pitch_deg: number;
  yaw_deg: number;
  qx: number;
  qy: number;
  qz: number;
  qw: number;
  observability_score: number;
  hit_count: number;
  hit_ratio: number;
  visible_sector_count: number;
  descriptor_nonzero_ratio: number;
  source: "auto" | "manual_added";
  locked: boolean;
  label: string;
  note: string;
  original_candidate_id: number;
  z_auto?: boolean;
  z_frame?: "ground" | "base_link";
  yaw_expand_deg?: string;
}

interface DeletionRegion {
  label: string;
  min_x: number;
  max_x: number;
  min_y: number;
  max_y: number;
}

interface ConfigField {
  section: string;
  key: string;
  label: string;
  value: string;
  help: string;
}

interface EditorSnapshot {
  candidates: CandidatePoint[];
  deletedCandidates: CandidatePoint[];
  deletionRegions: DeletionRegion[];
  selectedIds: number[];
}

interface CandidatePoseGroup {
  key: string;
  x: number;
  y: number;
  z: number;
  candidates: CandidatePoint[];
}

interface CandidatePickHit {
  pickKind: "group" | "candidate";
  groupKey: string;
  candidateIds?: number[];
  candidateId?: number;
}

const props = defineProps<{
  tool: ToolDefinition;
  loading: boolean;
  summary: string;
  logs: string[];
  resultData: Record<string, any>;
}>();

const emit = defineEmits<{
  run: [values: Record<string, string>];
  clearLogs: [];
}>();

const formValues = reactive<Record<string, string>>({});
const configValues = reactive<Record<string, string>>({});
const mountRef = ref<HTMLDivElement | null>(null);
const sceneMessage = ref("等待加载 PCD 地图和候选点。");
const interactionMode = ref<"select" | "box" | "add">("select");
const candidates = ref<CandidatePoint[]>([]);
const deletedCandidates = ref<CandidatePoint[]>([]);
const selectedIds = ref<number[]>([]);
const deletionRegions = ref<DeletionRegion[]>([]);
const manualLabel = ref("");
const manualZ = ref("");
const manualUseAutoZ = ref(true);
const manualYawDeg = ref("0.0");
const manualYawExpand = ref("0");
const manualNote = ref("前端人工补点，z 由 3D ground index 自动估计。");
const exportPreview = ref("");
const exportMessage = ref("");
const boxSelectionStyle = ref({ left: "0px", top: "0px", width: "0px", height: "0px" });
const boxSelecting = ref(false);
const undoStack = ref<EditorSnapshot[]>([]);
const redoStack = ref<EditorSnapshot[]>([]);
let editingCandidateSnapshotActive = false;

let renderer: THREE.WebGLRenderer | null = null;
let scene: THREE.Scene | null = null;
let camera: THREE.PerspectiveCamera | null = null;
let controls: OrbitControls | null = null;
let resizeObserver: ResizeObserver | null = null;
let animationFrame = 0;
let pointCloudObject: THREE.Points | null = null;
let candidateGroup: THREE.Group | null = null;
let candidateMaterial: THREE.MeshBasicMaterial | null = null;
let selectedCandidateMaterial: THREE.MeshBasicMaterial | null = null;
let manualCandidateMaterial: THREE.MeshBasicMaterial | null = null;
let lockedCandidateMaterial: THREE.MeshBasicMaterial | null = null;
let boxStart: { x: number; y: number } | null = null;
let dragState: {
  groupKey: string;
  candidateIds: number[];
  previousPoint: THREE.Vector3;
  plane: THREE.Plane;
  historyRecorded: boolean;
} | null = null;

const raycaster = new THREE.Raycaster();
const pointer = new THREE.Vector2();
const groundPlane = new THREE.Plane(new THREE.Vector3(0, 0, 1), 0);

const configFields: ConfigField[] = [
  { section: "map", key: "voxel_leaf_m", label: "voxel_leaf_m", value: "0.20", help: "点云体素降采样尺寸，越大越快但细节越少。" },
  { section: "map", key: "occupancy_resolution_m", label: "occupancy_resolution_m", value: "0.25", help: "三维占据栅格分辨率，用于 clearance 和 ray casting 查询。" },
  { section: "map", key: "z_min_m", label: "z_min_m", value: "-3.0", help: "读取地图时保留的最低 Z，低于该值的点会被忽略。" },
  { section: "map", key: "z_max_m", label: "z_max_m", value: "5.0", help: "读取地图时保留的最高 Z，高于该值的点会被忽略。" },
  { section: "candidate_sampling", key: "strategy", label: "strategy", value: "adaptive_random", help: "候选 base 位置采样策略，当前推荐 adaptive_random。" },
  { section: "candidate_sampling", key: "xy_resolution_m", label: "xy_resolution_m", value: "0.50", help: "候选采样和 ground index 使用的 XY 网格尺寸。" },
  { section: "candidate_sampling", key: "z_resolution_m", label: "z_resolution_m", value: "0.20", help: "候选采样时用于高度离散或后续扩展的 Z 分辨率。" },
  { section: "candidate_sampling", key: "min_candidate_distance_m", label: "min_candidate_distance_m", value: "0.80", help: "已接受候选 base 之间的最小平面距离，控制候选密度。" },
  { section: "candidate_sampling", key: "robot_radius_m", label: "robot_radius_m", value: "0.63", help: "机器人 footprint 外包圆半径，用于离线 clearance 检查。" },
  { section: "candidate_sampling", key: "safety_margin_m", label: "safety_margin_m", value: "0.05", help: "候选点 clearance 的额外安全余量，贴墙时应适当增大。" },
  { section: "candidate_sampling", key: "clearance_check_height_m", label: "clearance_check_height_m", value: "0.80", help: "从候选点 Z 向上检查的圆柱高度。" },
  { section: "candidate_sampling", key: "clearance_min_free_ratio", label: "clearance_min_free_ratio", value: "0.65", help: "clearance 圆柱中需要为空的比例，越高越保守。" },
  { section: "candidate_sampling", key: "map_boundary_margin_m", label: "map_boundary_margin_m", value: "1.0", help: "候选点离 PCD 外包框边缘的最小距离，避免采到地图外空域。" },
  { section: "candidate_sampling", key: "ground_min_points_per_cell", label: "ground_min_points_per_cell", value: "4", help: "单个 ground cell 至少需要的点数，过高会减少候选。" },
  { section: "candidate_sampling", key: "ground_support_radius_m", label: "ground_support_radius_m", value: "0.80", help: "候选点周围需要连续地面支撑的半径。" },
  { section: "candidate_sampling", key: "ground_min_neighbor_cells", label: "ground_min_neighbor_cells", value: "4", help: "邻域内至少需要多少个 ground cell，避免孤立噪点。" },
  { section: "candidate_sampling", key: "ground_support_max_delta_z_m", label: "ground_support_max_delta_z_m", value: "0.35", help: "邻域 ground z 与中心 z 的最大允许差，过大可能是墙边或台阶边缘。" },
  { section: "candidate_sampling", key: "base_link_height_offset_m", label: "base_link_height_offset_m", value: "0.35", help: "人工地面点和自动 ground z 转换到 map 下 base_link z 的高度偏移；不同机器人需要按实际 base_link 离地高度调整。" },
  { section: "candidate_sampling", key: "roll_samples_deg", label: "roll_samples_deg", value: "0.0", help: "候选姿态展开的 roll 角列表，多个值用逗号分隔。" },
  { section: "candidate_sampling", key: "pitch_samples_deg", label: "pitch_samples_deg", value: "0.0", help: "候选姿态展开的 pitch 角列表，多个值用逗号分隔。" },
  { section: "candidate_sampling", key: "yaw_step_deg", label: "yaw_step_deg", value: "45.0", help: "v2 离线库不再按 yaw 展开，该参数仅保留用于兼容旧配置。" },
  { section: "candidate_sampling", key: "random_seed", label: "random_seed", value: "7", help: "随机采样种子，用于复现实验结果。" },
  { section: "candidate_sampling", key: "target_base_positions", label: "target_base_positions", value: "120", help: "目标 base 位置数量，不包含 yaw 展开后的姿态倍增。" },
  { section: "candidate_sampling", key: "max_base_samples", label: "max_base_samples", value: "2500", help: "最多尝试多少个 base 采样点，越大覆盖越充分但更慢。" },
  { section: "candidate_sampling", key: "early_stop_window", label: "early_stop_window", value: "500", help: "早停窗口大小，用于判断采样效率是否过低。" },
  { section: "candidate_sampling", key: "early_stop_min_accepts", label: "early_stop_min_accepts", value: "5", help: "早停窗口内至少接受的 base 数，低于该值会提前停止。" },
  { section: "candidate_sampling", key: "max_candidates", label: "max_candidates", value: "200000", help: "最终候选 place 最大数量，防止配置过密导致文件过大。" },
  { section: "virtual_lidar", key: "min_range_m", label: "min_range_m", value: "0.30", help: "虚拟 LiDAR 最近有效距离，需要与在线 scan_context_query_min_range_m 一致。" },
  { section: "virtual_lidar", key: "max_range_m", label: "max_range_m", value: "30.0", help: "虚拟 LiDAR 最远有效距离，影响 Scan Context 可见范围。" },
  { section: "virtual_lidar", key: "horizontal_fov_deg", label: "horizontal_fov_deg", value: "360.0", help: "虚拟 LiDAR 水平视场角。" },
  { section: "virtual_lidar", key: "vertical_fov_deg", label: "vertical_fov_deg", value: "59.0", help: "虚拟 LiDAR 垂直视场角，需要与在线 scan_context_query_vertical_fov_deg 一致。" },
  { section: "virtual_lidar", key: "horizontal_step_deg", label: "horizontal_step_deg", value: "2.0", help: "虚拟 LiDAR 水平射线角分辨率，越小越慢；需与在线 query 参数一致。" },
  { section: "virtual_lidar", key: "vertical_step_deg", label: "vertical_step_deg", value: "2.0", help: "虚拟 LiDAR 垂直射线角分辨率，越小越慢；需与在线 query 参数一致。" },
  { section: "virtual_lidar", key: "occupancy_inflate_radius_m", label: "occupancy_inflate_radius_m", value: "0.15", help: "synthetic LiDAR 查询占据体素膨胀半径，需要与在线 scan_context_query_occupancy_inflate_radius_m 一致。" },
  { section: "virtual_lidar", key: "lidar_to_base_translation_xyz", label: "lidar_to_base_translation_xyz", value: "0,0,0", help: "LiDAR 相对 base_link 的平移外参；在线 cloud 已是 base_link 语义时保持 0,0,0。" },
  { section: "virtual_lidar", key: "lidar_to_base_rpy_deg", label: "lidar_to_base_rpy_deg", value: "0,0,0", help: "LiDAR 相对 base_link 的旋转外参；在线 cloud 已是 base_link 语义时保持 0,0,0。" },
  { section: "observability", key: "min_hit_points", label: "min_hit_points", value: "80", help: "合成扫描至少需要命中的点数，过低说明该候选观测不足。" },
  { section: "observability", key: "min_hit_ratio", label: "min_hit_ratio", value: "0.03", help: "合成射线命中比例下限，用于过滤空视野候选。" },
  { section: "observability", key: "min_visible_sector_count", label: "min_visible_sector_count", value: "12", help: "Scan Context 中至少有观测的扇区数量。" },
  { section: "observability", key: "min_descriptor_nonzero_ratio", label: "min_descriptor_nonzero_ratio", value: "0.03", help: "descriptor 非零单元比例下限，过低说明描述子太空。" },
  { section: "descriptor", key: "num_rings", label: "num_rings", value: "20", help: "Scan Context 极坐标环数。" },
  { section: "descriptor", key: "num_sectors", label: "num_sectors", value: "60", help: "Scan Context 极坐标扇区数。" },
  { section: "descriptor", key: "max_radius_m", label: "max_radius_m", value: "30.0", help: "Scan Context 最大半径。" },
  { section: "descriptor", key: "height_clip_min_m", label: "height_clip_min_m", value: "-3.0", help: "descriptor 高度裁剪下限。" },
  { section: "descriptor", key: "height_clip_max_m", label: "height_clip_max_m", value: "5.0", help: "descriptor 高度裁剪上限。" },
  { section: "manual_edit", key: "allow_force_add_low_observability", label: "allow_force_add_low_observability", value: "false", help: "是否允许强制加入可观测性不达标的人工点，默认不允许。" },
  { section: "manual_edit", key: "manual_points_bypass_min_distance", label: "manual_points_bypass_min_distance", value: "true", help: "人工点是否绕过自动候选之间的最小距离限制。" },
  { section: "manual_edit", key: "manual_points_bypass_random_quota", label: "manual_points_bypass_random_quota", value: "true", help: "人工点是否绕过随机采样数量配额。" },
];

const configSections = computed(() => Array.from(new Set(configFields.map((item) => item.section))));
const selectedCandidates = computed(() => candidates.value.filter((item) => selectedIds.value.includes(item.candidate_id)));
const activeCandidateCount = computed(() => candidates.value.length);
const loadedCandidateCount = computed(() => candidates.value.filter((item) => item.source === "auto").length);
const manualCandidateCount = computed(() => candidates.value.filter((item) => item.source === "manual_added").length);
const lockedCandidateCount = computed(() => candidates.value.filter((item) => item.locked).length);
const canUndo = computed(() => undoStack.value.length > 0);
const canRedo = computed(() => redoStack.value.length > 0);

const configPayload = computed(() => {
  const payload: Record<string, Record<string, string | boolean>> = {};
  configFields.forEach((field) => {
    if (!payload[field.section]) {
      payload[field.section] = {};
    }
    const rawValue = configValues[configKey(field)] ?? field.value;
    payload[field.section][field.key] = rawValue === "true" ? true : rawValue === "false" ? false : rawValue;
  });
  return payload;
});

const manualYamlPreview = computed(() => {
  const manualPayload = buildManualExportPayload(false);
  return JSON.stringify(manualPayload, null, 2);
});

function configKey(field: ConfigField) {
  return `${field.section}.${field.key}`;
}

function cloneCandidate(candidate: CandidatePoint): CandidatePoint {
  return { ...candidate };
}

function createEditorSnapshot(): EditorSnapshot {
  return {
    candidates: candidates.value.map(cloneCandidate),
    deletedCandidates: deletedCandidates.value.map(cloneCandidate),
    deletionRegions: deletionRegions.value.map((region) => ({ ...region })),
    selectedIds: [...selectedIds.value],
  };
}

function restoreEditorSnapshot(snapshot: EditorSnapshot) {
  candidates.value = snapshot.candidates.map(cloneCandidate);
  deletedCandidates.value = snapshot.deletedCandidates.map(cloneCandidate);
  deletionRegions.value = snapshot.deletionRegions.map((region) => ({ ...region }));
  selectedIds.value = [...snapshot.selectedIds];
}

function recordHistory() {
  undoStack.value = [...undoStack.value.slice(-79), createEditorSnapshot()];
  redoStack.value = [];
}

function undoEdit() {
  const snapshot = undoStack.value.at(-1);
  if (!snapshot) {
    return;
  }
  redoStack.value = [...redoStack.value, createEditorSnapshot()];
  undoStack.value = undoStack.value.slice(0, -1);
  restoreEditorSnapshot(snapshot);
  sceneMessage.value = "已撤销上一步编辑。";
}

function redoEdit() {
  const snapshot = redoStack.value.at(-1);
  if (!snapshot) {
    return;
  }
  undoStack.value = [...undoStack.value, createEditorSnapshot()];
  redoStack.value = redoStack.value.slice(0, -1);
  restoreEditorSnapshot(snapshot);
  sceneMessage.value = "已重做编辑。";
}

function beginCandidateFieldEdit() {
  if (editingCandidateSnapshotActive) {
    return;
  }
  recordHistory();
  editingCandidateSnapshotActive = true;
}

function endCandidateFieldEdit() {
  editingCandidateSnapshotActive = false;
}

function normalizeSortCoordinate(value: number) {
  return Math.round(value * 1000);
}

function candidateGroupKey(candidate: Pick<CandidatePoint, "x" | "y" | "z">) {
  return [
    normalizeSortCoordinate(candidate.x),
    normalizeSortCoordinate(candidate.y),
    normalizeSortCoordinate(candidate.z),
  ].join(":");
}

function buildCandidatePoseGroups(items = candidates.value): CandidatePoseGroup[] {
  const groupMap = new Map<string, CandidatePoseGroup>();
  items.forEach((candidate) => {
    const key = candidateGroupKey(candidate);
    const existing = groupMap.get(key);
    if (existing) {
      existing.candidates.push(candidate);
      return;
    }
    groupMap.set(key, {
      key,
      x: candidate.x,
      y: candidate.y,
      z: candidate.z,
      candidates: [candidate],
    });
  });
  return Array.from(groupMap.values()).map((group) => ({
    ...group,
    candidates: [...group.candidates].sort((left, right) => left.yaw_deg - right.yaw_deg),
  }));
}

function sortedFinalCandidates() {
  return candidates.value
    .map(cloneCandidate)
    .sort((left, right) => {
      const fields = [
        normalizeSortCoordinate(left.x) - normalizeSortCoordinate(right.x),
        normalizeSortCoordinate(left.y) - normalizeSortCoordinate(right.y),
        normalizeSortCoordinate(left.z) - normalizeSortCoordinate(right.z),
        left.roll_deg - right.roll_deg,
        left.pitch_deg - right.pitch_deg,
        left.yaw_deg - right.yaw_deg,
        left.original_candidate_id - right.original_candidate_id,
      ];
      return fields.find((value) => value !== 0) ?? 0;
    })
    .map((candidate, index) => ({
      ...candidate,
      candidate_id: index,
    }));
}

function initializeFormValues() {
  props.tool.fields.forEach((field) => {
    formValues[field.key] = field.value ?? "";
  });
  if (!formValues.base_frame) {
    formValues.base_frame = "base_link";
  }
  configFields.forEach((field) => {
    configValues[configKey(field)] = field.value;
  });
}

function initializeScene() {
  const host = mountRef.value;
  if (!host) {
    return;
  }
  scene = new THREE.Scene();
  scene.background = new THREE.Color("#07121d");
  scene.up.set(0, 0, 1);

  camera = new THREE.PerspectiveCamera(52, 1, 0.01, 800);
  camera.up.set(0, 0, 1);
  camera.position.set(12, -14, 10);
  camera.lookAt(0, 0, 0);

  renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(window.devicePixelRatio);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.domElement.style.display = "block";
  renderer.domElement.style.width = "100%";
  renderer.domElement.style.height = "100%";
  host.appendChild(renderer.domElement);

  controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.target.set(0, 0, 0);
  controls.screenSpacePanning = false;

  scene.add(new THREE.AmbientLight("#d8e9ff", 1.35));
  const grid = new THREE.GridHelper(60, 60, "#2f8cff", "#21334c");
  grid.rotateX(Math.PI / 2);
  scene.add(grid);
  scene.add(new THREE.AxesHelper(1.6));

  candidateGroup = new THREE.Group();
  scene.add(candidateGroup);
  candidateMaterial = new THREE.MeshBasicMaterial({ color: "#ffd166" });
  selectedCandidateMaterial = new THREE.MeshBasicMaterial({ color: "#31d28a" });
  manualCandidateMaterial = new THREE.MeshBasicMaterial({ color: "#f15d78" });
  lockedCandidateMaterial = new THREE.MeshBasicMaterial({ color: "#7bdff2" });

  fitRendererSize();
  animate();
}

function fitRendererSize() {
  if (!renderer || !camera || !mountRef.value) {
    return;
  }
  const bounds = mountRef.value.getBoundingClientRect();
  const width = Math.max(320, Math.round(bounds.width));
  const height = Math.max(360, Math.round(bounds.height));
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

function disposeObject(object: THREE.Object3D | null) {
  if (!object) {
    return;
  }
  object.traverse((child) => {
    const mesh = child as THREE.Mesh;
    mesh.geometry?.dispose();
    const material = mesh.material;
    if (Array.isArray(material)) {
      material.forEach((item) => item.dispose());
    } else {
      material?.dispose();
    }
  });
  scene?.remove(object);
}

function disposeObjectGeometry(object: THREE.Object3D) {
  object.traverse((child) => {
    const mesh = child as THREE.Mesh;
    mesh.geometry?.dispose();
  });
}

function teardownScene() {
  window.cancelAnimationFrame(animationFrame);
  resizeObserver?.disconnect();
  disposeObject(pointCloudObject);
  disposeObject(candidateGroup);
  candidateMaterial?.dispose();
  selectedCandidateMaterial?.dispose();
  manualCandidateMaterial?.dispose();
  lockedCandidateMaterial?.dispose();
  controls?.dispose();
  renderer?.dispose();
  const canvas = renderer?.domElement;
  if (canvas?.parentElement) {
    canvas.parentElement.removeChild(canvas);
  }
  pointCloudObject = null;
  candidateGroup = null;
  renderer = null;
  scene = null;
  camera = null;
}

function renderPointCloud(points: number[][]) {
  if (!scene) {
    return;
  }
  disposeObject(pointCloudObject);
  const positions = points.flat();
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  const material = new THREE.PointsMaterial({
    color: "#d7dee8",
    size: 0.06,
    sizeAttenuation: true,
    transparent: true,
    opacity: 0.78,
  });
  pointCloudObject = new THREE.Points(geometry, material);
  scene.add(pointCloudObject);
  focusPositions(positions);
}

function focusPositions(positions: number[]) {
  if (!camera || !controls || positions.length < 3) {
    return;
  }
  const box = new THREE.Box3();
  for (let index = 0; index < positions.length; index += 3) {
    box.expandByPoint(new THREE.Vector3(positions[index], positions[index + 1], positions[index + 2]));
  }
  const center = new THREE.Vector3();
  const size = new THREE.Vector3();
  box.getCenter(center);
  box.getSize(size);
  const distance = Math.max(size.x, size.y, size.z, 8) * 0.9;
  controls.target.copy(center);
  camera.position.set(center.x + distance, center.y - distance, center.z + distance * 0.65);
  camera.lookAt(center);
  controls.update();
}

function focusSceneFromDirection(direction: THREE.Vector3) {
  if (!camera || !controls) {
    return;
  }
  const target = controls.target.clone();
  const distance = Math.max(8, camera.position.distanceTo(target));
  const nextPosition = target.clone().add(direction.normalize().multiplyScalar(distance));
  camera.position.copy(nextPosition);
  camera.lookAt(target);
  controls.update();
}

function setAxisView(axis: "x" | "y" | "z" | "home") {
  if (axis === "x") {
    focusSceneFromDirection(new THREE.Vector3(1, 0, 0.08));
  } else if (axis === "y") {
    focusSceneFromDirection(new THREE.Vector3(0, -1, 0.08));
  } else if (axis === "z") {
    focusSceneFromDirection(new THREE.Vector3(0, 0, 1));
  } else {
    focusSceneFromDirection(new THREE.Vector3(0.8, -1, 0.65));
  }
}

async function browseField(fieldKey: string, mode: "open_file" | "open_dir" | "save_file") {
  try {
    const path = await browsePath({
      mode,
      title: `选择${fieldKey}`,
      initial_path: formValues[fieldKey] ?? "",
    });
    if (path) {
      formValues[fieldKey] = path;
    }
  } catch (error) {
    sceneMessage.value = `选择路径失败: ${(error as Error).message}`;
  }
}

async function loadPointCloudFromPath() {
  if (!formValues.input_pcd?.trim()) {
    sceneMessage.value = "请先选择输入 PCD。";
    return;
  }
  try {
    const response = await fetchGlobalRelocalizationPcdPreview(formValues.input_pcd, 90000);
    renderPointCloud(response.points);
    sceneMessage.value = `已加载 PCD: ${response.sampled_count} / ${response.point_count} 点`;
  } catch (error) {
    sceneMessage.value = `点云加载失败: ${(error as Error).message}`;
  }
}

function normalizeCandidate(item: GlobalRelocalizationCandidateItem): CandidatePoint {
  const placeId = Number(item.place_id ?? item.candidate_id);
  const canonicalYawDeg = Number(item.canonical_yaw_deg ?? item.yaw_deg ?? 0);
  return {
    candidate_id: placeId,
    x: Number(item.x),
    y: Number(item.y),
    z: Number(item.z),
    roll_deg: Number(item.roll_deg),
    pitch_deg: Number(item.pitch_deg),
    yaw_deg: canonicalYawDeg,
    qx: Number(item.qx),
    qy: Number(item.qy),
    qz: Number(item.qz),
    qw: Number(item.qw),
    observability_score: Number(item.observability_score),
    hit_count: Number(item.hit_count),
    hit_ratio: Number(item.hit_ratio),
    visible_sector_count: Number(item.visible_sector_count),
    descriptor_nonzero_ratio: Number(item.descriptor_nonzero_ratio),
    source: item.source === "manual_added" ? "manual_added" : "auto",
    locked: Boolean(item.locked),
    label: String(item.label || ""),
    note: "",
    original_candidate_id: Number(item.original_candidate_id ?? placeId),
    z_frame: item.z_frame === "ground" ? "ground" : "base_link",
  };
}

async function loadCandidatesFromPath() {
  if (!formValues.candidate_file?.trim()) {
    sceneMessage.value = "请先选择 candidates.csv 或 candidates.npy。";
    return;
  }
  try {
    const response = await fetchGlobalRelocalizationCandidates(formValues.candidate_file);
    recordHistory();
    candidates.value = response.candidates.map(normalizeCandidate);
    deletedCandidates.value = [];
    selectedIds.value = [];
    deletionRegions.value = [];
    sceneMessage.value = `已加载候选点: ${response.candidate_count} 个`;
  } catch (error) {
    sceneMessage.value = `候选点加载失败: ${(error as Error).message}`;
  }
}

function quaternionFromYaw(yawDeg: number) {
  const halfYaw = THREE.MathUtils.degToRad(yawDeg) / 2;
  return { x: 0, y: 0, z: Math.sin(halfYaw), w: Math.cos(halfYaw) };
}

function nextCandidateId() {
  const activeMax = candidates.value.reduce((maxId, item) => Math.max(maxId, item.candidate_id), -1);
  const trashMax = deletedCandidates.value.reduce((maxId, item) => Math.max(maxId, item.candidate_id), -1);
  return Math.max(activeMax, trashMax) + 1;
}

function materialForCandidate(candidate: CandidatePoint, selected: boolean) {
  if (selected && selectedCandidateMaterial) {
    return selectedCandidateMaterial;
  }
  if (candidate.locked && lockedCandidateMaterial) {
    return lockedCandidateMaterial;
  }
  if (candidate.source === "manual_added" && manualCandidateMaterial) {
    return manualCandidateMaterial;
  }
  return candidateMaterial;
}

function renderCandidates() {
  if (!candidateGroup || !candidateMaterial) {
    return;
  }
  while (candidateGroup.children.length) {
    const child = candidateGroup.children[0];
    candidateGroup.remove(child);
    disposeObjectGeometry(child);
  }
  buildCandidatePoseGroups().forEach((group) => {
    const groupIds = group.candidates.map((candidate) => candidate.candidate_id);
    const selectedCount = groupIds.filter((id) => selectedIds.value.includes(id)).length;
    const groupSelected = selectedCount === groupIds.length && groupIds.length > 0;
    const hasManual = group.candidates.some((candidate) => candidate.source === "manual_added");
    const hasLocked = group.candidates.some((candidate) => candidate.locked);
    const markerMaterial = groupSelected
      ? selectedCandidateMaterial
      : hasLocked
        ? lockedCandidateMaterial
        : hasManual
          ? manualCandidateMaterial
          : candidateMaterial;
    const marker = new THREE.Mesh(new THREE.SphereGeometry(groupSelected ? 0.24 : 0.18, 18, 14), markerMaterial ?? candidateMaterial!);
    marker.position.set(group.x, group.y, group.z);
    marker.userData.groupKey = group.key;
    marker.userData.candidateIds = groupIds;
    marker.userData.pickKind = "group";
    candidateGroup?.add(marker);

    group.candidates.forEach((candidate) => {
      const selected = selectedIds.value.includes(candidate.candidate_id);
      const direction = new THREE.ArrowHelper(
        new THREE.Vector3(Math.cos(THREE.MathUtils.degToRad(candidate.yaw_deg)), Math.sin(THREE.MathUtils.degToRad(candidate.yaw_deg)), 0),
        marker.position,
        selected ? 1.02 : 0.88,
        selected ? "#31d28a" : candidate.locked ? "#7bdff2" : "#ffd166",
        selected ? 0.26 : 0.22,
        selected ? 0.14 : 0.12
      );
      direction.userData.candidateId = candidate.candidate_id;
      direction.userData.groupKey = group.key;
      direction.userData.pickKind = "candidate";
      direction.traverse((child) => {
        child.userData.candidateId = candidate.candidate_id;
        child.userData.groupKey = group.key;
        child.userData.pickKind = "candidate";
      });
      candidateGroup?.add(direction);
    });
  });
}

function selectCandidate(id: number, additive = false) {
  if (additive) {
    selectedIds.value = selectedIds.value.includes(id)
      ? selectedIds.value.filter((item) => item !== id)
      : [...selectedIds.value, id];
    return;
  }
  selectedIds.value = [id];
}

function selectCandidateGroup(candidateIds: number[], additive = false) {
  if (additive) {
    const current = new Set(selectedIds.value);
    const allSelected = candidateIds.every((id) => current.has(id));
    candidateIds.forEach((id) => {
      if (allSelected) {
        current.delete(id);
      } else {
        current.add(id);
      }
    });
    selectedIds.value = Array.from(current);
    return;
  }
  selectedIds.value = [...candidateIds];
}

function deleteSelectedCandidates() {
  const selectedSet = new Set(selectedIds.value);
  if (selectedSet.size === 0) {
    return;
  }
  recordHistory();
  const lockedIds = candidates.value.filter((item) => selectedSet.has(item.candidate_id) && item.locked).map((item) => item.candidate_id);
  const deletable = candidates.value.filter((item) => selectedSet.has(item.candidate_id) && !item.locked);
  deletedCandidates.value = [...deletedCandidates.value, ...deletable];
  candidates.value = candidates.value.filter((item) => !selectedSet.has(item.candidate_id) || item.locked);
  selectedIds.value = lockedIds;
  sceneMessage.value = lockedIds.length
    ? `已删除 ${deletable.length} 个候选点，跳过 ${lockedIds.length} 个锁定点。`
    : `已移入回收站: ${deletable.length} 个候选点`;
}

function restoreCandidate(id: number) {
  const target = deletedCandidates.value.find((item) => item.candidate_id === id);
  if (!target) {
    return;
  }
  recordHistory();
  deletedCandidates.value = deletedCandidates.value.filter((item) => item.candidate_id !== id);
  candidates.value = [...candidates.value, target].sort((left, right) => left.candidate_id - right.candidate_id);
}

function purgeTrash() {
  if (deletedCandidates.value.length === 0) {
    return;
  }
  recordHistory();
  deletedCandidates.value = [];
}

function toggleSelectedLocked() {
  const selectedSet = new Set(selectedIds.value);
  if (selectedSet.size === 0) {
    return;
  }
  recordHistory();
  candidates.value = candidates.value.map((candidate) =>
    selectedSet.has(candidate.candidate_id) ? { ...candidate, locked: !candidate.locked } : candidate
  );
}

function parseNumberList(value: string) {
  return value
    .split(/[,，\s]+/)
    .map((item) => Number(item))
    .filter((item) => Number.isFinite(item));
}

function addManualCandidate(point: THREE.Vector3) {
  recordHistory();
  const baseYawDeg = Number(manualYawDeg.value) || 0;
  const yawOffsets = parseNumberList(manualYawExpand.value);
  const yawValues = (yawOffsets.length ? yawOffsets : [0]).map((offset) => ((baseYawDeg + offset) % 360 + 360) % 360);
  const uniqueYawValues = Array.from(new Set(yawValues.map((value) => Math.round(value * 1000) / 1000))).sort((left, right) => left - right);
  let nextId = nextCandidateId();
  const z = manualUseAutoZ.value ? point.z : Number(manualZ.value) || point.z;
  const label = manualLabel.value.trim() || `manual_${nextId}`;
  const additions = uniqueYawValues.map((yawDeg) => {
    const quaternion = quaternionFromYaw(yawDeg);
    const candidateId = nextId++;
    return {
      candidate_id: candidateId,
      x: point.x,
      y: point.y,
      z,
      roll_deg: 0,
      pitch_deg: 0,
      yaw_deg: yawDeg,
      qx: quaternion.x,
      qy: quaternion.y,
      qz: quaternion.z,
      qw: quaternion.w,
      observability_score: 0,
      hit_count: 0,
      hit_ratio: 0,
      visible_sector_count: 0,
      descriptor_nonzero_ratio: 0,
      source: "manual_added" as const,
      locked: true,
      label,
      note: manualNote.value.trim(),
      original_candidate_id: candidateId,
      z_auto: manualUseAutoZ.value,
      z_frame: "ground" as const,
      yaw_expand_deg: manualYawExpand.value,
    };
  });
  candidates.value = [...candidates.value, ...additions];
  selectedIds.value = additions.map((candidate) => candidate.candidate_id);
  sceneMessage.value = `已添加人工候选点组: ${additions.length} 个方向，后续由离线工具重算 descriptor。`;
}

function updatePointer(event: MouseEvent) {
  const canvas = renderer?.domElement;
  if (!canvas) {
    return false;
  }
  const bounds = canvas.getBoundingClientRect();
  pointer.x = ((event.clientX - bounds.left) / bounds.width) * 2 - 1;
  pointer.y = -((event.clientY - bounds.top) / bounds.height) * 2 + 1;
  return true;
}

function projectWorldToCanvas(point: THREE.Vector3) {
  if (!renderer || !camera) {
    return null;
  }
  const bounds = renderer.domElement.getBoundingClientRect();
  const projected = point.clone().project(camera);
  if (projected.z < -1 || projected.z > 1) {
    return null;
  }
  return {
    x: ((projected.x + 1) / 2) * bounds.width,
    y: ((-projected.y + 1) / 2) * bounds.height,
  };
}

function distanceToSegment(point: { x: number; y: number }, start: { x: number; y: number }, end: { x: number; y: number }) {
  const vx = end.x - start.x;
  const vy = end.y - start.y;
  const wx = point.x - start.x;
  const wy = point.y - start.y;
  const lengthSq = vx * vx + vy * vy;
  if (lengthSq <= 0.0001) {
    return Math.hypot(point.x - start.x, point.y - start.y);
  }
  const t = Math.max(0, Math.min(1, (wx * vx + wy * vy) / lengthSq));
  const px = start.x + t * vx;
  const py = start.y + t * vy;
  return Math.hypot(point.x - px, point.y - py);
}

function pickCandidateVisual(event: MouseEvent): CandidatePickHit | null {
  if (!renderer || !camera) {
    return null;
  }
  const bounds = renderer.domElement.getBoundingClientRect();
  const mouse = {
    x: event.clientX - bounds.left,
    y: event.clientY - bounds.top,
  };
  const arrowHits: Array<CandidatePickHit & { distance: number }> = [];
  const groupHits: Array<CandidatePickHit & { distance: number }> = [];

  buildCandidatePoseGroups().forEach((group) => {
    const centerWorld = new THREE.Vector3(group.x, group.y, group.z);
    const center = projectWorldToCanvas(centerWorld);
    if (!center) {
      return;
    }
    const centerDistance = Math.hypot(mouse.x - center.x, mouse.y - center.y);
    if (centerDistance <= 22) {
      groupHits.push({
        pickKind: "group",
        groupKey: group.key,
        candidateIds: group.candidates.map((candidate) => candidate.candidate_id),
        distance: centerDistance,
      });
    }

    group.candidates.forEach((candidate) => {
      const yaw = THREE.MathUtils.degToRad(candidate.yaw_deg);
      const arrowEndWorld = new THREE.Vector3(
        group.x + Math.cos(yaw) * 0.95,
        group.y + Math.sin(yaw) * 0.95,
        group.z
      );
      const arrowEnd = projectWorldToCanvas(arrowEndWorld);
      if (!arrowEnd) {
        return;
      }
      const segmentDistance = distanceToSegment(mouse, center, arrowEnd);
      const headDistance = Math.hypot(mouse.x - arrowEnd.x, mouse.y - arrowEnd.y);
      const distance = Math.min(segmentDistance, headDistance);
      if (distance <= 14) {
        arrowHits.push({
          pickKind: "candidate",
          groupKey: group.key,
          candidateId: candidate.candidate_id,
          distance,
        });
      }
    });
  });

  groupHits.sort((left, right) => left.distance - right.distance);
  if (groupHits[0]) {
    return groupHits[0];
  }
  arrowHits.sort((left, right) => left.distance - right.distance);
  return arrowHits[0] ?? null;
}

function beginGroupDrag(hit: CandidatePickHit, event: MouseEvent) {
  if (!camera || !controls || !updatePointer(event)) {
    return;
  }
  raycaster.setFromCamera(pointer, camera);
  const candidateIds = hit.candidateIds ?? [];
  const groupKey = hit.groupKey;
  if (!candidateIds.length || !groupKey) {
    return;
  }
  selectCandidateGroup(candidateIds, event.ctrlKey || event.shiftKey);
  const group = buildCandidatePoseGroups().find((item) => item.key === groupKey);
  if (!group) {
    return;
  }
  const cameraDirection = new THREE.Vector3();
  camera.getWorldDirection(cameraDirection);
  const plane = new THREE.Plane().setFromNormalAndCoplanarPoint(
    cameraDirection,
    new THREE.Vector3(group.x, group.y, group.z)
  );
  const previousPoint = new THREE.Vector3();
  if (!raycaster.ray.intersectPlane(plane, previousPoint)) {
    return;
  }
  dragState = {
    groupKey,
    candidateIds,
    previousPoint,
    plane,
    historyRecorded: false,
  };
  controls.enabled = false;
}

function updateGroupDrag(event: MouseEvent) {
  if (!dragState || !renderer || !camera || !updatePointer(event)) {
    return false;
  }
  raycaster.setFromCamera(pointer, camera);
  const nextPoint = new THREE.Vector3();
  if (!raycaster.ray.intersectPlane(dragState.plane, nextPoint)) {
    return true;
  }
  const delta = nextPoint.clone().sub(dragState.previousPoint);
  if (delta.lengthSq() < 0.000001) {
    return true;
  }
  if (!dragState.historyRecorded) {
    recordHistory();
    dragState.historyRecorded = true;
  }
  const movingIds = new Set(dragState.candidateIds);
  candidates.value = candidates.value.map((candidate) =>
    movingIds.has(candidate.candidate_id)
      ? {
          ...candidate,
          x: candidate.x + delta.x,
          y: candidate.y + delta.y,
          z: candidate.z + delta.z,
        }
      : candidate
  );
  dragState.previousPoint = nextPoint;
  sceneMessage.value = `已移动候选点组: ${dragState.candidateIds.length} 个方向`;
  return true;
}

function finishGroupDrag() {
  if (!dragState) {
    return false;
  }
  dragState = null;
  if (controls) {
    controls.enabled = true;
  }
  return true;
}

function handlePointerDown(event: MouseEvent) {
  if (!renderer || !camera || !updatePointer(event)) {
    return;
  }
  if (interactionMode.value === "box") {
    controls!.enabled = false;
    boxSelecting.value = true;
    boxStart = { x: event.offsetX, y: event.offsetY };
    boxSelectionStyle.value = { left: `${event.offsetX}px`, top: `${event.offsetY}px`, width: "0px", height: "0px" };
    return;
  }
  if (interactionMode.value === "select") {
    const hit = pickCandidateVisual(event);
    if (hit?.pickKind === "group") {
      beginGroupDrag(hit, event);
    }
  }
}

function handlePointerMove(event: MouseEvent) {
  if (updateGroupDrag(event)) {
    return;
  }
  if (!boxSelecting.value || !boxStart) {
    return;
  }
  const left = Math.min(boxStart.x, event.offsetX);
  const top = Math.min(boxStart.y, event.offsetY);
  const width = Math.abs(event.offsetX - boxStart.x);
  const height = Math.abs(event.offsetY - boxStart.y);
  boxSelectionStyle.value = { left: `${left}px`, top: `${top}px`, width: `${width}px`, height: `${height}px` };
}

function handlePointerUp(event: MouseEvent) {
  if (finishGroupDrag()) {
    return;
  }
  if (!renderer || !camera || !updatePointer(event)) {
    return;
  }
  if (interactionMode.value === "box" && boxSelecting.value) {
    finishBoxSelection(event);
    return;
  }
  if (interactionMode.value === "add") {
    raycaster.setFromCamera(pointer, camera);
    const point = new THREE.Vector3();
    if (raycaster.ray.intersectPlane(groundPlane, point)) {
      addManualCandidate(point);
    }
    return;
  }
  const hit = pickCandidateVisual(event);
  if (hit?.pickKind === "group") {
    const ids = hit.candidateIds ?? [];
    selectCandidateGroup(ids, event.ctrlKey || event.shiftKey);
    return;
  }
  const hitId = hit?.candidateId;
  if (Number.isFinite(hitId)) {
    selectCandidate(Number(hitId), event.ctrlKey || event.shiftKey);
  }
}

function handlePointerLeave() {
  if (boxSelecting.value) {
    boxSelecting.value = false;
    boxStart = null;
    if (controls) {
      controls.enabled = true;
    }
  }
  finishGroupDrag();
}

function finishBoxSelection(event: MouseEvent) {
  controls!.enabled = true;
  boxSelecting.value = false;
  if (!boxStart || !camera || !renderer) {
    boxStart = null;
    return;
  }
  const bounds = renderer.domElement.getBoundingClientRect();
  const left = Math.min(boxStart.x, event.offsetX);
  const right = Math.max(boxStart.x, event.offsetX);
  const top = Math.min(boxStart.y, event.offsetY);
  const bottom = Math.max(boxStart.y, event.offsetY);
  const projected = new THREE.Vector3();
  const selected = candidates.value
    .filter((candidate) => {
      projected.set(candidate.x, candidate.y, candidate.z).project(camera!);
      const x = ((projected.x + 1) / 2) * bounds.width;
      const y = ((-projected.y + 1) / 2) * bounds.height;
      return x >= left && x <= right && y >= top && y <= bottom;
    })
    .map((candidate) => candidate.candidate_id);
  selectedIds.value = selected;
  sceneMessage.value = `框选候选点: ${selected.length} 个`;
  boxStart = null;
}

function addDeletionRegionFromSelection() {
  const selected = selectedCandidates.value;
  if (!selected.length) {
    return;
  }
  recordHistory();
  const xs = selected.map((item) => item.x);
  const ys = selected.map((item) => item.y);
  deletionRegions.value = [
    ...deletionRegions.value,
    {
      label: `region_${deletionRegions.value.length + 1}`,
      min_x: Math.min(...xs),
      max_x: Math.max(...xs),
      min_y: Math.min(...ys),
      max_y: Math.max(...ys),
    },
  ];
}

function candidateToCsvRow(candidate: CandidatePoint) {
  return [
    candidate.candidate_id,
    candidate.x,
    candidate.y,
    candidate.z,
    candidate.roll_deg,
    candidate.pitch_deg,
    0.0,
    candidate.qx,
    candidate.qy,
    candidate.qz,
    candidate.qw,
    candidate.observability_score,
    candidate.hit_count,
    candidate.hit_ratio,
    candidate.visible_sector_count,
    candidate.descriptor_nonzero_ratio,
    candidate.source,
    candidate.label,
    candidate.locked,
    candidate.original_candidate_id,
    candidate.z_frame || (candidate.source === "manual_added" ? "ground" : "base_link"),
  ].join(",");
}

function refreshExportPreview() {
  const header = "place_id,x,y,z,roll_deg,pitch_deg,canonical_yaw_deg,qx,qy,qz,qw,observability_score,hit_count,hit_ratio,visible_sector_count,descriptor_nonzero_ratio,source,label,locked,original_candidate_id,z_frame";
  exportPreview.value = [header, ...sortedFinalCandidates().map(candidateToCsvRow)].join("\n");
}

function buildManualAdditions() {
  const groups = new Map<string, CandidatePoint[]>();
  sortedFinalCandidates()
    .filter((candidate) => candidate.source === "manual_added")
    .forEach((candidate) => {
      const key = `${normalizeSortCoordinate(candidate.x)}:${normalizeSortCoordinate(candidate.y)}:${normalizeSortCoordinate(candidate.z)}`;
      groups.set(key, [...(groups.get(key) ?? []), candidate]);
    });
  return Array.from(groups.values()).map((group) => {
    const first = group[0];
    const yawValues = Array.from(new Set(group.map((candidate) => Number(candidate.yaw_deg.toFixed(6))))).sort((left, right) => left - right);
    return {
      label: first.label || `manual_${first.candidate_id}`,
      x: first.x,
      y: first.y,
      z: first.z_auto ? null : first.z,
      roll_deg: first.roll_deg,
      pitch_deg: first.pitch_deg,
      yaw_deg: yawValues[0] ?? first.yaw_deg,
      yaw_expand_deg: yawValues,
      locked: group.some((candidate) => candidate.locked),
      note: first.note || "前端人工补点。",
    };
  });
}

function buildManualExportPayload(includeCandidates: boolean) {
  const deletedAutoIds = deletedCandidates.value
    .filter((candidate) => candidate.source === "auto")
    .map((candidate) => candidate.original_candidate_id);
  const payload: Record<string, unknown> = {
    output_dir: formValues.output_dir,
    frame_id: formValues.fixed_frame || "map",
    base_frame: formValues.base_frame || "base_link",
    config: configPayload.value,
    manual_edit: configPayload.value.manual_edit,
    additions: buildManualAdditions(),
    deletions: {
      candidate_ids: deletedAutoIds,
      regions: deletionRegions.value,
    },
    locked_candidate_ids: candidates.value.filter((candidate) => candidate.locked && candidate.source === "auto").map((candidate) => candidate.original_candidate_id),
  };
  if (includeCandidates) {
    payload.candidates = sortedFinalCandidates();
  }
  return payload;
}

async function exportManualEditFile() {
  if (!formValues.output_dir?.trim()) {
    sceneMessage.value = "请先选择输出目录。";
    return;
  }
  refreshExportPreview();
  try {
    const response = await exportGlobalRelocalizationManual(buildManualExportPayload(true));
    formValues.manual_file = response.manual_path;
    exportMessage.value = `已导出 ${response.manual_path}，候选预览 ${response.reviewed_csv_path}`;
    sceneMessage.value = "manual_candidates.yaml 已导出，并已填入人工编辑文件。";
  } catch (error) {
    exportMessage.value = `导出失败: ${(error as Error).message}`;
  }
}

async function openOutputDir() {
  if (!formValues.output_dir?.trim()) {
    return;
  }
  try {
    await openLocalPath(formValues.output_dir);
  } catch (error) {
    sceneMessage.value = `打开目录失败: ${(error as Error).message}`;
  }
}

async function runScaffold() {
  let finalCandidatesJson = "";
  let candidateFileForRun = "";
  if (candidates.value.length > 0) {
    if (!formValues.output_dir?.trim()) {
      sceneMessage.value = "请先选择输出目录。";
      return;
    }
    refreshExportPreview();
    try {
      const manualResponse = await exportGlobalRelocalizationManual(buildManualExportPayload(true));
      formValues.manual_file = manualResponse.manual_path;
      finalCandidatesJson = JSON.stringify(sortedFinalCandidates());
      candidateFileForRun = manualResponse.reviewed_csv_path;
      exportMessage.value = `已导出 ${manualResponse.manual_path}，即将按当前界面候选点写最终库。`;
    } catch (error) {
      exportMessage.value = `运行前导出人工编辑失败: ${(error as Error).message}`;
      return;
    }
  } else {
    formValues.manual_file = "";
    exportMessage.value = "当前没有已加载候选点，将直接从 PCD 自动生成 v2 离线库。";
  }
  emit("run", {
    input_pcd: formValues.input_pcd,
    candidate_file: candidateFileForRun,
    output_dir: formValues.output_dir,
    config_path: formValues.config_path,
    manual_file: formValues.manual_file,
    target_base_positions: configValues["candidate_sampling.target_base_positions"],
    max_base_samples: configValues["candidate_sampling.max_base_samples"],
    min_candidate_distance_m: configValues["candidate_sampling.min_candidate_distance_m"],
    yaw_step_deg: configValues["candidate_sampling.yaw_step_deg"],
    config_json: JSON.stringify(configPayload.value),
    final_candidates_json: finalCandidatesJson,
    active_candidates: String(candidates.value.length),
    manual_additions: String(manualCandidateCount.value),
    deleted_candidates: deletedCandidates.value.map((item) => item.original_candidate_id).join(","),
    locked_candidates: candidates.value.filter((item) => item.locked).map((item) => item.original_candidate_id).join(","),
  });
}

function handleEditorKeydown(event: KeyboardEvent) {
  const target = event.target as HTMLElement | null;
  const tagName = target?.tagName?.toLowerCase();
  if (tagName === "input" || tagName === "textarea" || tagName === "select" || target?.isContentEditable) {
    return;
  }
  if (!event.ctrlKey) {
    return;
  }
  const key = event.key.toLowerCase();
  if (key === "z") {
    event.preventDefault();
    undoEdit();
  } else if (key === "y") {
    event.preventDefault();
    redoEdit();
  }
}

watch([candidates, selectedIds], () => renderCandidates(), { deep: true });

watch(
  () => props.tool,
  () => initializeFormValues(),
  { immediate: true }
);

onMounted(() => {
  initializeScene();
  resizeObserver = new ResizeObserver(() => fitRendererSize());
  if (mountRef.value) {
    resizeObserver.observe(mountRef.value);
  }
  renderer?.domElement.addEventListener("mousedown", handlePointerDown);
  renderer?.domElement.addEventListener("mousemove", handlePointerMove);
  renderer?.domElement.addEventListener("mouseup", handlePointerUp);
  renderer?.domElement.addEventListener("mouseleave", handlePointerLeave);
  window.addEventListener("keydown", handleEditorKeydown);
});

onBeforeUnmount(() => {
  renderer?.domElement.removeEventListener("mousedown", handlePointerDown);
  renderer?.domElement.removeEventListener("mousemove", handlePointerMove);
  renderer?.domElement.removeEventListener("mouseup", handlePointerUp);
  renderer?.domElement.removeEventListener("mouseleave", handlePointerLeave);
  window.removeEventListener("keydown", handleEditorKeydown);
  teardownScene();
});
</script>

<template>
  <section class="panel global-relocalization-toolbar">
    <div class="section-head">
      <div>
        <div class="result-title">Scan Context 全局重定位候选点</div>
        <div class="section-subtitle">仅依赖 3D PCD；人工编辑导出为 manual_candidates.yaml，最终 descriptor/ring key 由离线工具重算。</div>
      </div>
      <div class="status-pill">{{ loading ? "运行中" : "审核态" }}</div>
    </div>

    <div class="global-relocalization-path-grid">
      <label class="field">
        <span class="field-label">输入 PCD</span>
        <div class="field-row">
          <input v-model="formValues.input_pcd" class="field-input" placeholder="G:/path/map.pcd" />
          <button class="field-browse-btn" type="button" @click="browseField('input_pcd', 'open_file')">选择</button>
          <button class="secondary-btn small" type="button" @click="loadPointCloudFromPath">加载点云</button>
        </div>
      </label>
      <label class="field">
        <span class="field-label">候选点文件</span>
        <div class="field-row">
          <input v-model="formValues.candidate_file" class="field-input" placeholder="global_relocalization_db/candidates.csv 或 candidates.npy" />
          <button class="field-browse-btn" type="button" @click="browseField('candidate_file', 'open_file')">选择</button>
          <button class="secondary-btn small" type="button" @click="loadCandidatesFromPath">加载候选</button>
        </div>
      </label>
      <label class="field">
        <span class="field-label">人工编辑文件</span>
        <div class="field-row">
          <input v-model="formValues.manual_file" class="field-input" placeholder="global_relocalization_db/manual_candidates.yaml" />
          <button class="field-browse-btn" type="button" @click="browseField('manual_file', 'open_file')">选择</button>
        </div>
      </label>
      <label class="field">
        <span class="field-label">输出目录</span>
        <div class="field-row">
          <input v-model="formValues.output_dir" class="field-input" placeholder="global_relocalization_db" />
          <button class="field-browse-btn" type="button" @click="browseField('output_dir', 'open_dir')">选择</button>
          <button class="secondary-btn small" type="button" @click="openOutputDir">打开</button>
        </div>
      </label>
    </div>

    <div class="global-relocalization-controls">
      <input v-model="manualLabel" class="field-input compact-input" placeholder="人工点 label" />
      <input v-model="manualYawDeg" class="field-input compact-input" placeholder="yaw_deg" />
      <input v-model="manualYawExpand" class="field-input compact-input" placeholder="yaw_expand_deg" />
      <label class="inline-check">
        <input v-model="manualUseAutoZ" type="checkbox" />
        <span>z 自动估计</span>
      </label>
      <input v-if="!manualUseAutoZ" v-model="manualZ" class="field-input compact-input" placeholder="ground z" />
      <button class="secondary-btn" type="button" @click="refreshExportPreview">刷新 CSV 预览</button>
      <button class="secondary-btn" type="button" @click="exportManualEditFile">导出人工编辑文件</button>
      <button class="primary-btn" type="button" :disabled="loading" @click="runScaffold">{{ tool.primary_action }}</button>
      <button class="secondary-btn" type="button" @click="emit('clearLogs')">清空日志</button>
    </div>
  </section>

  <section class="panel global-relocalization-config-panel">
    <div class="section-head">
      <div>
        <div class="result-title">离线生成参数草案</div>
        <div class="section-subtitle">字段覆盖 MD 中 map / candidate_sampling / virtual_lidar / observability / descriptor / manual_edit 配置。</div>
      </div>
    </div>
    <div class="config-section-grid">
      <section v-for="section in configSections" :key="section" class="config-section">
        <div class="config-section-title">{{ section }}</div>
        <label v-for="field in configFields.filter((item) => item.section === section)" :key="configKey(field)" class="field compact-field">
          <span class="field-label config-field-label">
            <span>{{ field.label }}</span>
            <span class="param-help-icon" :title="field.help">!</span>
          </span>
          <input v-model="configValues[configKey(field)]" class="field-input" />
        </label>
      </section>
    </div>
  </section>

  <section class="panel global-relocalization-view-panel">
    <div class="global-relocalization-stage">
      <div ref="mountRef" class="global-relocalization-canvas-host"></div>
      <div v-if="boxSelecting" class="box-selection-rect" :style="boxSelectionStyle"></div>
      <div class="viewer-left-tools" aria-label="候选点编辑工具">
        <button class="viewer-side-button" :class="{ active: interactionMode === 'select' }" type="button" title="点击选择候选点" @click="interactionMode = 'select'">S</button>
        <button class="viewer-side-button" :class="{ active: interactionMode === 'box' }" type="button" title="框选候选点" @click="interactionMode = 'box'">B</button>
        <button class="viewer-side-button" :class="{ active: interactionMode === 'add' }" type="button" title="手动加点：点击三维平面新增人工候选点" @click="interactionMode = 'add'">+</button>
        <button class="viewer-side-button danger" type="button" title="删除选中点：按 candidate_id 写入删除列表" :disabled="selectedIds.length === 0" @click="deleteSelectedCandidates">D</button>
        <button class="viewer-side-button" type="button" title="锁定保留：后续自动清理或稀疏化时优先保留" :disabled="selectedIds.length === 0" @click="toggleSelectedLocked">L</button>
        <button class="viewer-side-button warning" type="button" title="设为禁用区域：用选中点外包矩形创建区域删除规则" :disabled="selectedIds.length === 0" @click="addDeletionRegionFromSelection">R</button>
      </div>
      <div class="viewer-corner-tools">
        <div class="history-tool-strip">
          <button class="viewer-tool-button" type="button" title="撤销 Ctrl+Z" :disabled="!canUndo" @click="undoEdit">↶</button>
          <button class="viewer-tool-button" type="button" title="重做 Ctrl+Y" :disabled="!canRedo" @click="redoEdit">↷</button>
        </div>
        <div class="axis-gizmo" aria-label="视图轴向控制">
          <button class="axis-button axis-z" type="button" title="顶视图 Z" @click="setAxisView('z')">Z</button>
          <button class="axis-button axis-y" type="button" title="前视图 Y" @click="setAxisView('y')">Y</button>
          <button class="axis-button axis-x" type="button" title="侧视图 X" @click="setAxisView('x')">X</button>
          <button class="axis-button axis-home" type="button" title="透视视图" @click="setAxisView('home')">⌂</button>
          <span class="axis-line axis-line-z"></span>
          <span class="axis-line axis-line-y"></span>
          <span class="axis-line axis-line-x"></span>
        </div>
      </div>
    </div>
    <div class="nav-viewer-footer">
      <span class="nav-viewer-status">{{ sceneMessage }}</span>
      <span class="nav-viewer-status">候选 {{ activeCandidateCount }}</span>
      <span class="nav-viewer-status">人工 {{ manualCandidateCount }}</span>
      <span class="nav-viewer-status">锁定 {{ lockedCandidateCount }}</span>
      <span class="nav-viewer-status">回收站 {{ deletedCandidates.length }}</span>
    </div>
  </section>

  <section class="panel global-relocalization-list-panel">
    <div class="section-head">
      <div>
        <div class="result-title">候选点列表</div>
        <div class="section-subtitle">显示 auto / manual_added / locked 状态和观测质量指标。</div>
      </div>
      <div class="status-pill success">加载 {{ loadedCandidateCount }}</div>
    </div>
    <div class="candidate-list">
      <button
        v-for="candidate in candidates"
        :key="candidate.candidate_id"
        class="candidate-row"
        :class="{ selected: selectedIds.includes(candidate.candidate_id), manual: candidate.source === 'manual_added', locked: candidate.locked }"
        type="button"
        @click="selectCandidate(candidate.candidate_id, true)"
      >
        <span class="candidate-id">#{{ candidate.candidate_id }}</span>
        <span>x {{ candidate.x.toFixed(2) }}</span>
        <span>y {{ candidate.y.toFixed(2) }}</span>
        <span>yaw {{ candidate.yaw_deg.toFixed(1) }}</span>
        <span>{{ candidate.source }}{{ candidate.locked ? " / locked" : "" }}</span>
      </button>
      <div v-if="candidates.length === 0" class="section-empty">加载 candidates.csv 或 candidates.npy 后显示候选点。</div>
    </div>
  </section>

  <section class="panel global-relocalization-selected-panel">
    <div class="section-head">
      <div>
        <div class="result-title">选中点位</div>
        <div class="section-subtitle">可编辑 yaw / z / roll / pitch；人工点支持 yaw_expand_deg。</div>
      </div>
    </div>
    <div class="candidate-detail-list">
      <div v-for="candidate in selectedCandidates" :key="`selected-${candidate.candidate_id}`" class="candidate-detail">
        <strong>#{{ candidate.candidate_id }} {{ candidate.label }}</strong>
        <div class="candidate-edit-grid">
          <label>x<input v-model.number="candidate.x" class="field-input" @focus="beginCandidateFieldEdit" @blur="endCandidateFieldEdit" /></label>
          <label>y<input v-model.number="candidate.y" class="field-input" @focus="beginCandidateFieldEdit" @blur="endCandidateFieldEdit" /></label>
          <label>z<input v-model.number="candidate.z" class="field-input" @focus="beginCandidateFieldEdit" @blur="endCandidateFieldEdit" /></label>
          <label>yaw<input v-model.number="candidate.yaw_deg" class="field-input" @focus="beginCandidateFieldEdit" @blur="endCandidateFieldEdit" /></label>
          <label>roll<input v-model.number="candidate.roll_deg" class="field-input" @focus="beginCandidateFieldEdit" @blur="endCandidateFieldEdit" /></label>
          <label>pitch<input v-model.number="candidate.pitch_deg" class="field-input" @focus="beginCandidateFieldEdit" @blur="endCandidateFieldEdit" /></label>
        </div>
        <div class="candidate-quality">
          score {{ candidate.observability_score.toFixed(3) }} · hit {{ candidate.hit_count }} · ratio {{ candidate.hit_ratio.toFixed(3) }} · sectors {{ candidate.visible_sector_count }} · nonzero {{ candidate.descriptor_nonzero_ratio.toFixed(3) }}
        </div>
      </div>
      <div v-if="selectedCandidates.length === 0" class="section-empty">当前未选择候选点。</div>
    </div>
  </section>

  <section class="panel global-relocalization-trash-panel">
    <div class="section-head">
      <div>
        <div class="result-title">删除规则 / 回收站</div>
        <div class="section-subtitle">删除自动点会写入 deletions.candidate_ids；删除区域会写入 deletions.regions。</div>
      </div>
      <button class="secondary-btn small" type="button" :disabled="deletedCandidates.length === 0" @click="purgeTrash">清空</button>
    </div>
    <div class="candidate-list compact">
      <button v-for="candidate in deletedCandidates" :key="`trash-${candidate.candidate_id}`" class="candidate-row deleted" type="button" @click="restoreCandidate(candidate.candidate_id)">
        <span class="candidate-id">#{{ candidate.candidate_id }}</span>
        <span>x {{ candidate.x.toFixed(2) }}</span>
        <span>y {{ candidate.y.toFixed(2) }}</span>
        <span>{{ candidate.source }}</span>
        <span>恢复</span>
      </button>
      <div v-if="deletedCandidates.length === 0" class="section-empty">回收站为空。</div>
    </div>
    <div class="deletion-region-list">
      <div v-for="region in deletionRegions" :key="region.label" class="candidate-detail">
        <strong>{{ region.label }}</strong>
        <span>x {{ region.min_x.toFixed(2) }} ~ {{ region.max_x.toFixed(2) }} / y {{ region.min_y.toFixed(2) }} ~ {{ region.max_y.toFixed(2) }}</span>
      </div>
    </div>
  </section>

  <section class="panel global-relocalization-export-panel">
    <div class="section-head">
      <div>
        <div class="result-title">导出预览</div>
        <div class="section-subtitle">CSV 预览用于人工检查；最终在线兼容仍由离线工具生成 candidates.npy/descriptors.npy/ring_keys.npy。</div>
      </div>
    </div>
    <pre class="logs export-preview">{{ exportPreview || "点击“刷新 CSV 预览”后显示。" }}</pre>
    <div class="section-subtitle export-message">{{ exportMessage }}</div>
    <pre class="logs manual-yaml-preview">{{ manualYamlPreview }}</pre>
  </section>

  <section class="result-panel global-relocalization-summary-panel">
    <div class="result-title">输出摘要</div>
    <p class="summary">{{ summary }}</p>
  </section>
</template>
