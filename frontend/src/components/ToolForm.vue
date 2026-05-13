<script setup lang="ts">
import { computed, defineAsyncComponent, nextTick, onBeforeUnmount, ref, reactive, watch } from "vue";

import {
  buildBackendImageUrl,
  browsePath,
  deleteNavRecording,
  fetchLocalTextFile,
  fetchNavRecordingFiles,
  fetchRosDataSourceConfig,
  fetchRosTopics,
  fetchMtslashBrowserFavorites,
  fetchMtslashBrowserTabs,
  fetchMtslashCaptcha,
  fetchMtslashFavorites,
  fetchPcdTilePreview,
  inspectRosDataSource,
  loginMtslash,
  openLocalPath,
  saveRosDataSourceConfig,
  startMtslashBrowser,
} from "../api/client";
import type { MtslashBrowserTab, MtslashFavoriteItem } from "../api/client";
import type { BrowseDialogPayload, NavRecordingFileItem, NavRecordingSavePayload, RosInspectionResponse, RosTopicItem, ToolDefinition } from "../types";
import { buildDisplayLabel, inferDisplayKind, type NavViewerDisplay } from "../lib/ros/displayRegistry";
import { createRosLiveAdapter } from "../lib/ros/liveAdapter";

const Nav3DViewer = defineAsyncComponent(() => import("./Nav3DViewer.vue"));
const NavTopicPanelList = defineAsyncComponent(() => import("./NavTopicPanelList.vue"));

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
const tilePreview = ref("");
const networkKeyword = ref("");
const networkMacFilter = ref("");
const networkOnlyAlive = ref(false);
const costmapCanvas = ref<HTMLCanvasElement | null>(null);
const costmapFrameIndex = ref(0);
const costmapPlaying = ref(false);
const mtslashCaptchaImage = ref("");
const mtslashLoginMessage = ref("");
const mtslashCaptchaLoading = ref(false);
const mtslashLoginLoading = ref(false);
const mtslashLoggedIn = ref(false);
const mtslashFavorites = ref<MtslashFavoriteItem[]>([]);
const mtslashFavoritesLoading = ref(false);
const mtslashFavoritesMessage = ref("");
const mtslashFavoritesPage = ref(1);
const mtslashFavoritesKeyword = ref("");
const mtslashBrowserTabs = ref<MtslashBrowserTab[]>([]);
const mtslashBrowserLoading = ref(false);
const mtslashBrowserMessage = ref("");
const mtslashBrowserPage = ref(1);
const mtslashBrowserKeyword = ref("");
const mtslashPageSize = 20;

interface NavTopicOption {
  key: string;
  label: string;
  type: string;
  note: string;
}

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

interface NavRecordingChartHover {
  offsetMs: number;
  value: number;
  x: number;
}

interface SavedNavPanelLayout {
  sidePanels: NavPanelItem[];
  fullPanels: NavPanelItem[];
  mainDisplays: NavViewerDisplay[];
}

function defaultPointCloudColor(topic: string) {
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

const NAV_RECORDING_JSON_BEGIN = "--- NAV_RECORDING_JSON BEGIN ---";
const NAV_RECORDING_JSON_END = "--- NAV_RECORDING_JSON END ---";

const defaultNavTopicOptions: NavTopicOption[] = [
  { key: "/map", label: "二维地图", type: "nav_msgs/OccupancyGrid", note: "Nav2 常用二维栅格地图话题，适合直接叠加到主视图。" },
  { key: "/debug/loaded_pointcloud_map", label: "地图点云", type: "sensor_msgs/msg/PointCloud2", note: "文档推荐优先接入，用于和实时点云做重合验证。" },
  { key: "/points_aligned", label: "对齐结果点云", type: "sensor_msgs/msg/PointCloud2", note: "文档最关键的几何验证话题之一，用来看 NDT 是否真正贴图。" },
  { key: "/cloud_registered_bl", label: "NDT 输入点云", type: "sensor_msgs/msg/PointCloud2", note: "NDT 实际输入点云，适合和 points_aligned 对比。" },
  { key: "/cloud_registered_body", label: "FAST-LIO 输出点云", type: "sensor_msgs/msg/PointCloud2", note: "结构参考点云，也是 scan 链路上游。" },
  { key: "/ndt_pose", label: "NDT 位姿", type: "geometry_msgs/msg/PoseStamped", note: "文档明确推荐优先接入，用于显示定位箭头。" },
  { key: "/odometry/filtered", label: "融合里程计", type: "nav_msgs/msg/Odometry", note: "查看导航运动和位姿连续性。" },
  { key: "/plan", label: "当前路径", type: "nav_msgs/msg/Path", note: "文档建议作为几何验证主视图的常规叠加项。" },
  { key: "/tf", label: "TF 树", type: "tf2_msgs/msg/TFMessage", note: "查看 base_link 与地图坐标系链路。" },
  { key: "/scan", label: "LaserScan", type: "sensor_msgs/msg/LaserScan", note: "文档建议用于查看 Nav2 局部避障输入。" },
  { key: "/ndt_status", label: "NDT 状态", type: "std_msgs/msg/UInt8", note: "0 unknown / 1 healthy / 2 degraded / 3 lost。" },
  { key: "/iteration_num", label: "NDT 迭代数", type: "autoware_internal_debug_msgs/msg/Int32Stamped", note: "判断是否接近失配或吃满迭代。" },
  { key: "/exe_time_ms", label: "NDT 耗时", type: "autoware_internal_debug_msgs/msg/Float32Stamped", note: "判断环境复杂度和性能抖动。" },
  { key: "/ndt_score", label: "NDT 评分", type: "std_msgs/msg/Float32", note: "适合趋势显示和失配预警。" },
  { key: "/fastlio_ndt_observation_debug", label: "NDT 观测调试", type: "std_msgs/msg/String", note: "字符串 JSON，重点看 sigma_xy_m / sigma_yaw_deg / planar_dist_before_m / z_err_before_m。" },
  { key: "/nav2_status", label: "Nav2 状态汇总", type: "std_msgs/msg/String", note: "字符串 JSON，总状态看板核心话题。" },
  { key: "/nav2_goal_context", label: "导航任务上下文", type: "std_msgs/msg/String", note: "字符串 JSON，适合看 active / paused / request_planid。" },
  { key: "/cmd_vel", label: "控制输出", type: "geometry_msgs/msg/Twist", note: "判断 Nav2 是否真的在输出控制指令。" },
];

function createDefaultNavSidePanels(): NavPanelItem[] {
  return [
    {
      id: "panel-ndt-status",
      title: "NDT 状态窗",
      topic: "/ndt_status",
      type: "状态卡片",
      messageType: "std_msgs/msg/UInt8",
      collapsed: false,
      paused: false,
    },
    {
      id: "panel-ndt-iter",
      title: "NDT 迭代数窗",
      topic: "/iteration_num",
      type: "诊断卡片",
      messageType: "autoware_internal_debug_msgs/msg/Int32Stamped",
      collapsed: false,
      paused: false,
    },
    {
      id: "panel-ndt-delay",
      title: "NDT 耗时窗",
      topic: "/exe_time_ms",
      type: "诊断卡片",
      messageType: "autoware_internal_debug_msgs/msg/Float32Stamped",
      collapsed: false,
      paused: false,
    },
    {
      id: "panel-ndt-score",
      title: "NDT 评分窗",
      topic: "/ndt_score",
      type: "诊断卡片",
      messageType: "std_msgs/msg/Float32",
      collapsed: false,
      paused: false,
    },
    {
      id: "panel-nav2-status",
      title: "Nav2 状态窗",
      topic: "/nav2_status",
      type: "状态卡片",
      messageType: "std_msgs/msg/String",
      collapsed: false,
      paused: false,
    },
    {
      id: "panel-nav2-context",
      title: "任务上下文窗",
      topic: "/nav2_goal_context",
      type: "状态卡片",
      messageType: "std_msgs/msg/String",
      collapsed: true,
      paused: true,
    },
    {
      id: "panel-ndt-observation",
      title: "NDT 观测窗",
      topic: "/fastlio_ndt_observation_debug",
      type: "日志卡片",
      messageType: "std_msgs/msg/String",
      collapsed: false,
      paused: false,
    },
  ];
}

function createDefaultNavFullPanels(): NavPanelItem[] {
  return [
    {
      id: "full-panel-ndt-status",
      title: "NDT 状态窗",
      topic: "/ndt_status",
      type: "状态卡片",
      messageType: "std_msgs/msg/UInt8",
      collapsed: false,
      paused: false,
    },
    {
      id: "full-panel-ndt-iter",
      title: "NDT 迭代数窗",
      topic: "/iteration_num",
      type: "诊断卡片",
      messageType: "autoware_internal_debug_msgs/msg/Int32Stamped",
      collapsed: false,
      paused: false,
    },
    {
      id: "full-panel-ndt-score",
      title: "NDT 评分窗",
      topic: "/ndt_score",
      type: "诊断卡片",
      messageType: "std_msgs/msg/Float32",
      collapsed: false,
      paused: false,
    },
  ];
}

const selectedNavTopics = ref<string[]>([]);
const navSidePanels = ref<NavPanelItem[]>(createDefaultNavSidePanels());
const navFullPanels = ref<NavPanelItem[]>(createDefaultNavFullPanels());
const navMainDisplays = ref<NavViewerDisplay[]>([]);
const rosInspectLoading = ref(false);
const rosTopicsLoading = ref(false);
const rosDataSourceSaving = ref(false);
const rosTopicQuery = ref("");
const rosTopicOptions = ref<NavTopicOption[]>(defaultNavTopicOptions);
const rosInspectResult = ref<RosInspectionResponse | null>(null);
const rosTopicsMessage = ref("");
const navDisplayManagerCollapsed = ref(false);
const navTfFrameOptions = ref<Record<string, string[]>>({});
const navRecordingFiles = ref<NavRecordingFileItem[]>([]);
const navRecordingFilesDirectory = ref("");
const navRecordingFilesLoading = ref(false);
const navRecordingFilesMessage = ref("");
const navRecordingPreviewPath = ref("");
const navRecordingPreviewText = ref("");
const navRecordingPreviewKind = ref<"text" | "image" | "">("");
const navRecordingParsedPayload = ref<NavRecordingSavePayload | null>(null);
const navRecordingChartMetricLabel = ref("");
const navRecordingChartRangeStart = ref(0);
const navRecordingChartRangeEnd = ref(1);
const navRecordingChartDragging = ref(false);
const navRecordingChartHover = ref<NavRecordingChartHover | null>(null);
let navRecordingChartDragAnchorX = 0;
let navRecordingChartDragRangeStart = 0;
let navRecordingChartDragRangeEnd = 1;
const navInteractionMode = ref<"none" | "initialpose" | "navgoal">("none");
const navControlLoading = ref(false);
const navControlMessage = ref("");
const navGoalSequence = ref(1);
let costmapTimer: number | undefined;

watch(
  () => props.tool,
  (tool) => {
    Object.keys(formValues).forEach((key) => delete formValues[key]);
    tool.fields.forEach((field) => {
      formValues[field.key] = field.value ?? "";
    });
    hydrateMtslashCachedFields(tool.key);
    tilePreview.value = "";
    mtslashCaptchaImage.value = "";
    mtslashLoginMessage.value = "";
    mtslashLoggedIn.value = false;
    mtslashFavorites.value = [];
    mtslashFavoritesMessage.value = "";
    mtslashFavoritesPage.value = 1;
    mtslashFavoritesKeyword.value = "";
    mtslashBrowserTabs.value = [];
    mtslashBrowserMessage.value = "";
    mtslashBrowserPage.value = 1;
    mtslashBrowserKeyword.value = "";
    selectedNavTopics.value = [];
    navSidePanels.value = createDefaultNavSidePanels();
    navFullPanels.value = createDefaultNavFullPanels();
    navMainDisplays.value = [];
    rosInspectResult.value = null;
    rosTopicsMessage.value = "";
    rosTopicQuery.value = "";
    rosTopicOptions.value = defaultNavTopicOptions;
    navDisplayManagerCollapsed.value = false;
    navTfFrameOptions.value = {};
    navRecordingFiles.value = [];
    navRecordingFilesDirectory.value = "";
    navRecordingFilesMessage.value = "";
    navRecordingPreviewPath.value = "";
    navRecordingPreviewText.value = "";
    navRecordingPreviewKind.value = "";
    navInteractionMode.value = "none";
    navControlMessage.value = "";
    if (tool.key === "ros_nav_test") {
      void loadRosDataSourceConfigForNav();
      void loadNavRecordingFiles();
    }
    stopCostmapPlayback();
    costmapFrameIndex.value = 0;
  },
  { immediate: true }
);

watch(
  () => [formValues.output_dir, formValues.login_username, formValues.login_password],
  () => {
    if (props.tool.key !== "mtslash_export") {
      return;
    }
    persistMtslashCachedFields();
  }
);

watch(
  () => formValues.input_pcd,
  (value) => {
    if (props.tool.key !== "pcd_tile") {
      return;
    }
    const currentOutput = formValues.output_dir ?? "";
    const suggested = buildDefaultTileOutputDir(value ?? "");
    if (!value || !suggested) {
      return;
    }
    if (!currentOutput || currentOutput === buildDefaultTileOutputDir(currentOutput.replace(/_tiles$/, ".pcd"))) {
      formValues.output_dir = suggested;
      return;
    }
    if (currentOutput.endsWith("_tiles")) {
      formValues.output_dir = suggested;
    }
  }
);

const parsedPairs = computed(() => {
  const pairs: Record<string, string> = {};
  props.logs.forEach((line) => {
    const normalized = line.replace(/^\[STDOUT\]\s*/, "");
    const index = normalized.indexOf(": ");
    if (index > 0) {
      const key = normalized.slice(0, index).trim();
      const value = normalized.slice(index + 2).trim();
      pairs[key] = value;
    }
  });
  return pairs;
});

const networkRows = computed(() =>
  (props.resultData.rows ?? []).map((row: Record<string, string>) => ({
    ip: row.ip ?? "",
    status: row.status ?? "",
    latency: row.latency ?? "",
    hostname: row.hostname ?? "",
    mac: row.mac ?? "",
    arp_type: row.arp_type ?? "",
    port_22: row.port_22 ?? "",
    note: row.note ?? "",
  }))
);

const filteredNetworkRows = computed(() =>
  networkRows.value.filter((row) => {
    if (networkOnlyAlive.value && row.status !== "在线") {
      return false;
    }
    if (networkMacFilter.value.trim() && !row.mac.toLowerCase().includes(networkMacFilter.value.trim().toLowerCase())) {
      return false;
    }
    if (networkKeyword.value.trim()) {
      const merged = [row.ip, row.status, row.latency, row.hostname, row.mac, row.arp_type, row.port_22, row.note].join(" ").toLowerCase();
      if (!merged.includes(networkKeyword.value.trim().toLowerCase())) {
        return false;
      }
    }
    return true;
  })
);

const pcdMapImageUrl = computed(() => {
  const path = props.resultData.preview_path || props.resultData.color_path;
  if (!path) {
    return "";
  }
  return buildBackendImageUrl(String(path), String(props.resultData.generated_at || ""));
});

const selectedNavTopicOptions = computed(() =>
  rosTopicOptions.value.filter((item) => selectedNavTopics.value.includes(item.key))
);

const navActiveSidePanelCount = computed(() => navSidePanels.value.filter((panel) => !panel.paused).length);
const navActiveFullPanelCount = computed(() => navFullPanels.value.filter((panel) => !panel.paused).length);
const navDisplayManagerLabel = computed(() =>
  navDisplayManagerCollapsed.value ? `展开显示项管理 (${navMainDisplays.value.length})` : `收起显示项管理 (${navMainDisplays.value.length})`
);
const filteredRosTopicOptions = computed(() => {
  const keyword = rosTopicQuery.value.trim().toLowerCase();
  if (!keyword) {
    return rosTopicOptions.value;
  }
  return rosTopicOptions.value.filter((item) => `${item.key} ${item.label} ${item.type} ${item.note}`.toLowerCase().includes(keyword));
});

const mtslashFavoriteTotalPages = computed(() => Math.max(1, Math.ceil(mtslashFavorites.value.length / mtslashPageSize)));
const filteredMtslashFavorites = computed(() => {
  const keyword = mtslashFavoritesKeyword.value.trim().toLowerCase();
  if (!keyword) {
    return mtslashFavorites.value;
  }
  return mtslashFavorites.value.filter((item) => `${item.title} ${item.url}`.toLowerCase().includes(keyword));
});
const filteredMtslashFavoriteTotalPages = computed(() => Math.max(1, Math.ceil(filteredMtslashFavorites.value.length / mtslashPageSize)));
const pagedMtslashFavorites = computed(() => {
  const safePage = Math.min(Math.max(1, mtslashFavoritesPage.value), filteredMtslashFavoriteTotalPages.value);
  const start = (safePage - 1) * mtslashPageSize;
  return filteredMtslashFavorites.value.slice(start, start + mtslashPageSize);
});
const filteredMtslashBrowserTabs = computed(() => {
  const keyword = mtslashBrowserKeyword.value.trim().toLowerCase();
  if (!keyword) {
    return mtslashBrowserTabs.value;
  }
  return mtslashBrowserTabs.value.filter((item) => `${item.title} ${item.url}`.toLowerCase().includes(keyword));
});
const filteredMtslashBrowserTotalPages = computed(() => Math.max(1, Math.ceil(filteredMtslashBrowserTabs.value.length / mtslashPageSize)));
const pagedMtslashBrowserTabs = computed(() => {
  const safePage = Math.min(Math.max(1, mtslashBrowserPage.value), filteredMtslashBrowserTotalPages.value);
  const start = (safePage - 1) * mtslashPageSize;
  return filteredMtslashBrowserTabs.value.slice(start, start + mtslashPageSize);
});
const mtslashExportModeLabel = computed(() =>
  String(formValues.browser_mode ?? "false").toLowerCase() === "true" ? `浏览器模式 / ${formValues.browser_type || "edge"}` : "直连/登录会话模式"
);
const mtslashProgressText = computed(() => {
  if (props.loading) {
    return `正在导出: ${formValues.thread_url || "等待帖子 URL"}`;
  }
  return props.summary || "等待导出任务";
});

watch(mtslashFavoritesKeyword, () => {
  mtslashFavoritesPage.value = 1;
});

watch(mtslashBrowserKeyword, () => {
  mtslashBrowserPage.value = 1;
});

const costmapFrames = computed(() => props.resultData.frames ?? []);
const currentCostmapFrame = computed(() => {
  if (costmapFrames.value.length === 0) {
    return null;
  }
  const index = Math.max(0, Math.min(costmapFrameIndex.value, costmapFrames.value.length - 1));
  return costmapFrames.value[index] ?? null;
});

const costmapThreshold = computed(() => parseFloat(formValues.threshold || `${props.resultData.threshold || 99}`) || 99);
const costmapFps = computed(() => Math.max(0.1, parseFloat(formValues.fps || `${props.resultData.fps || 2}`) || 2));
const costmapShowLethal = computed(() => String(formValues.show_lethal ?? "true").toLowerCase() === "true");
const costmapShowFootprint = computed(() => String(formValues.show_footprint ?? "true").toLowerCase() === "true");
const costmapFootprintLength = computed(() => Math.max(0.01, parseFloat(formValues.footprint_length || `${props.resultData.footprint_length || 0.7}`) || 0.7));
const costmapFootprintWidth = computed(() => Math.max(0.01, parseFloat(formValues.footprint_width || `${props.resultData.footprint_width || 0.4}`) || 0.4));
const costmapFrameInfo = computed(() => {
  const frame = currentCostmapFrame.value;
  if (!frame) {
    return "加载 Costmap 后将在这里显示当前帧信息。";
  }
  const stamp = `${frame.stamp_sec ?? 0}.${String(frame.stamp_nanosec ?? 0).padStart(9, "0")}`;
  const values = frame.preview_pixels ?? [];
  const lethal = values.filter((value: number) => value >= costmapThreshold.value).length;
  return [
    `frame_id: ${frame.frame_id || "-"}`,
    `stamp: ${stamp}`,
    `帧序号: ${(frame.index ?? costmapFrameIndex.value) + 1} / ${costmapFrames.value.length}`,
    `原始尺寸: ${frame.width} x ${frame.height}`,
    `预览尺寸: ${frame.preview_width} x ${frame.preview_height}`,
    `resolution: ${Number(frame.resolution ?? 0).toFixed(3)} m/cell`,
    `origin: (${Number(frame.origin_x ?? 0).toFixed(3)}, ${Number(frame.origin_y ?? 0).toFixed(3)})`,
    `非零单元: ${frame.nonzero ?? 0}`,
    `Lethal 单元(预览): ${lethal}`,
    `Footprint: ${costmapFootprintLength.value.toFixed(2)} x ${costmapFootprintWidth.value.toFixed(2)} m`,
  ].join("\n");
});

function submit() {
  if (props.tool.key === "mtslash_export") {
    persistMtslashCachedFields();
  }
  emit("run", { ...formValues });
}

function defaultMtslashOutputDir() {
  const root = localStorage.getItem("moontoolbox.appRoot") || "";
  return root ? `${root.replace(/\\/g, "/")}/output` : "output";
}

function hydrateMtslashCachedFields(toolKey: string) {
  if (toolKey !== "mtslash_export") {
    return;
  }
  formValues.output_dir = localStorage.getItem("mtslash.outputDir") || formValues.output_dir || defaultMtslashOutputDir();
  formValues.login_username = localStorage.getItem("mtslash.loginUsername") || formValues.login_username || "";
  formValues.login_password = localStorage.getItem("mtslash.loginPassword") || formValues.login_password || "";
}

function persistMtslashCachedFields() {
  if (formValues.output_dir?.trim()) {
    localStorage.setItem("mtslash.outputDir", formValues.output_dir.trim());
  }
  localStorage.setItem("mtslash.loginUsername", formValues.login_username || "");
  localStorage.setItem("mtslash.loginPassword", formValues.login_password || "");
}

function getBrowseMode(fieldKey: string, fieldLabel: string): BrowseDialogPayload["mode"] | null {
  const key = fieldKey.toLowerCase();
  const label = fieldLabel.toLowerCase();
  if (key.includes("output_dir") || key.endsWith("_dir") || label.includes("output dir") || label.includes("directory") || label.includes("输出目录")) {
    return "open_dir";
  }
  if (key.includes("input") || key.includes("path") || key.includes("pcd") || key.includes("yaml")) {
    return "open_file";
  }
  if (key.includes("output") && key.includes("path")) {
    return "save_file";
  }
  return null;
}

function buildDefaultTileOutputDir(path: string) {
  if (!path) {
    return "";
  }
  const normalized = path.replace(/\\/g, "/");
  const lastSlash = normalized.lastIndexOf("/");
  const dir = lastSlash >= 0 ? normalized.slice(0, lastSlash) : "";
  const fileName = lastSlash >= 0 ? normalized.slice(lastSlash + 1) : normalized;
  const stem = fileName.replace(/\.[^.]+$/, "");
  if (!stem) {
    return "";
  }
  return `${dir}/${stem}_tiles`;
}

async function browseField(fieldKey: string, fieldLabel: string) {
  const mode = getBrowseMode(fieldKey, fieldLabel);
  if (!mode) {
    return;
  }
  try {
    const path = await browsePath({
      mode,
      title: `选择${fieldLabel}`,
      initial_path: formValues[fieldKey] ?? "",
    });
    if (path) {
      formValues[fieldKey] = path;
      if (props.tool.key === "mtslash_export" && fieldKey === "output_dir") {
        localStorage.setItem("mtslash.outputDir", path);
      }
    }
  } catch {
    // Ignore dialog failures to keep manual input usable.
  }
}

async function previewTile() {
  if (!formValues.input_pcd?.trim()) {
    tilePreview.value = "请先选择输入 PCD。";
    return;
  }
  try {
    const result = await fetchPcdTilePreview(formValues.input_pcd, formValues.tile_size || "20.0");
    tilePreview.value = [
      `点数: ${result.point_count}`,
      `X 范围: ${result.xmin.toFixed(3)} ~ ${result.xmax.toFixed(3)}`,
      `Y 范围: ${result.ymin.toFixed(3)} ~ ${result.ymax.toFixed(3)}`,
      `Z 范围: ${result.zmin.toFixed(3)} ~ ${result.zmax.toFixed(3)}`,
      `预计 tile 数: ${result.estimated_tiles}`,
    ].join("\n");
  } catch (error) {
    tilePreview.value = `预扫描失败: ${(error as Error).message}`;
  }
}

async function openOutputDir() {
  if (!formValues.output_dir?.trim()) {
    return;
  }
  try {
    await openLocalPath(formValues.output_dir);
  } catch {
    // Ignore open failure and keep UI usable.
  }
}

function buildRosDataSourceConfig() {
  const savedLayout: SavedNavPanelLayout = {
    sidePanels: navSidePanels.value.map((panel) => ({
      ...panel,
      collapsed: false,
      paused: false,
    })),
    fullPanels: navFullPanels.value.map((panel) => ({
      ...panel,
      collapsed: false,
      paused: false,
    })),
    mainDisplays: navMainDisplays.value.map((display) => ({ ...display })),
  };
  return {
    provider: (formValues.ros_provider || "rosbridge").trim() || "rosbridge",
    options: {
      url: (formValues.ros_bridge_url || "").trim(),
      rosapi_service: (formValues.ros_api_service || "/rosapi/topics_and_raw_types").trim(),
      timeout_ms: (formValues.timeout_ms || "2500").trim(),
      nav_layout_json: JSON.stringify(savedLayout),
    },
  };
}

function sanitizeNavPanelItem(raw: unknown, fallbackPrefix: string, index: number): NavPanelItem | null {
  if (!raw || typeof raw !== "object") {
    return null;
  }
  const panel = raw as Record<string, unknown>;
  const topic = typeof panel.topic === "string" ? panel.topic.trim() : "";
  const messageType = typeof panel.messageType === "string" ? panel.messageType.trim() : "";
  if (!topic || !messageType) {
    return null;
  }
  const id = typeof panel.id === "string" && panel.id.trim()
    ? panel.id.trim()
    : `${fallbackPrefix}-${topic.replace(/[^a-z0-9]+/gi, "-").replace(/^-+|-+$/g, "") || index}`;
  return {
    id,
    title: typeof panel.title === "string" && panel.title.trim() ? panel.title.trim() : `${topic}窗`,
    topic,
    type: typeof panel.type === "string" && panel.type.trim() ? panel.type.trim() : "可视化卡片",
    messageType,
    collapsed: false,
    paused: false,
    pointSize: typeof panel.pointSize === "number" ? panel.pointSize : undefined,
    hzLimit: typeof panel.hzLimit === "number" ? panel.hzLimit : undefined,
  };
}

function sanitizeNavViewerDisplay(raw: unknown): NavViewerDisplay | null {
  if (!raw || typeof raw !== "object") {
    return null;
  }
  const display = raw as Record<string, unknown>;
  const topic = typeof display.topic === "string" ? display.topic.trim() : "";
  const messageType = typeof display.messageType === "string" ? display.messageType.trim() : "";
  if (!topic || !messageType) {
    return null;
  }
  const kind = inferDisplayKind(topic, messageType);
  return {
    topic,
    messageType,
    kind,
    label: typeof display.label === "string" && display.label.trim() ? display.label.trim() : buildDisplayLabel(topic, kind),
    pointSize: typeof display.pointSize === "number" ? display.pointSize : undefined,
    hzLimit: typeof display.hzLimit === "number" ? display.hzLimit : undefined,
    color: typeof display.color === "string" && display.color.trim() ? display.color.trim() : undefined,
    tfShowNames: typeof display.tfShowNames === "boolean" ? display.tfShowNames : undefined,
    tfLabelSize: typeof display.tfLabelSize === "number" ? display.tfLabelSize : undefined,
    tfVisibleFrames: Array.isArray(display.tfVisibleFrames)
      ? display.tfVisibleFrames.filter((item): item is string => typeof item === "string" && item.trim().length > 0)
      : undefined,
  };
}

function parseSavedNavLayout(rawValue: string | undefined): SavedNavPanelLayout | null {
  if (!rawValue) {
    return null;
  }
  try {
    const parsed = JSON.parse(rawValue) as Record<string, unknown>;
    const sidePanels = Array.isArray(parsed.sidePanels)
      ? parsed.sidePanels
        .map((item, index) => sanitizeNavPanelItem(item, "side-panel", index))
        .filter((item): item is NavPanelItem => item !== null)
      : [];
    const fullPanels = Array.isArray(parsed.fullPanels)
      ? parsed.fullPanels
        .map((item, index) => sanitizeNavPanelItem(item, "full-panel", index))
        .filter((item): item is NavPanelItem => item !== null)
      : [];
    const mainDisplays = Array.isArray(parsed.mainDisplays)
      ? parsed.mainDisplays
        .map((item) => sanitizeNavViewerDisplay(item))
        .filter((item): item is NavViewerDisplay => item !== null)
      : [];
    return {
      sidePanels,
      fullPanels,
      mainDisplays,
    };
  } catch {
    return null;
  }
}

function mapTopicItemToOption(topic: RosTopicItem): NavTopicOption {
  const tail = topic.name.split("/").filter(Boolean).pop() || topic.name;
  return {
    key: topic.name,
    label: tail,
    type: topic.type || "未知类型",
    note: "来自后端 ROS 数据层实时检测，可直接加入主视图或小窗列表。",
  };
}

function mergeRosTopicOptions(nextTopics: NavTopicOption[]) {
  const merged = new Map<string, NavTopicOption>();

  defaultNavTopicOptions.forEach((topic) => {
    merged.set(topic.key, topic);
  });

  nextTopics.forEach((topic) => {
    const previous = merged.get(topic.key);
    merged.set(topic.key, {
      key: topic.key,
      label: topic.label || previous?.label || topic.key,
      type: topic.type || previous?.type || "未知类型",
      note: topic.note || previous?.note || "",
    });
  });

  return Array.from(merged.values()).sort((left, right) => {
    const leftIsDefault = defaultNavTopicOptions.some((topic) => topic.key === left.key);
    const rightIsDefault = defaultNavTopicOptions.some((topic) => topic.key === right.key);
    if (leftIsDefault !== rightIsDefault) {
      return leftIsDefault ? -1 : 1;
    }
    return left.key.localeCompare(right.key, "zh-CN");
  });
}

function topicOptionToDisplay(option: NavTopicOption): NavViewerDisplay {
  const kind = inferDisplayKind(option.key, option.type);
  return {
    topic: option.key,
    messageType: option.type,
    kind,
    label: buildDisplayLabel(option.key, kind),
    pointSize: kind === "pointcloud" ? 0.08 : undefined,
    hzLimit: kind === "pointcloud" ? 5 : undefined,
    color: kind === "pointcloud" ? defaultPointCloudColor(option.key) : undefined,
    tfShowNames: kind === "tf" ? true : undefined,
    tfLabelSize: kind === "tf" ? 0.5 : undefined,
    tfVisibleFrames: kind === "tf" ? [] : undefined,
  };
}

function hasMainDisplay(topicKey: string) {
  return navMainDisplays.value.some((display) => display.topic === topicKey);
}

function hasSidePanel(topicKey: string) {
  return navSidePanels.value.some((panel) => panel.topic === topicKey);
}

function hasFullPanel(topicKey: string) {
  return navFullPanels.value.some((panel) => panel.topic === topicKey);
}

function ensureDefaultNavDisplays() {
  if (navMainDisplays.value.length > 0) {
    return;
  }

  const defaults = [
    { key: formValues.map_topic || "/debug/loaded_pointcloud_map", type: "sensor_msgs/msg/PointCloud2", label: "地图点云", note: "" },
    { key: "/points_aligned", type: "sensor_msgs/msg/PointCloud2", label: "对齐结果点云", note: "" },
    { key: "/cloud_registered_bl", type: "sensor_msgs/msg/PointCloud2", label: "NDT 输入点云", note: "" },
    { key: "/tf", type: "tf2_msgs/msg/TFMessage", label: "TF 树", note: "" },
    { key: formValues.path_topic || "/plan", type: "nav_msgs/msg/Path", label: "全局路径", note: "" },
    { key: formValues.pose_topic || "/ndt_pose", type: "geometry_msgs/msg/PoseStamped", label: "NDT 位姿", note: "" },
  ];

  navMainDisplays.value = defaults.map(topicOptionToDisplay);
}

async function loadRosDataSourceConfigForNav() {
  let shouldApplyDefaultDisplays = true;
  try {
    const config = await fetchRosDataSourceConfig();
    formValues.ros_provider = config.provider || formValues.ros_provider || "rosbridge";
    formValues.ros_bridge_url = config.options.url || formValues.ros_bridge_url || "";
    formValues.ros_api_service = config.options.rosapi_service || formValues.ros_api_service || "/rosapi/topics_and_raw_types";
    formValues.timeout_ms = config.options.timeout_ms || formValues.timeout_ms || "2500";
    const savedLayout = parseSavedNavLayout(config.options.nav_layout_json);
    if (savedLayout) {
      shouldApplyDefaultDisplays = false;
      navSidePanels.value = savedLayout.sidePanels.length > 0 ? savedLayout.sidePanels : createDefaultNavSidePanels();
      navFullPanels.value = savedLayout.fullPanels.length > 0 ? savedLayout.fullPanels : createDefaultNavFullPanels();
      navMainDisplays.value = savedLayout.mainDisplays;
    }
  } catch {
    // 配置读取失败时保留表单默认值，避免阻断页面使用。
  } finally {
    if (shouldApplyDefaultDisplays) {
      ensureDefaultNavDisplays();
    }
  }
}

async function saveRosNavConfig() {
  rosDataSourceSaving.value = true;
  try {
    const saved = await saveRosDataSourceConfig(buildRosDataSourceConfig());
    formValues.ros_provider = saved.provider;
    formValues.ros_bridge_url = saved.options.url || formValues.ros_bridge_url || "";
    formValues.ros_api_service = saved.options.rosapi_service || formValues.ros_api_service || "";
    formValues.timeout_ms = saved.options.timeout_ms || formValues.timeout_ms || "";
    rosTopicsMessage.value = "ROS 数据源配置已保存。";
  } catch (error) {
    rosTopicsMessage.value = `ROS 数据源配置保存失败: ${(error as Error).message}`;
  } finally {
    rosDataSourceSaving.value = false;
  }
}

async function inspectRosNavSource() {
  rosInspectLoading.value = true;
  rosInspectResult.value = null;
  try {
    rosInspectResult.value = await inspectRosDataSource(buildRosDataSourceConfig());
  } catch (error) {
    rosInspectResult.value = {
      provider: formValues.ros_provider || "rosbridge",
      status: "error",
      message: (error as Error).message,
      capabilities: [],
      detected_hints: [],
      topics_count: 0,
    };
  } finally {
    rosInspectLoading.value = false;
  }
}

async function refreshRosTopics() {
  rosTopicsLoading.value = true;
  try {
    const response = await fetchRosTopics(buildRosDataSourceConfig());
    rosTopicsMessage.value = response.message;
    rosTopicOptions.value = response.topics.length > 0
      ? mergeRosTopicOptions(response.topics.map(mapTopicItemToOption))
      : defaultNavTopicOptions;
  } catch (error) {
    rosTopicsMessage.value = `读取 topic 失败: ${(error as Error).message}`;
    rosTopicOptions.value = defaultNavTopicOptions;
  } finally {
    rosTopicsLoading.value = false;
  }
}

function buildRosLiveConfig() {
  return {
    provider: (formValues.ros_provider || "rosbridge").trim() || "rosbridge",
    url: (formValues.ros_bridge_url || "").trim(),
    timeoutMs: Number(formValues.timeout_ms || "2500"),
  };
}

function yawToQuaternion(yaw: number) {
  const halfYaw = yaw / 2;
  return {
    x: 0,
    y: 0,
    z: Math.sin(halfYaw),
    w: Math.cos(halfYaw),
  };
}

async function publishRosMessage(topicName: string, messageType: string, message: Record<string, unknown>) {
  const adapter = createRosLiveAdapter(buildRosLiveConfig());
  try {
    await adapter.connect();
    adapter.publish(topicName, messageType, message);
  } finally {
    adapter.disconnect();
  }
}

function nextRequestPlanId() {
  const requestPlanId = `web_test_${String(navGoalSequence.value).padStart(3, "0")}`;
  navGoalSequence.value += 1;
  return requestPlanId;
}

function enterInitialPoseMode() {
  navInteractionMode.value = navInteractionMode.value === "initialpose" ? "none" : "initialpose";
  navControlMessage.value = navInteractionMode.value === "initialpose" ? "已进入初始化定位模式，请在主视图点击并拖动方向。" : "已退出初始化定位模式。";
}

function enterNavGoalMode() {
  navInteractionMode.value = navInteractionMode.value === "navgoal" ? "none" : "navgoal";
  navControlMessage.value = navInteractionMode.value === "navgoal" ? "已进入导航目标模式，请在主视图点击并拖动方向。" : "已退出导航目标模式。";
}

async function publishInitialPose(x: number, y: number, yaw: number) {
  const orientation = yawToQuaternion(yaw);
  await publishRosMessage("/initialpose", "geometry_msgs/msg/PoseWithCovarianceStamped", {
    header: {
      frame_id: formValues.fixed_frame || "map",
    },
    pose: {
      pose: {
        position: {
          x,
          y,
          z: 0,
        },
        orientation,
      },
      covariance: [
        0.25, 0, 0, 0, 0, 0,
        0, 0.25, 0, 0, 0, 0,
        0, 0, 0.0, 0, 0, 0,
        0, 0, 0, 0.0, 0, 0,
        0, 0, 0, 0, 0.0, 0,
        0, 0, 0, 0, 0, 0.0685,
      ],
    },
  });
}

async function publishNavGoal(x: number, y: number, yaw: number) {
  const requestPlanId = nextRequestPlanId();
  await publishRosMessage("/nav2_goal_request", "std_msgs/msg/String", {
    data: JSON.stringify({
      request_planid: requestPlanId,
      pose: {
        frame_id: formValues.fixed_frame || "map",
        x,
        y,
        yaw,
      },
      context: {
        source: "web",
        scene: "ndt_test",
      },
    }),
  });
  navControlMessage.value = `已下发导航目标: ${requestPlanId}`;
}

async function handleNavViewerInteraction(payload: { mode: "initialpose" | "navgoal"; x: number; y: number; yaw: number }) {
  navControlLoading.value = true;
  try {
    if (payload.mode === "initialpose") {
      await publishInitialPose(payload.x, payload.y, payload.yaw);
      navControlMessage.value = `已下发初始化定位: (${payload.x.toFixed(2)}, ${payload.y.toFixed(2)}, yaw=${payload.yaw.toFixed(2)})`;
    } else {
      await publishNavGoal(payload.x, payload.y, payload.yaw);
    }
  } catch (error) {
    navControlMessage.value = `下发失败: ${(error as Error).message}`;
  } finally {
    navControlLoading.value = false;
    navInteractionMode.value = "none";
  }
}

async function sendNavControlCommand(command: "pause" | "resume" | "cancel") {
  navControlLoading.value = true;
  try {
    await publishRosMessage("/nav2_goal_control", "std_msgs/msg/String", {
      data: command,
    });
    navControlMessage.value = `已发送导航控制: ${command}`;
  } catch (error) {
    navControlMessage.value = `控制下发失败: ${(error as Error).message}`;
  } finally {
    navControlLoading.value = false;
  }
}

async function loadNavRecordingFiles() {
  navRecordingFilesLoading.value = true;
  try {
    const response = await fetchNavRecordingFiles();
    navRecordingFiles.value = response.items;
    navRecordingFilesDirectory.value = response.directory;
    navRecordingFilesMessage.value = response.items.length > 0 ? `已读取 ${response.items.length} 个录制文件。` : "录制目录当前没有文件。";
  } catch (error) {
    navRecordingFilesMessage.value = `录制文件读取失败: ${(error as Error).message}`;
  } finally {
    navRecordingFilesLoading.value = false;
  }
}

function parseNavRecordingPayload(rawText: string) {
  const beginIndex = rawText.indexOf(NAV_RECORDING_JSON_BEGIN);
  const endIndex = rawText.indexOf(NAV_RECORDING_JSON_END);
  if (beginIndex < 0 || endIndex <= beginIndex) {
    return null;
  }
  const jsonText = rawText
    .slice(beginIndex + NAV_RECORDING_JSON_BEGIN.length, endIndex)
    .trim();
  try {
    return JSON.parse(jsonText) as NavRecordingSavePayload;
  } catch {
    return null;
  }
}

function stripNavRecordingPayload(rawText: string) {
  const beginIndex = rawText.indexOf(NAV_RECORDING_JSON_BEGIN);
  const endIndex = rawText.indexOf(NAV_RECORDING_JSON_END);
  if (beginIndex < 0 || endIndex <= beginIndex) {
    return rawText;
  }
  return `${rawText.slice(0, beginIndex).trimEnd()}\n`.trim();
}

function resetNavRecordingChartState(payload: NavRecordingSavePayload | null) {
  navRecordingParsedPayload.value = payload;
  navRecordingChartHover.value = null;
  if (!payload || payload.metric_series.length === 0) {
    navRecordingChartMetricLabel.value = "";
    navRecordingChartRangeStart.value = 0;
    navRecordingChartRangeEnd.value = 1;
    return;
  }
  navRecordingChartMetricLabel.value = payload.metric_series[0].label;
  navRecordingChartRangeStart.value = 0;
  navRecordingChartRangeEnd.value = Math.max(1, payload.duration_ms);
}

const activeNavRecordingMetric = computed(() => {
  const payload = navRecordingParsedPayload.value;
  if (!payload) {
    return null;
  }
  return payload.metric_series.find((item) => item.label === navRecordingChartMetricLabel.value) || payload.metric_series[0] || null;
});

const activeNavRecordingMetricSamples = computed(() => {
  const metric = activeNavRecordingMetric.value;
  if (!metric) {
    return [];
  }
  return metric.samples.filter((sample) => sample.offset_ms >= navRecordingChartRangeStart.value && sample.offset_ms <= navRecordingChartRangeEnd.value);
});

function navRecordingChartTimeText(offsetMs: number) {
  const payload = navRecordingParsedPayload.value;
  if (!payload) {
    return "-";
  }
  return new Date(payload.started_at_ms + offsetMs).toLocaleTimeString("zh-CN", {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    fractionalSecondDigits: 3,
  });
}

function navRecordingChartPolylinePoints() {
  const samples = activeNavRecordingMetricSamples.value;
  if (samples.length === 0) {
    return "";
  }
  const rangeSpan = Math.max(1, navRecordingChartRangeEnd.value - navRecordingChartRangeStart.value);
  const values = samples.map((item) => item.value);
  const minValue = Math.min(...values);
  const maxValue = Math.max(...values);
  const valueSpan = Math.max(1e-6, maxValue - minValue);
  return samples
    .map((sample) => {
      const x = ((sample.offset_ms - navRecordingChartRangeStart.value) / rangeSpan) * 1000;
      const y = 190 - ((sample.value - minValue) / valueSpan) * 150;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");
}

function setNavRecordingMetric(label: string) {
  navRecordingChartMetricLabel.value = label;
  navRecordingChartHover.value = null;
}

function zoomNavRecordingChart(factor: number, anchorRatio = 0.5) {
  const payload = navRecordingParsedPayload.value;
  if (!payload) {
    return;
  }
  const totalDuration = Math.max(1, payload.duration_ms);
  const currentSpan = Math.max(1, navRecordingChartRangeEnd.value - navRecordingChartRangeStart.value);
  const nextSpan = Math.max(200, Math.min(totalDuration, currentSpan * factor));
  const anchorOffset = navRecordingChartRangeStart.value + currentSpan * anchorRatio;
  let nextStart = anchorOffset - nextSpan * anchorRatio;
  let nextEnd = nextStart + nextSpan;
  if (nextStart < 0) {
    nextStart = 0;
    nextEnd = nextSpan;
  }
  if (nextEnd > totalDuration) {
    nextEnd = totalDuration;
    nextStart = Math.max(0, totalDuration - nextSpan);
  }
  navRecordingChartRangeStart.value = Math.round(nextStart);
  navRecordingChartRangeEnd.value = Math.round(nextEnd);
  navRecordingChartHover.value = null;
}

function handleNavRecordingChartWheel(event: WheelEvent) {
  const payload = navRecordingParsedPayload.value;
  const target = event.currentTarget as HTMLElement | null;
  if (!payload || !target) {
    return;
  }
  event.preventDefault();
  const rect = target.getBoundingClientRect();
  const anchorRatio = Math.max(0, Math.min(1, (event.clientX - rect.left) / Math.max(1, rect.width)));
  zoomNavRecordingChart(event.deltaY > 0 ? 1.25 : 0.8, anchorRatio);
}

function handleNavRecordingChartPointerDown(event: PointerEvent) {
  if (!navRecordingParsedPayload.value) {
    return;
  }
  navRecordingChartDragging.value = true;
  navRecordingChartDragAnchorX = event.clientX;
  navRecordingChartDragRangeStart = navRecordingChartRangeStart.value;
  navRecordingChartDragRangeEnd = navRecordingChartRangeEnd.value;
}

function handleNavRecordingChartPointerMove(event: PointerEvent) {
  const payload = navRecordingParsedPayload.value;
  const metric = activeNavRecordingMetric.value;
  const target = event.currentTarget as HTMLElement | null;
  if (!payload || !metric || !target) {
    return;
  }
  const rect = target.getBoundingClientRect();
  const ratio = Math.max(0, Math.min(1, (event.clientX - rect.left) / Math.max(1, rect.width)));
  const hoverOffset = navRecordingChartRangeStart.value + ratio * Math.max(1, navRecordingChartRangeEnd.value - navRecordingChartRangeStart.value);
  const nearest = metric.samples.reduce((best, sample) => {
    if (!best) {
      return sample;
    }
    return Math.abs(sample.offset_ms - hoverOffset) < Math.abs(best.offset_ms - hoverOffset) ? sample : best;
  }, metric.samples[0]);
  if (nearest) {
    navRecordingChartHover.value = {
      offsetMs: nearest.offset_ms,
      value: nearest.value,
      x: ((nearest.offset_ms - navRecordingChartRangeStart.value) / Math.max(1, navRecordingChartRangeEnd.value - navRecordingChartRangeStart.value)) * 1000,
    };
  }
  if (!navRecordingChartDragging.value) {
    return;
  }
  const pixelDelta = event.clientX - navRecordingChartDragAnchorX;
  const totalDuration = Math.max(1, payload.duration_ms);
  const currentSpan = Math.max(1, navRecordingChartDragRangeEnd - navRecordingChartDragRangeStart);
  const offsetDelta = (pixelDelta / Math.max(1, rect.width)) * currentSpan;
  let nextStart = navRecordingChartDragRangeStart - offsetDelta;
  let nextEnd = navRecordingChartDragRangeEnd - offsetDelta;
  if (nextStart < 0) {
    nextEnd -= nextStart;
    nextStart = 0;
  }
  if (nextEnd > totalDuration) {
    const overflow = nextEnd - totalDuration;
    nextStart -= overflow;
    nextEnd = totalDuration;
  }
  navRecordingChartRangeStart.value = Math.max(0, Math.round(nextStart));
  navRecordingChartRangeEnd.value = Math.min(totalDuration, Math.round(Math.max(nextStart + 1, nextEnd)));
}

function stopNavRecordingChartDrag() {
  navRecordingChartDragging.value = false;
}

async function previewNavRecordingFile(item: NavRecordingFileItem) {
  navRecordingPreviewPath.value = item.path;
  navRecordingPreviewKind.value = item.kind;
  navRecordingParsedPayload.value = null;
  navRecordingChartHover.value = null;
  if (item.kind !== "text") {
    navRecordingPreviewText.value = "";
    return;
  }
  try {
    const rawText = await fetchLocalTextFile(item.path);
    navRecordingPreviewText.value = stripNavRecordingPayload(rawText);
    resetNavRecordingChartState(parseNavRecordingPayload(rawText));
  } catch (error) {
    navRecordingPreviewText.value = `读取失败: ${(error as Error).message}`;
    resetNavRecordingChartState(null);
  }
}

async function removeNavRecordingFile(path: string) {
  try {
    const response = await deleteNavRecording(path);
    navRecordingFiles.value = response.items;
    navRecordingFilesDirectory.value = response.directory;
    navRecordingFilesMessage.value = `已删除录制文件: ${path}`;
    if (navRecordingPreviewPath.value === path) {
      navRecordingPreviewPath.value = "";
      navRecordingPreviewText.value = "";
      navRecordingPreviewKind.value = "";
      resetNavRecordingChartState(null);
    }
  } catch (error) {
    navRecordingFilesMessage.value = `删除录制文件失败: ${(error as Error).message}`;
  }
}

function fieldKind(fieldKey: string) {
  if (fieldKey === "login_session_id") {
    return "hidden";
  }
  if (fieldKey === "login_password") {
    return "password";
  }
  if (fieldKey === "ros_provider") {
    return "select-ros-provider";
  }
  if (props.tool.key === "pcd_tile" && fieldKey === "format") {
    return "select-format";
  }
  if (props.tool.key === "mtslash_export" && fieldKey === "browser_type") {
    return "select-browser";
  }
  if (fieldKey === "zip_output" || fieldKey === "export_gif" || fieldKey === "export_png" || fieldKey === "show_lethal" || fieldKey === "show_footprint" || fieldKey === "only_thread_author" || fieldKey === "browser_mode") {
    return "select-bool";
  }
  return "input";
}

async function fetchCaptcha() {
  mtslashCaptchaLoading.value = true;
  mtslashLoginMessage.value = "";
  mtslashLoggedIn.value = false;
  try {
    const result = await fetchMtslashCaptcha();
    formValues.login_session_id = result.session_id;
    mtslashCaptchaImage.value = result.captcha_image;
    mtslashLoginMessage.value = result.message;
  } catch (error) {
    mtslashLoginMessage.value = `验证码获取失败: ${(error as Error).message}`;
  } finally {
    mtslashCaptchaLoading.value = false;
  }
}

async function loginMtslashSession() {
  mtslashLoginLoading.value = true;
  mtslashLoginMessage.value = "";
  try {
    const result = await loginMtslash({ ...formValues });
    formValues.login_session_id = result.session_id;
    mtslashLoggedIn.value = true;
    mtslashLoginMessage.value = result.message;
    persistMtslashCachedFields();
  } catch (error) {
    mtslashLoggedIn.value = false;
    mtslashLoginMessage.value = `登录失败: ${(error as Error).message}`;
  } finally {
    mtslashLoginLoading.value = false;
  }
}

async function loadMtslashFavorites() {
  const useBrowser = String(formValues.browser_mode ?? "false").toLowerCase() === "true";
  if (!useBrowser && !formValues.login_session_id?.trim()) {
    mtslashFavoritesMessage.value = "请先获取验证码并登录。";
    return;
  }
  mtslashFavoritesLoading.value = true;
  mtslashFavoritesMessage.value = "";
  try {
    const browser = formValues.browser_type || "edge";
    const result = useBrowser ? await fetchMtslashBrowserFavorites(browser) : await fetchMtslashFavorites(formValues.login_session_id);
    mtslashFavorites.value = result.items ?? [];
    mtslashFavoritesPage.value = 1;
    mtslashFavoritesMessage.value = `已加载 ${mtslashFavorites.value.length} 条收藏，扫描 ${result.page_count} 页${useBrowser ? "，来源: 浏览器模式" : ""}。`;
  } catch (error) {
    mtslashFavoritesMessage.value = `收藏夹加载失败: ${(error as Error).message}`;
  } finally {
    mtslashFavoritesLoading.value = false;
  }
}

function selectMtslashFavorite(item: MtslashFavoriteItem) {
  formValues.thread_url = item.url;
}

async function startMtslashBrowserMode() {
  mtslashBrowserLoading.value = true;
  mtslashBrowserMessage.value = "";
  try {
    const browser = formValues.browser_type || "edge";
    const result = await startMtslashBrowser(browser);
    formValues.browser_mode = "true";
    mtslashBrowserMessage.value = result.message || `${browser} 浏览器模式已就绪`;
    await loadMtslashBrowserTabs();
  } catch (error) {
    mtslashBrowserMessage.value = `浏览器模式启动失败: ${(error as Error).message}`;
  } finally {
    mtslashBrowserLoading.value = false;
  }
}

async function loadMtslashBrowserTabs() {
  mtslashBrowserLoading.value = true;
  mtslashBrowserMessage.value = "";
  try {
    const browser = formValues.browser_type || "edge";
    const result = await fetchMtslashBrowserTabs(browser);
    mtslashBrowserTabs.value = result.items ?? [];
    mtslashBrowserPage.value = 1;
    mtslashBrowserMessage.value = `已发现 ${mtslashBrowserTabs.value.length} 个站内标签页。`;
  } catch (error) {
    mtslashBrowserMessage.value = `标签页读取失败: ${(error as Error).message}`;
  } finally {
    mtslashBrowserLoading.value = false;
  }
}

function selectMtslashBrowserTab(item: MtslashBrowserTab) {
  formValues.thread_url = item.url;
  formValues.browser_mode = "true";
}

function prevMtslashBrowserPage() {
  mtslashBrowserPage.value = Math.max(1, mtslashBrowserPage.value - 1);
}

function nextMtslashBrowserPage() {
  mtslashBrowserPage.value = Math.min(filteredMtslashBrowserTotalPages.value, mtslashBrowserPage.value + 1);
}

function prevMtslashFavoritesPage() {
  mtslashFavoritesPage.value = Math.max(1, mtslashFavoritesPage.value - 1);
}

function nextMtslashFavoritesPage() {
  mtslashFavoritesPage.value = Math.min(filteredMtslashFavoriteTotalPages.value, mtslashFavoritesPage.value + 1);
}

function costColor(value: number) {
  if (value < 0) {
    return [92, 98, 112];
  }
  if (value === 0) {
    return [13, 19, 29];
  }
  const clamped = Math.max(0, Math.min(100, value));
  if (costmapShowLethal.value && clamped >= costmapThreshold.value) {
    return [255, 80, 48];
  }
  const ratio = clamped / 100;
  return [
    Math.round(55 + ratio * 200),
    Math.round(132 + ratio * 78),
    Math.round(Math.max(30, 255 - ratio * 220)),
  ];
}

function drawCostmapFrame() {
  const canvas = costmapCanvas.value;
  const frame = currentCostmapFrame.value;
  if (!canvas || !frame) {
    return;
  }
  const previewWidth = Number(frame.preview_width ?? 0);
  const previewHeight = Number(frame.preview_height ?? 0);
  const values = frame.preview_pixels ?? [];
  if (previewWidth <= 0 || previewHeight <= 0 || values.length === 0) {
    return;
  }

  const hostWidth = Math.max(320, canvas.parentElement?.clientWidth ?? 720);
  const scale = Math.max(2, Math.floor(Math.min(hostWidth / previewWidth, 620 / previewHeight)));
  canvas.width = previewWidth * scale;
  canvas.height = previewHeight * scale;
  const ctx = canvas.getContext("2d");
  if (!ctx) {
    return;
  }
  ctx.imageSmoothingEnabled = false;
  const imageData = ctx.createImageData(previewWidth, previewHeight);
  for (let y = 0; y < previewHeight; y += 1) {
    for (let x = 0; x < previewWidth; x += 1) {
      const sourceIndex = (previewHeight - 1 - y) * previewWidth + x;
      const targetIndex = (y * previewWidth + x) * 4;
      const [r, g, b] = costColor(Number(values[sourceIndex] ?? 0));
      imageData.data[targetIndex] = r;
      imageData.data[targetIndex + 1] = g;
      imageData.data[targetIndex + 2] = b;
      imageData.data[targetIndex + 3] = 255;
    }
  }
  const offscreen = document.createElement("canvas");
  offscreen.width = previewWidth;
  offscreen.height = previewHeight;
  offscreen.getContext("2d")?.putImageData(imageData, 0, 0);
  ctx.drawImage(offscreen, 0, 0, canvas.width, canvas.height);

  ctx.strokeStyle = "#4adfff";
  ctx.fillStyle = "#4adfff";
  ctx.lineWidth = 2;
  const centerX = canvas.width / 2;
  const centerY = canvas.height / 2;
  ctx.beginPath();
  ctx.moveTo(centerX - 8, centerY);
  ctx.lineTo(centerX + 8, centerY);
  ctx.moveTo(centerX, centerY - 8);
  ctx.lineTo(centerX, centerY + 8);
  ctx.stroke();

  if (costmapShowFootprint.value) {
    const metersPerPreviewCell = Number(frame.resolution ?? 0.05) * (Number(frame.width ?? previewWidth) / previewWidth);
    const footprintWidthPx = Math.max(8, (costmapFootprintLength.value / metersPerPreviewCell) * scale);
    const footprintHeightPx = Math.max(8, (costmapFootprintWidth.value / metersPerPreviewCell) * scale);
    ctx.strokeRect(centerX - footprintWidthPx / 2, centerY - footprintHeightPx / 2, footprintWidthPx, footprintHeightPx);
  }
}

function stopCostmapPlayback() {
  costmapPlaying.value = false;
  if (costmapTimer !== undefined) {
    window.clearTimeout(costmapTimer);
    costmapTimer = undefined;
  }
}

function scheduleCostmapPlayback() {
  if (!costmapPlaying.value || costmapFrames.value.length === 0) {
    return;
  }
  costmapTimer = window.setTimeout(() => {
    costmapFrameIndex.value = (costmapFrameIndex.value + 1) % costmapFrames.value.length;
    scheduleCostmapPlayback();
  }, Math.round(1000 / costmapFps.value));
}

function playCostmap() {
  if (costmapFrames.value.length === 0) {
    return;
  }
  stopCostmapPlayback();
  costmapPlaying.value = true;
  scheduleCostmapPlayback();
}

function pauseCostmap() {
  stopCostmapPlayback();
}

function prevCostmapFrame() {
  stopCostmapPlayback();
  costmapFrameIndex.value = Math.max(0, costmapFrameIndex.value - 1);
}

function nextCostmapFrame() {
  stopCostmapPlayback();
  costmapFrameIndex.value = Math.min(costmapFrames.value.length - 1, costmapFrameIndex.value + 1);
}

async function exportCurrentCostmapPng() {
  await nextTick();
  drawCostmapFrame();
  const canvas = costmapCanvas.value;
  if (!canvas || !currentCostmapFrame.value) {
    return;
  }
  const link = document.createElement("a");
  link.href = canvas.toDataURL("image/png");
  link.download = `costmap_frame_${String(costmapFrameIndex.value + 1).padStart(4, "0")}.png`;
  link.click();
}

function addSelectedTopicsAsSidePanels() {
  selectedNavTopicOptions.value.forEach((topic) => {
    addTopicAsSidePanel(topic);
  });
  selectedNavTopics.value = [];
}

function addSelectedTopicsAsFullPanels() {
  selectedNavTopicOptions.value.forEach((topic) => {
    addTopicAsFullPanel(topic);
  });
  selectedNavTopics.value = [];
}

function addSelectedTopicsToMainView() {
  if (selectedNavTopicOptions.value.length === 0) {
    return;
  }
  selectedNavTopicOptions.value.forEach((topic) => {
    addTopicToMainView(topic);
  });
  selectedNavTopics.value = [];
}

function addTopicToMainView(topic: NavTopicOption) {
  if (hasMainDisplay(topic.key)) {
    return;
  }
  navMainDisplays.value = [...navMainDisplays.value, topicOptionToDisplay(topic)];
}

function createNavPanelFromTopic(topic: NavTopicOption, idPrefix: string): NavPanelItem {
  const isPointCloudTopic = topic.type === "sensor_msgs/msg/PointCloud2";
  return {
    id: `${idPrefix}-${topic.key.replace(/[^a-z0-9]+/gi, "-").replace(/^-+|-+$/g, "")}`,
    title: `${topic.label}窗`,
    topic: topic.key,
    type: "可视化卡片",
    messageType: topic.type,
    collapsed: false,
    paused: false,
    pointSize: isPointCloudTopic ? 2.5 : undefined,
    hzLimit: isPointCloudTopic ? 5 : undefined,
  };
}

function addTopicAsSidePanel(topic: NavTopicOption) {
  if (hasSidePanel(topic.key)) {
    return;
  }
  navSidePanels.value = [...navSidePanels.value, createNavPanelFromTopic(topic, "side-panel")];
}

function addTopicAsFullPanel(topic: NavTopicOption) {
  if (hasFullPanel(topic.key)) {
    return;
  }
  navFullPanels.value = [...navFullPanels.value, createNavPanelFromTopic(topic, "full-panel")];
}

function removeMainDisplay(topic: string) {
  navMainDisplays.value = navMainDisplays.value.filter((display) => display.topic !== topic);
}

function updateMainDisplayConfig(topic: string, patch: Partial<NavViewerDisplay>) {
  navMainDisplays.value = navMainDisplays.value.map((display) => {
    if (display.topic !== topic) {
      return display;
    }
    return {
      ...display,
      ...patch,
    };
  });
}

function updateMainDisplayPointSize(topic: string, rawValue: string) {
  const pointSize = Math.min(0.6, Math.max(0.01, Number(rawValue || "0.08") || 0.08));
  updateMainDisplayConfig(topic, { pointSize });
}

function updateMainDisplayHzLimit(topic: string, rawValue: string) {
  const hzLimit = Math.max(0, Math.round(Number(rawValue || "0") || 0));
  updateMainDisplayConfig(topic, { hzLimit });
}

function updateMainDisplayColor(topic: string, rawValue: string) {
  updateMainDisplayConfig(topic, { color: rawValue || defaultPointCloudColor(topic) });
}

function updateMainDisplayTfLabelSize(topic: string, rawValue: string) {
  const tfLabelSize = Math.min(2, Math.max(0.2, Number(rawValue || "0.5") || 0.5));
  updateMainDisplayConfig(topic, { tfLabelSize });
}

function updateMainDisplayTfShowNames(topic: string, checked: boolean) {
  updateMainDisplayConfig(topic, { tfShowNames: checked });
}

function tfFramesForDisplay(topic: string) {
  return navTfFrameOptions.value[topic] || [];
}

function isTfFrameSelected(display: NavViewerDisplay, frameName: string) {
  const selectedFrames = display.tfVisibleFrames ?? [];
  return selectedFrames.length === 0 || selectedFrames.includes(frameName);
}

function showAllMainDisplayTfFrames(topic: string) {
  updateMainDisplayConfig(topic, { tfVisibleFrames: [] });
}

function toggleMainDisplayTfFrame(topic: string, frameName: string) {
  const display = navMainDisplays.value.find((item) => item.topic === topic);
  if (!display) {
    return;
  }
  const currentFrames = display.tfVisibleFrames ?? [];
  if (currentFrames.length === 0) {
    updateMainDisplayConfig(topic, { tfVisibleFrames: [frameName] });
    return;
  }
  const nextFrames = currentFrames.includes(frameName)
    ? currentFrames.filter((item) => item !== frameName)
    : [...currentFrames, frameName];
  updateMainDisplayConfig(topic, { tfVisibleFrames: nextFrames });
}

function handleTfFramesChange(payload: { topic: string; frames: string[] }) {
  navTfFrameOptions.value = {
    ...navTfFrameOptions.value,
    [payload.topic]: payload.frames,
  };
}

function toggleNavDisplayManager() {
  navDisplayManagerCollapsed.value = !navDisplayManagerCollapsed.value;
}

function togglePanelList(list: NavPanelItem[], panelId: string) {
  return list.map((panel) => {
    if (panel.id !== panelId) {
      return panel;
    }
    const nextCollapsed = !panel.collapsed;
    return {
      ...panel,
      collapsed: nextCollapsed,
      paused: nextCollapsed,
    };
  });
}

function toggleNavSidePanel(panelId: string) {
  navSidePanels.value = togglePanelList(navSidePanels.value, panelId);
}

function toggleNavFullPanel(panelId: string) {
  navFullPanels.value = togglePanelList(navFullPanels.value, panelId);
}

function removeNavSidePanel(panelId: string) {
  navSidePanels.value = navSidePanels.value.filter((panel) => panel.id !== panelId);
}

function removeNavFullPanel(panelId: string) {
  navFullPanels.value = navFullPanels.value.filter((panel) => panel.id !== panelId);
}

function updatePanelListConfig(list: NavPanelItem[], panelId: string, patch: Partial<NavPanelItem>) {
  return list.map((panel) => {
    if (panel.id !== panelId) {
      return panel;
    }
    return {
      ...panel,
      ...patch,
    };
  });
}

function updateNavSidePanelConfig(panelId: string, patch: Partial<NavPanelItem>) {
  navSidePanels.value = updatePanelListConfig(navSidePanels.value, panelId, patch);
}

function updateNavFullPanelConfig(panelId: string, patch: Partial<NavPanelItem>) {
  navFullPanels.value = updatePanelListConfig(navFullPanels.value, panelId, patch);
}

function exportNetworkCsv() {
  if (filteredNetworkRows.value.length === 0) {
    return;
  }
  const header = ["IP", "状态", "延迟(ms)", "主机名", "MAC", "ARP类型", "SSH(22)", "备注"];
  const rows = filteredNetworkRows.value.map((row) => [
    row.ip,
    row.status,
    row.latency,
    row.hostname,
    row.mac,
    row.arp_type,
    row.port_22,
    row.note,
  ]);
  const csv = [header, ...rows]
    .map((row) => row.map((cell) => `"${String(cell).replace(/"/g, '""')}"`).join(","))
    .join("\n");
  const blob = new Blob(["\ufeff" + csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "network_scan_results.csv";
  link.click();
  URL.revokeObjectURL(url);
}

watch(
  () => props.resultData.frames,
  () => {
    stopCostmapPlayback();
    costmapFrameIndex.value = 0;
    nextTick(drawCostmapFrame);
  }
);

watch(
  [currentCostmapFrame, costmapThreshold, costmapShowLethal, costmapShowFootprint, costmapFootprintLength, costmapFootprintWidth],
  () => nextTick(drawCostmapFrame)
);

onBeforeUnmount(() => stopCostmapPlayback());
</script>

<template>
  <div class="tool-shell">
    <header class="panel-header">
      <div>
        <h1>{{ tool.title }}</h1>
        <p>{{ tool.description }}</p>
      </div>
      <div class="status-pill">{{ loading ? "运行中" : "就绪" }}</div>
    </header>

    <div class="tool-layout" :class="`tool-layout-${tool.key}`">
      <section v-if="tool.key !== 'mtslash_export'" class="panel tool-form-panel">
        <div class="section-head">
          <div class="result-title">参数配置</div>
          <div class="section-subtitle">支持手动输入和本地浏览选择</div>
        </div>

        <div class="grid-form">
          <label v-for="field in tool.fields" v-show="fieldKind(field.key) !== 'hidden'" :key="field.key" class="field">
            <span class="field-label">{{ field.label }}</span>
            <div class="field-row">
              <select
                v-if="fieldKind(field.key) === 'select-format'"
                v-model="formValues[field.key]"
                class="field-input"
              >
                <option value="ascii">ASCII</option>
                <option value="binary">Binary</option>
              </select>
              <select
                v-else-if="fieldKind(field.key) === 'select-ros-provider'"
                v-model="formValues[field.key]"
                class="field-input"
              >
                <option value="rosbridge">rosbridge websocket</option>
                <option value="mock">mock</option>
              </select>
              <select
                v-else-if="fieldKind(field.key) === 'select-bool'"
                v-model="formValues[field.key]"
                class="field-input"
              >
                <option value="false">否</option>
                <option value="true">是</option>
              </select>
              <select
                v-else-if="fieldKind(field.key) === 'select-browser'"
                v-model="formValues[field.key]"
                class="field-input"
              >
                <option value="edge">Edge</option>
                <option value="chrome">Chrome</option>
              </select>
              <input
                v-else
                v-model="formValues[field.key]"
                class="field-input"
                :type="fieldKind(field.key) === 'password' ? 'password' : 'text'"
                :placeholder="field.placeholder"
              />
              <button
                v-if="getBrowseMode(field.key, field.label)"
                class="field-browse-btn"
                type="button"
                @click="browseField(field.key, field.label)"
              >
                选择
              </button>
            </div>
          </label>
        </div>

        <div class="actions">
          <button class="primary-btn" :disabled="loading" @click="submit">
            {{ loading ? "处理中..." : tool.primary_action }}
          </button>
          <template v-if="tool.key === 'pcd_map'">
            <button class="secondary-btn" type="button" @click="openOutputDir">打开输出目录</button>
            <button class="secondary-btn" type="button" @click="emit('clearLogs')">清空日志</button>
          </template>
          <template v-else-if="tool.key === 'pcd_tile'">
            <button class="secondary-btn" type="button" @click="previewTile">预扫描</button>
            <button class="secondary-btn" type="button" @click="openOutputDir">打开输出目录</button>
            <button class="secondary-btn" type="button" @click="emit('clearLogs')">清空日志</button>
          </template>
          <template v-else-if="tool.key === 'costmap'">
            <button class="secondary-btn" type="button" @click="openOutputDir">打开导出目录</button>
            <button class="secondary-btn" type="button" @click="emit('clearLogs')">清空日志</button>
          </template>
          <template v-else-if="tool.key === 'ros_nav_test'">
            <button class="secondary-btn" type="button" :disabled="rosDataSourceSaving" @click="saveRosNavConfig">
              {{ rosDataSourceSaving ? "保存中..." : "保存接入配置" }}
            </button>
            <button class="secondary-btn" type="button" :disabled="rosInspectLoading" @click="inspectRosNavSource">
              {{ rosInspectLoading ? "检测中..." : "检测接入方式" }}
            </button>
            <button class="secondary-btn" type="button" :disabled="rosTopicsLoading" @click="refreshRosTopics">
              {{ rosTopicsLoading ? "刷新中..." : "刷新话题" }}
            </button>
            <button class="secondary-btn" type="button" @click="openOutputDir">打开快照目录</button>
            <button class="secondary-btn" type="button" @click="emit('clearLogs')">清空日志</button>
          </template>
          <template v-else-if="tool.key === 'mtslash_export'">
            <button class="secondary-btn" type="button" :disabled="mtslashCaptchaLoading" @click="fetchCaptcha">
              {{ mtslashCaptchaLoading ? "获取中..." : "获取验证码" }}
            </button>
            <button class="secondary-btn" type="button" :disabled="mtslashLoginLoading" @click="loginMtslashSession">
              {{ mtslashLoginLoading ? "登录中..." : "登录" }}
            </button>
            <button class="secondary-btn" type="button" :disabled="mtslashFavoritesLoading" @click="loadMtslashFavorites">
              {{ mtslashFavoritesLoading ? "加载中..." : "加载收藏夹" }}
            </button>
            <button class="secondary-btn" type="button" :disabled="mtslashBrowserLoading" @click="startMtslashBrowserMode">
              {{ mtslashBrowserLoading ? "处理中..." : "启动浏览器模式" }}
            </button>
            <button class="secondary-btn" type="button" @click="openOutputDir">打开输出目录</button>
            <button class="secondary-btn" type="button" @click="emit('clearLogs')">清空日志</button>
          </template>
        </div>
      </section>

      <template v-if="tool.key === 'pcd_map'">
        <section class="result-panel">
          <div class="result-title">地图结果</div>
          <p class="summary">{{ summary }}</p>
          <div class="stat-strip">
            <div class="stat-chip">
              <span class="stat-chip-label">点数</span>
              <strong>{{ props.resultData.point_count || "0" }}</strong>
            </div>
            <div class="stat-chip">
              <span class="stat-chip-label">可行走格</span>
              <strong>{{ props.resultData.walkable_cells || "0" }}</strong>
            </div>
            <div class="stat-chip">
              <span class="stat-chip-label">障碍格</span>
              <strong>{{ props.resultData.obstacle_cells || "0" }}</strong>
            </div>
          </div>
        </section>

        <section class="panel pcd-map-preview-panel">
          <div class="section-head">
            <div>
              <div class="result-title">绿道预览</div>
              <div class="section-subtitle">优先显示带黑底预览图，没有则显示透明绿道图</div>
            </div>
          </div>

          <div class="pcd-map-preview-wrap">
            <img v-if="pcdMapImageUrl" :src="pcdMapImageUrl" class="pcd-map-preview-image" alt="绿道预览" />
            <div v-else class="pcd-map-preview-empty">执行生成后在这里显示绿道预览</div>
          </div>

          <div class="kv-list">
            <div class="kv-item">
              <span class="kv-key">PGM</span>
              <span class="kv-value">{{ props.resultData.pgm_path || "等待生成" }}</span>
            </div>
            <div class="kv-item">
              <span class="kv-key">YAML</span>
              <span class="kv-value">{{ props.resultData.yaml_path || "等待生成" }}</span>
            </div>
            <div class="kv-item">
              <span class="kv-key">绿道 PNG</span>
              <span class="kv-value">{{ props.resultData.color_path || "等待生成" }}</span>
            </div>
            <div class="kv-item">
              <span class="kv-key">预览 PNG</span>
              <span class="kv-value">{{ props.resultData.preview_path || "等待生成" }}</span>
            </div>
          </div>
        </section>
      </template>

      <template v-else-if="tool.key === 'network_scan'">
        <section class="result-panel">
          <div class="result-title">扫描概览</div>
          <p class="summary">{{ summary }}</p>
          <div class="stat-strip">
            <div class="stat-chip">
              <span class="stat-chip-label">结果数</span>
              <strong>{{ filteredNetworkRows.length }}</strong>
            </div>
            <div class="stat-chip">
              <span class="stat-chip-label">在线数</span>
              <strong>{{ networkRows.filter((row) => row.status === 'reachable' || row.status === '在线').length }}</strong>
            </div>
            <div class="stat-chip">
              <span class="stat-chip-label">本机 IP</span>
              <strong>{{ props.resultData.local_ip || "未知" }}</strong>
            </div>
          </div>
        </section>

        <section class="panel network-panel">
          <div class="section-head">
            <div class="result-title">扫描结果</div>
            <div class="network-tools">
              <input v-model="networkMacFilter" class="field-input compact-input" placeholder="MAC关键字过滤" />
              <input v-model="networkKeyword" class="field-input compact-input" placeholder="关键字搜索" />
              <label class="check-inline">
                <input v-model="networkOnlyAlive" type="checkbox" />
                <span>仅显示在线</span>
              </label>
              <button class="secondary-btn" type="button" @click="exportNetworkCsv">导出 CSV</button>
            </div>
          </div>
          <div class="network-table-wrap">
            <table class="network-table">
              <thead>
                <tr>
                  <th>IP</th>
                  <th>状态</th>
                  <th>延迟(ms)</th>
                  <th>主机名</th>
                  <th>MAC</th>
                  <th>ARP类型</th>
                  <th>SSH(22)</th>
                  <th>备注</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in filteredNetworkRows" :key="`${row.ip}-${row.note}`">
                  <td>{{ row.ip }}</td>
                  <td>{{ row.status }}</td>
                  <td>{{ row.latency }}</td>
                  <td>{{ row.hostname }}</td>
                  <td>{{ row.mac }}</td>
                  <td>{{ row.arp_type }}</td>
                  <td>{{ row.port_22 }}</td>
                  <td>{{ row.note }}</td>
                </tr>
                <tr v-if="filteredNetworkRows.length === 0">
                  <td colspan="8" class="empty-cell">运行后将在这里显示扫描结果</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      </template>

      <template v-else-if="tool.key === 'pcd_tile'">
        <section class="result-panel">
          <div class="result-title">预扫描信息</div>
          <pre class="logs helper-logs">{{ tilePreview || "点击“预扫描”后显示点数、范围和预计 tile 数。" }}</pre>
        </section>

        <section class="panel helper-panel">
          <div class="result-title">输出信息</div>
          <div class="kv-list">
            <div class="kv-item">
              <span class="kv-key">Metadata 文件</span>
              <span class="kv-value">{{ parsedPairs.metadata_path || "等待执行" }}</span>
            </div>
            <div class="kv-item">
              <span class="kv-key">Tile 数量</span>
              <span class="kv-value">{{ parsedPairs.tile_count || "0" }}</span>
            </div>
            <div class="kv-item">
              <span class="kv-key">执行摘要</span>
              <span class="kv-value">{{ parsedPairs.summary || summary || "等待执行" }}</span>
            </div>
          </div>
        </section>
      </template>

      <template v-else-if="tool.key === 'costmap'">
        <section class="result-panel">
          <div class="result-title">回放概览</div>
          <p class="summary">{{ summary }}</p>
          <div class="stat-strip">
            <div class="stat-chip">
              <span class="stat-chip-label">帧数量</span>
              <strong>{{ props.resultData.frame_count || costmapFrames.length || "0" }}</strong>
            </div>
            <div class="stat-chip">
              <span class="stat-chip-label">当前帧</span>
              <strong>{{ costmapFrames.length ? `${costmapFrameIndex + 1} / ${costmapFrames.length}` : "0 / 0" }}</strong>
            </div>
            <div class="stat-chip">
              <span class="stat-chip-label">摘要文件</span>
              <strong>{{ props.resultData.summary_path || "未生成" }}</strong>
            </div>
          </div>
        </section>

        <section class="panel costmap-player-panel">
          <div class="section-head">
            <div>
              <div class="result-title">Costmap 播放器</div>
              <div class="section-subtitle">Canvas 预览，支持播放、帧切换、阈值高亮和 Footprint</div>
            </div>
            <div class="costmap-actions">
              <button class="secondary-btn" type="button" @click="playCostmap">播放</button>
              <button class="secondary-btn" type="button" @click="pauseCostmap">暂停</button>
              <button class="secondary-btn" type="button" @click="prevCostmapFrame">上一帧</button>
              <button class="secondary-btn" type="button" @click="nextCostmapFrame">下一帧</button>
              <button class="secondary-btn" type="button" @click="exportCurrentCostmapPng">导出当前 PNG</button>
            </div>
          </div>

          <div class="costmap-viewer">
            <div class="costmap-canvas-wrap">
              <canvas ref="costmapCanvas" class="costmap-canvas"></canvas>
              <div v-if="costmapFrames.length === 0" class="costmap-empty">
                加载 Costmap YAML 后显示回放预览
              </div>
            </div>
            <pre class="logs costmap-info">{{ costmapFrameInfo }}</pre>
          </div>

          <div class="costmap-slider-row">
            <input
              v-model.number="costmapFrameIndex"
              class="costmap-slider"
              type="range"
              min="0"
              :max="Math.max(0, costmapFrames.length - 1)"
              step="1"
            />
            <span>{{ costmapFrames.length ? `${costmapFrameIndex + 1} / ${costmapFrames.length}` : "0 / 0" }}</span>
            <span>{{ costmapPlaying ? "播放中" : "已暂停" }}</span>
          </div>

          <div v-if="props.resultData.export_paths?.length" class="costmap-export-list">
            <span class="kv-key">已导出:</span>
            <span v-for="path in props.resultData.export_paths" :key="path" class="kv-value">{{ path }}</span>
          </div>
        </section>

        <section class="panel costmap-guide-panel">
          <div class="section-head">
            <div>
              <div class="result-title">录制 costmap.yaml 方法</div>
              <div class="section-subtitle">当前播放器读取的是 nav_msgs/OccupancyGrid 导出的 YAML 多文档格式</div>
            </div>
          </div>

          <div class="costmap-guide-grid">
            <div class="costmap-guide-card">
              <div class="guide-step">1. 确认 Costmap Topic</div>
              <pre class="guide-code">ros2 topic list | grep costmap
ros2 topic echo /local_costmap/costmap --once</pre>
              <p>常见 topic 是 <code>/local_costmap/costmap</code> 或 <code>/global_costmap/costmap</code>，以你机器人实际输出为准。</p>
            </div>

            <div class="costmap-guide-card">
              <div class="guide-step">2. 直接录成 YAML</div>
              <pre class="guide-code">ros2 topic echo /local_costmap/costmap &gt; costmap.yaml</pre>
              <p>开始命令后让机器人运行一段时间，按 <code>Ctrl + C</code> 停止。生成的 <code>costmap.yaml</code> 可以直接在本页面加载。</p>
            </div>

            <div class="costmap-guide-card">
              <div class="guide-step">3. 推荐先录 Bag 再导出</div>
              <pre class="guide-code">ros2 bag record /local_costmap/costmap -o costmap_bag
ros2 bag play costmap_bag
ros2 topic echo /local_costmap/costmap &gt; costmap.yaml</pre>
              <p>这种方式更稳，现场先保存原始 bag，后续可以反复导出不同片段。</p>
            </div>

            <div class="costmap-guide-card">
              <div class="guide-step">4. 文件格式要求</div>
              <pre class="guide-code">header:
  stamp:
    sec: 0
    nanosec: 0
info:
  width: 100
  height: 100
  resolution: 0.05
data: [0, 0, 100, ...]</pre>
              <p>每帧需要包含 <code>info.width</code>、<code>info.height</code>、<code>info.resolution</code> 和 <code>data</code>。多帧 YAML 通常用 <code>---</code> 分隔。</p>
            </div>
          </div>
        </section>
      </template>

      <template v-else-if="tool.key === 'ros_nav_test'">
        <section class="result-panel nav-overview-panel">
          <div class="result-title">测试工作台概览</div>
          <p class="summary">这一版先确认导航测试页布局，后续再逐步接入 ROS 话题订阅、三维渲染和实际小窗内容。</p>
          <div class="stat-strip">
            <div class="stat-chip">
              <span class="stat-chip-label">固定坐标系</span>
              <strong>{{ formValues.fixed_frame || "map" }}</strong>
            </div>
            <div class="stat-chip">
              <span class="stat-chip-label">候选 Topic</span>
              <strong>{{ rosTopicOptions.length }}</strong>
            </div>
            <div class="stat-chip">
              <span class="stat-chip-label">侧边/完整小窗</span>
              <strong>{{ navActiveSidePanelCount }} / {{ navSidePanels.length }} · {{ navActiveFullPanelCount }} / {{ navFullPanels.length }}</strong>
            </div>
          </div>
          <div class="nav-control-card">
            <div class="nav-control-card-head">
              <div class="result-title">定位与导航控制</div>
              <div class="section-subtitle">参考 RViz 交互方式，在主视图点击并拖动方向后下发。</div>
            </div>

            <div class="nav-control-grid">
              <button class="primary-btn" type="button" :disabled="navControlLoading" @click="enterInitialPoseMode">
                {{ navInteractionMode === "initialpose" ? "退出初始化定位" : "初始化定位" }}
              </button>
              <button class="primary-btn" type="button" :disabled="navControlLoading" @click="enterNavGoalMode">
                {{ navInteractionMode === "navgoal" ? "退出导航目标" : "导航目标" }}
              </button>
              <button class="secondary-btn" type="button" :disabled="navControlLoading" @click="sendNavControlCommand('pause')">暂停</button>
              <button class="secondary-btn" type="button" :disabled="navControlLoading" @click="sendNavControlCommand('resume')">继续</button>
              <button class="secondary-btn" type="button" :disabled="navControlLoading" @click="sendNavControlCommand('cancel')">取消</button>
            </div>
          </div>
          <div class="section-subtitle nav-control-feedback">
            {{ navControlMessage || "可在这里进入初始化定位/导航目标模式，然后在三维主视图中点击并拖动方向，按 RViz 方式下发。" }}
          </div>
        </section>

        <section class="panel nav-main-view-panel">
          <div class="section-head">
            <div>
              <div class="result-title">三维主视图</div>
              <div class="section-subtitle">当前支持 Map / TF / Path / Pose 四类常用显示项，交互方式按 RViz 的“添加显示项”思路组织。</div>
            </div>
            <div class="nav-main-view-actions">
              <div class="nav-view-tags">
                <span class="status-pill">地图</span>
                <span class="status-pill">定位</span>
                <span class="status-pill">路径</span>
                <span class="status-pill">TF</span>
              </div>
              <button class="secondary-btn" type="button" @click="toggleNavDisplayManager">
                {{ navDisplayManagerLabel }}
              </button>
            </div>
          </div>

          <div class="nav-display-summary-row">
            <span class="nav-display-summary-text">当前主视图显示 {{ navMainDisplays.length }} 项</span>
            <div class="nav-display-summary-chips">
              <span v-for="display in navMainDisplays" :key="display.topic" class="nav-display-summary-chip">{{ display.label }}</span>
              <span v-if="navMainDisplays.length === 0" class="nav-display-summary-chip muted">暂无显示项</span>
            </div>
          </div>

          <div v-if="!navDisplayManagerCollapsed" class="nav-display-strip">
            <div v-for="display in navMainDisplays" :key="display.topic" class="nav-display-chip">
              <div class="nav-display-chip-main">
                <strong>{{ display.label }}</strong>
                <span>{{ display.messageType }}</span>
              </div>
              <div v-if="display.kind === 'pointcloud'" class="nav-display-config-row">
                <label class="nav-display-config-item">
                  <span class="kv-key">颜色</span>
                  <input
                    class="nav-display-color-input"
                    type="color"
                    :value="display.color ?? '#ffffff'"
                    @input="updateMainDisplayColor(display.topic, ($event.target as HTMLInputElement).value)"
                  />
                </label>
                <label class="nav-display-config-item">
                  <span class="kv-key">点大小</span>
                  <input
                    class="field-input nav-display-config-input"
                    type="number"
                    min="0.01"
                    max="0.6"
                    step="0.01"
                    :value="display.pointSize ?? 0.08"
                    @input="updateMainDisplayPointSize(display.topic, ($event.target as HTMLInputElement).value)"
                  />
                </label>
                <label class="nav-display-config-item">
                  <span class="kv-key">Hz 限制</span>
                  <input
                    class="field-input nav-display-config-input"
                    type="number"
                    min="0"
                    max="60"
                    step="1"
                    :value="display.hzLimit ?? 5"
                    @input="updateMainDisplayHzLimit(display.topic, ($event.target as HTMLInputElement).value)"
                  />
                </label>
              </div>
              <div v-else-if="display.kind === 'tf'" class="nav-display-tf-config">
                <div class="nav-display-config-row tf">
                  <label class="nav-display-config-item nav-display-check-item">
                    <span class="kv-key">显示名字</span>
                    <input
                      type="checkbox"
                      :checked="display.tfShowNames !== false"
                      @change="updateMainDisplayTfShowNames(display.topic, ($event.target as HTMLInputElement).checked)"
                    />
                  </label>
                  <label class="nav-display-config-item">
                    <span class="kv-key">名字大小</span>
                    <input
                      class="field-input nav-display-config-input"
                      type="number"
                      min="0.2"
                      max="2"
                      step="0.1"
                      :value="display.tfLabelSize ?? 0.5"
                      @input="updateMainDisplayTfLabelSize(display.topic, ($event.target as HTMLInputElement).value)"
                    />
                  </label>
                </div>
                <div class="nav-tf-frame-filter">
                  <div class="nav-tf-frame-filter-head">
                    <span class="kv-key">TF 节点筛选</span>
                    <button class="secondary-btn small" type="button" @click="showAllMainDisplayTfFrames(display.topic)">显示全部</button>
                  </div>
                  <div v-if="tfFramesForDisplay(display.topic).length > 0" class="nav-tf-frame-chip-list">
                    <button
                      v-for="frameName in tfFramesForDisplay(display.topic)"
                      :key="frameName"
                      class="nav-tf-frame-chip"
                      :class="{ active: isTfFrameSelected(display, frameName) }"
                      type="button"
                      @click="toggleMainDisplayTfFrame(display.topic, frameName)"
                    >
                      {{ frameName }}
                    </button>
                  </div>
                  <div v-else class="section-subtitle">连接后读取 TF 节点列表。</div>
                </div>
              </div>
              <button class="section-card-action danger" type="button" @click="removeMainDisplay(display.topic)">移除</button>
            </div>
            <div v-if="navMainDisplays.length === 0" class="section-empty">当前没有主视图显示项，请从右侧话题列表中添加。</div>
          </div>

          <Nav3DViewer
            :provider="formValues.ros_provider || 'rosbridge'"
            :url="formValues.ros_bridge_url || ''"
            :timeout-ms="Number(formValues.timeout_ms || '2500')"
            :fixed-frame="formValues.fixed_frame || 'map'"
            :displays="navMainDisplays"
            :interaction-mode="navInteractionMode"
            @interaction-complete="handleNavViewerInteraction"
            @tf-frames-change="handleTfFramesChange"
          />
        </section>

        <section class="panel nav-topic-picker-panel">
          <div class="section-head">
            <div>
              <div class="result-title">话题选择小窗</div>
              <div class="section-subtitle">支持逐项直接添加，也保留批量选择；列表内部滚动，避免整页被 topic 拉太长。</div>
            </div>
          </div>

          <div class="nav-topic-search-row">
            <input v-model="rosTopicQuery" class="field-input" placeholder="搜索 topic / 类型 / 说明" />
            <button class="secondary-btn" type="button" :disabled="rosTopicsLoading" @click="refreshRosTopics">
              {{ rosTopicsLoading ? "刷新中..." : "刷新话题" }}
            </button>
          </div>

          <div class="section-subtitle nav-topic-feedback">
            {{ rosTopicsMessage || "优先尝试通过后端 ROS 数据层读取真实话题；失败时会回退到内置示例话题。" }}
          </div>

          <div class="nav-topic-batch-bar">
            <span class="nav-topic-batch-text">已勾选 {{ selectedNavTopicOptions.length }} 项</span>
            <button class="primary-btn" type="button" :disabled="selectedNavTopicOptions.length === 0" @click="addSelectedTopicsToMainView">批量加到主视窗</button>
            <button class="secondary-btn" type="button" :disabled="selectedNavTopicOptions.length === 0" @click="addSelectedTopicsAsSidePanels">批量简易展示</button>
            <button class="secondary-btn" type="button" :disabled="selectedNavTopicOptions.length === 0" @click="addSelectedTopicsAsFullPanels">批量完整展示</button>
          </div>

          <div class="nav-topic-list">
            <label v-for="topic in filteredRosTopicOptions" :key="topic.key" class="nav-topic-item">
              <div class="nav-topic-item-main">
                <input v-model="selectedNavTopics" type="checkbox" :value="topic.key" />
                <div class="nav-topic-text">
                  <strong>{{ topic.key }}</strong>
                  <span>{{ topic.label }} / {{ topic.type }}</span>
                </div>
              </div>
              <div class="nav-topic-item-actions">
                <button
                  class="primary-btn"
                  type="button"
                  :disabled="hasMainDisplay(topic.key)"
                  @click.prevent="addTopicToMainView(topic)"
                >
                  {{ hasMainDisplay(topic.key) ? "已在主视窗" : "加到主视窗" }}
                </button>
                <button
                  class="secondary-btn"
                  type="button"
                  :disabled="hasSidePanel(topic.key)"
                  @click.prevent="addTopicAsSidePanel(topic)"
                >
                  {{ hasSidePanel(topic.key) ? "已简易展示" : "简易展示" }}
                </button>
                <button
                  class="secondary-btn"
                  type="button"
                  :disabled="hasFullPanel(topic.key)"
                  @click.prevent="addTopicAsFullPanel(topic)"
                >
                  {{ hasFullPanel(topic.key) ? "已完整展示" : "完整展示" }}
                </button>
              </div>
              <span class="nav-topic-note">{{ topic.note }}</span>
            </label>
            <div v-if="filteredRosTopicOptions.length === 0" class="section-empty">当前筛选条件下没有 topic</div>
          </div>
        </section>

        <section class="panel nav-status-panel">
          <div class="section-head">
            <div>
              <div class="result-title">主视图状态</div>
              <div class="section-subtitle">这里同时展示数据层检测结果，便于判断机器狗当前到底暴露了什么接入方式。</div>
            </div>
          </div>

          <div class="kv-list">
            <div class="kv-item">
              <span class="kv-key">接入方式</span>
              <span class="kv-value">{{ formValues.ros_provider || "rosbridge" }}</span>
            </div>
            <div class="kv-item">
              <span class="kv-key">Bridge 地址</span>
              <span class="kv-value">{{ formValues.ros_bridge_url || "未配置" }}</span>
            </div>
            <div class="kv-item">
              <span class="kv-key">地图 Topic</span>
              <span class="kv-value">{{ formValues.map_topic || "/debug/loaded_pointcloud_map" }}</span>
            </div>
            <div class="kv-item">
              <span class="kv-key">定位 Topic</span>
              <span class="kv-value">{{ formValues.pose_topic || "/ndt_pose" }}</span>
            </div>
            <div class="kv-item">
              <span class="kv-key">计划路径 Topic</span>
              <span class="kv-value">{{ formValues.path_topic || "/plan" }}</span>
            </div>
            <div class="kv-item">
              <span class="kv-key">已选 Topic</span>
              <span class="kv-value">{{ selectedNavTopicOptions.map((item) => item.key).join("、") || "暂未临时选择" }}</span>
            </div>
          </div>

          <div class="nav-detection-card">
            <div class="result-title nav-detection-title">接入检测结果</div>
            <p class="summary">{{ rosInspectResult?.message || "点击“检测接入方式”后，这里会显示当前桥接能力、可用提示和 topic 检测结果。" }}</p>
            <div class="nav-detection-meta">
              <span class="status-pill" :class="{ success: rosInspectResult?.status === 'success' }">{{ rosInspectResult?.status || "未检测" }}</span>
              <span class="nav-detection-count">topics: {{ rosInspectResult?.topics_count ?? 0 }}</span>
            </div>
            <div v-if="rosInspectResult?.capabilities?.length" class="nav-capability-list">
              <span v-for="capability in rosInspectResult.capabilities" :key="capability" class="nav-capability-chip">{{ capability }}</span>
            </div>
            <ul v-if="rosInspectResult?.detected_hints?.length" class="nav-hints-list">
              <li v-for="hint in rosInspectResult.detected_hints" :key="hint">{{ hint }}</li>
            </ul>
          </div>
        </section>

        <section class="panel nav-side-monitor-panel">
          <div class="section-head">
            <div>
              <div class="result-title">侧边小窗</div>
              <div class="section-subtitle">右侧紧凑监控区只保留题目和图表/消息，方便同屏看更多实时数据。</div>
            </div>
          </div>

          <NavTopicPanelList
            :provider="formValues.ros_provider || 'rosbridge'"
            :url="formValues.ros_bridge_url || ''"
            :timeout-ms="Number(formValues.timeout_ms || '2500')"
            :panels="navSidePanels"
            :compact="true"
            @toggle="toggleNavSidePanel"
            @remove="removeNavSidePanel"
            @update-config="updateNavSidePanelConfig"
            @recording-saved="loadNavRecordingFiles"
          />
        </section>

        <section class="panel nav-recordings-panel-shell">
          <div class="nav-recordings-panel">
            <div class="section-head">
              <div>
                <div class="result-title">录制文件</div>
                <div class="section-subtitle">固定读取录制目录中的文本和图片，便于回看和整理。</div>
              </div>
              <div class="nav-recordings-actions">
                <button class="secondary-btn" type="button" :disabled="navRecordingFilesLoading" @click="loadNavRecordingFiles">
                  {{ navRecordingFilesLoading ? "刷新中..." : "刷新文件" }}
                </button>
                <button class="secondary-btn" type="button" @click="openLocalPath(navRecordingFilesDirectory || 'G:/ros_proj/ros_tool/output_nav/recordings')">
                  打开目录
                </button>
              </div>
            </div>

            <div class="section-subtitle nav-topic-feedback">
              {{ navRecordingFilesMessage || "录制停止后会在固定目录中生成录制文本文件；若文本中包含指标数据，这里会自动生成可交互图表。" }}
            </div>

            <div class="nav-recordings-browser">
              <div class="nav-recordings-filelist">
                <div
                  v-for="item in navRecordingFiles"
                  :key="item.path"
                  class="nav-recordings-fileitem"
                  :class="{ active: navRecordingPreviewPath === item.path }"
                >
                  <button class="nav-recordings-filemain" type="button" @click="previewNavRecordingFile(item)">
                    <span class="nav-recordings-filemeta">
                      <strong>{{ item.name }}</strong>
                      <span>{{ item.modified_at }} · {{ item.kind }}</span>
                    </span>
                  </button>
                  <span class="nav-recordings-filemeta">
                    <button class="secondary-btn small" type="button" @click.stop="removeNavRecordingFile(item.path)">删除</button>
                  </span>
                </div>
                <div v-if="navRecordingFiles.length === 0" class="section-empty">当前没有录制文件。</div>
              </div>

              <div class="nav-recordings-preview">
                <img
                  v-if="navRecordingPreviewKind === 'image' && navRecordingPreviewPath"
                  class="nav-recordings-preview-image"
                  :src="buildBackendImageUrl(navRecordingPreviewPath)"
                  alt="录制图片预览"
                />
                <template v-else-if="navRecordingPreviewKind === 'text' && navRecordingPreviewPath">
                  <pre class="logs nav-recordings-preview-text">{{ navRecordingPreviewText }}</pre>
                  <div v-if="navRecordingParsedPayload?.metric_series?.length" class="nav-recordings-chart">
                    <div class="nav-recordings-chart-head">
                      <div class="result-title">录制图表</div>
                      <div class="nav-recordings-chart-actions">
                        <button
                          v-for="metric in navRecordingParsedPayload.metric_series"
                          :key="metric.label"
                          class="nav-recordings-chart-chip"
                          :class="{ active: navRecordingChartMetricLabel === metric.label }"
                          type="button"
                          @click="setNavRecordingMetric(metric.label)"
                        >
                          {{ metric.label }}
                        </button>
                        <button class="secondary-btn small" type="button" @click="zoomNavRecordingChart(0.8)">放大</button>
                        <button class="secondary-btn small" type="button" @click="zoomNavRecordingChart(1.25)">缩小</button>
                        <button class="secondary-btn small" type="button" @click="resetNavRecordingChartState(navRecordingParsedPayload)">重置</button>
                      </div>
                    </div>
                    <div class="section-subtitle">
                      X 轴单位为毫秒；滚轮缩放，按住拖动可横向平移。
                    </div>
                    <div
                      class="nav-recordings-chart-canvas"
                      @wheel.prevent="handleNavRecordingChartWheel"
                      @pointerdown="handleNavRecordingChartPointerDown"
                      @pointermove="handleNavRecordingChartPointerMove"
                      @pointerup="stopNavRecordingChartDrag"
                      @pointerleave="stopNavRecordingChartDrag"
                    >
                      <div v-if="navRecordingChartHover" class="nav-recordings-chart-tooltip">
                        <strong>{{ navRecordingChartTimeText(navRecordingChartHover.offsetMs) }}</strong>
                        <span>{{ activeNavRecordingMetric?.label }}: {{ navRecordingChartHover.value.toFixed(3) }}</span>
                      </div>
                      <svg class="nav-recordings-chart-svg" viewBox="0 0 1000 220" preserveAspectRatio="none">
                        <line x1="0" y1="190" x2="1000" y2="190" stroke="#21334d" stroke-width="1" />
                        <line x1="0" y1="24" x2="0" y2="190" stroke="#21334d" stroke-width="1" />
                        <polyline
                          v-if="activeNavRecordingMetricSamples.length"
                          :points="navRecordingChartPolylinePoints()"
                          :stroke="activeNavRecordingMetric?.color || '#2f8cff'"
                          stroke-width="2"
                          fill="none"
                          stroke-linecap="round"
                          stroke-linejoin="round"
                          vector-effect="non-scaling-stroke"
                        />
                        <line
                          v-if="navRecordingChartHover"
                          :x1="navRecordingChartHover.x"
                          :x2="navRecordingChartHover.x"
                          y1="24"
                          y2="190"
                          stroke="#8ea1ba"
                          stroke-dasharray="4 4"
                          stroke-width="1"
                        />
                      </svg>
                    </div>
                    <div class="nav-recordings-chart-axis">
                      <span>{{ navRecordingChartRangeStart }} ms</span>
                      <span>{{ navRecordingChartRangeEnd }} ms</span>
                    </div>
                  </div>
                </template>
                <div v-else class="section-empty">选择一个录制文件后，这里会显示文本或图片预览。</div>
              </div>
            </div>
          </div>
        </section>

        <section class="panel nav-panel-list-panel">
          <div class="section-head">
            <div>
              <div class="result-title">完整小窗列表</div>
              <div class="section-subtitle">这里保留更大的卡片视图，方便完整查看折线和消息内容。</div>
            </div>
          </div>

          <NavTopicPanelList
            :provider="formValues.ros_provider || 'rosbridge'"
            :url="formValues.ros_bridge_url || ''"
            :timeout-ms="Number(formValues.timeout_ms || '2500')"
            :panels="navFullPanels"
            @toggle="toggleNavFullPanel"
            @remove="removeNavFullPanel"
            @update-config="updateNavFullPanelConfig"
            @recording-saved="loadNavRecordingFiles"
          />
        </section>

      </template>

      <template v-else-if="tool.key === 'mtslash_export'">
        <div class="mtslash-left-stack">
          <section class="panel tool-form-panel">
            <div class="section-head">
              <div class="result-title">参数配置</div>
              <div class="section-subtitle">支持手动输入和本地浏览选择</div>
            </div>

            <div class="grid-form">
              <label v-for="field in tool.fields" v-show="fieldKind(field.key) !== 'hidden'" :key="field.key" class="field">
                <span class="field-label">{{ field.label }}</span>
                <div class="field-row">
                  <select
                    v-if="fieldKind(field.key) === 'select-format'"
                    v-model="formValues[field.key]"
                    class="field-input"
                  >
                    <option value="ascii">ASCII</option>
                    <option value="binary">Binary</option>
                  </select>
                  <select
                    v-else-if="fieldKind(field.key) === 'select-bool'"
                    v-model="formValues[field.key]"
                    class="field-input"
                  >
                    <option value="false">否</option>
                    <option value="true">是</option>
                  </select>
                  <select
                    v-else-if="fieldKind(field.key) === 'select-browser'"
                    v-model="formValues[field.key]"
                    class="field-input"
                  >
                    <option value="edge">Edge</option>
                    <option value="chrome">Chrome</option>
                  </select>
                  <input
                    v-else
                    v-model="formValues[field.key]"
                    class="field-input"
                    :type="fieldKind(field.key) === 'password' ? 'password' : 'text'"
                    :placeholder="field.placeholder"
                  />
                  <button
                    v-if="getBrowseMode(field.key, field.label)"
                    class="field-browse-btn"
                    type="button"
                    @click="browseField(field.key, field.label)"
                  >
                    选择
                  </button>
                </div>
              </label>
            </div>

            <div class="actions">
              <button class="primary-btn" :disabled="loading" @click="submit">
                {{ loading ? "处理中..." : tool.primary_action }}
              </button>
              <button class="secondary-btn" type="button" :disabled="mtslashCaptchaLoading" @click="fetchCaptcha">
                {{ mtslashCaptchaLoading ? "获取中..." : "获取验证码" }}
              </button>
              <button class="secondary-btn" type="button" :disabled="mtslashLoginLoading" @click="loginMtslashSession">
                {{ mtslashLoginLoading ? "登录中..." : "登录" }}
              </button>
              <button class="secondary-btn" type="button" :disabled="mtslashFavoritesLoading" @click="loadMtslashFavorites">
                {{ mtslashFavoritesLoading ? "加载中..." : "加载收藏夹" }}
              </button>
              <button class="secondary-btn" type="button" :disabled="mtslashBrowserLoading" @click="startMtslashBrowserMode">
                {{ mtslashBrowserLoading ? "处理中..." : "启动浏览器模式" }}
              </button>
              <button class="secondary-btn" type="button" @click="openOutputDir">打开输出目录</button>
              <button class="secondary-btn" type="button" @click="emit('clearLogs')">清空日志</button>
            </div>
          </section>

          <section class="panel mtslash-login-panel">
            <div class="section-head">
              <div>
                <div class="result-title">一次性登录</div>
                <div class="section-subtitle">验证码必须人工输入；登录失败不会自动重试，账号有 60 秒冷却。</div>
              </div>
            </div>
            <div class="mtslash-login-box">
              <div class="captcha-frame">
                <img v-if="mtslashCaptchaImage" :src="mtslashCaptchaImage" alt="验证码" />
                <span v-else>点击“获取验证码”后显示图片</span>
              </div>
              <div>
                <div class="status-pill" :class="{ success: mtslashLoggedIn }">
                  {{ mtslashLoggedIn ? "已登录" : "未登录" }}
                </div>
                <p class="summary">{{ mtslashLoginMessage || "可继续使用 Cookie；不填 Cookie 时，先获取验证码并登录，再导出。" }}</p>
              </div>
            </div>
          </section>

          <section class="panel mtslash-progress-panel">
            <div class="section-head">
              <div>
                <div class="result-title">处理进度</div>
                <div class="section-subtitle">{{ mtslashExportModeLabel }}</div>
              </div>
              <div class="status-pill" :class="{ success: !loading && Boolean(props.resultData.output_path) }">
                {{ loading ? "导出中" : props.resultData.output_path ? "已完成" : "待处理" }}
              </div>
            </div>
            <div class="mtslash-progress-track" :class="{ active: loading }">
              <div class="mtslash-progress-bar"></div>
            </div>
            <p class="summary mtslash-progress-text">{{ mtslashProgressText }}</p>
          </section>
        </div>

        <div class="mtslash-right-stack">
          <section class="panel mtslash-favorites-panel">
            <div class="section-head">
              <div>
                <div class="result-title">收藏夹</div>
                <div class="section-subtitle">从当前登录用户收藏夹读取帖子，点击行可填入帖子 URL。</div>
              </div>
              <div class="mtslash-favorites-tools">
                <input v-model="mtslashFavoritesKeyword" class="field-input compact-input mtslash-search-input" placeholder="搜索标题或链接" />
                <button class="secondary-btn" type="button" :disabled="mtslashFavoritesLoading" @click="loadMtslashFavorites">
                  {{ mtslashFavoritesLoading ? "加载中..." : "刷新" }}
                </button>
                <button class="secondary-btn" type="button" :disabled="mtslashFavoritesPage <= 1" @click="prevMtslashFavoritesPage">上一页</button>
                <button class="secondary-btn" type="button" :disabled="mtslashFavoritesPage >= filteredMtslashFavoriteTotalPages" @click="nextMtslashFavoritesPage">下一页</button>
              </div>
            </div>
            <div class="section-subtitle">
              {{ mtslashFavoritesMessage || `共 ${mtslashFavorites.length} 条，筛选 ${filteredMtslashFavorites.length} 条，当前第 ${mtslashFavoritesPage} / ${filteredMtslashFavoriteTotalPages} 页` }}
            </div>
            <div class="network-table-wrap mtslash-favorites-wrap">
              <table class="network-table mtslash-favorites-table">
                <thead>
                  <tr>
                    <th>帖子名</th>
                    <th>链接</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="item in pagedMtslashFavorites" :key="item.url" @click="selectMtslashFavorite(item)">
                    <td class="favorite-title" :title="item.title">{{ item.title }}</td>
                    <td class="favorite-url">{{ item.url }}</td>
                  </tr>
                  <tr v-if="pagedMtslashFavorites.length === 0">
                    <td colspan="2" class="empty-cell">登录后点击“加载收藏夹”，或调整搜索条件</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>

          <section class="panel mtslash-browser-panel">
            <div class="section-head">
              <div>
                <div class="result-title">浏览器标签页</div>
                <div class="section-subtitle">读取浏览器模式窗口中已打开的站内页面，点击行可填入帖子 URL。</div>
              </div>
              <div class="mtslash-favorites-tools">
                <input v-model="mtslashBrowserKeyword" class="field-input compact-input mtslash-search-input" placeholder="搜索标题或链接" />
                <button class="secondary-btn" type="button" :disabled="mtslashBrowserLoading" @click="startMtslashBrowserMode">
                  {{ mtslashBrowserLoading ? "处理中..." : "启动" }}
                </button>
                <button class="secondary-btn" type="button" :disabled="mtslashBrowserLoading" @click="loadMtslashBrowserTabs">
                  {{ mtslashBrowserLoading ? "刷新中..." : "刷新" }}
                </button>
                <button class="secondary-btn" type="button" :disabled="mtslashBrowserPage <= 1" @click="prevMtslashBrowserPage">上一页</button>
                <button class="secondary-btn" type="button" :disabled="mtslashBrowserPage >= filteredMtslashBrowserTotalPages" @click="nextMtslashBrowserPage">下一页</button>
              </div>
            </div>
            <div class="section-subtitle">
              {{ mtslashBrowserMessage || `共 ${mtslashBrowserTabs.length} 个，筛选 ${filteredMtslashBrowserTabs.length} 个，当前第 ${mtslashBrowserPage} / ${filteredMtslashBrowserTotalPages} 页` }}
            </div>
            <div class="network-table-wrap mtslash-favorites-wrap">
              <table class="network-table mtslash-favorites-table">
                <thead>
                  <tr>
                    <th>页面标题</th>
                    <th>链接</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="item in pagedMtslashBrowserTabs" :key="item.id || item.url" @click="selectMtslashBrowserTab(item)">
                    <td class="favorite-title" :title="item.title">{{ item.title }}</td>
                    <td class="favorite-url">{{ item.url }}</td>
                  </tr>
                  <tr v-if="pagedMtslashBrowserTabs.length === 0">
                    <td colspan="2" class="empty-cell">启动浏览器模式后，在该窗口打开站内帖子并点击刷新</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>

          <section class="result-panel">
            <div class="result-title">导出概览</div>
            <p class="summary">{{ summary }}</p>
            <div class="stat-strip">
              <div class="stat-chip">
                <span class="stat-chip-label">收录段落</span>
                <strong>{{ props.resultData.post_count || "0" }}</strong>
              </div>
              <div class="stat-chip">
                <span class="stat-chip-label">帖子标题</span>
                <strong>{{ props.resultData.title || "等待导出" }}</strong>
              </div>
              <div class="stat-chip">
                <span class="stat-chip-label">输出文件</span>
                <strong>{{ props.resultData.output_path || "未生成" }}</strong>
              </div>
            </div>
          </section>
        </div>
      </template>

      <template v-else>
        <section class="result-panel">
          <div class="result-title">输出摘要</div>
          <p class="summary">{{ summary }}</p>
        </section>
      </template>

      <section class="log-panel tool-log-panel">
        <div class="result-title">执行日志</div>
        <pre class="logs">{{ logs.join("\n") }}</pre>
      </section>
    </div>
  </div>
</template>
