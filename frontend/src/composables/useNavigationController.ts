// 功能说明：编排 ROS 接入、地图、定位控制、诊断和录制，供平台页面调用。
import type { TaskScene } from "../lib/navigationTasks";
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  reactive,
  watch,
} from "vue";
import {
  buildBackendImageUrl,
  browsePath,
  deleteNavRecording,
  fetchLocalTextFile,
  fetchNavRecordingFiles,
  fetchRosDataSourceConfig,
  fetchRosNavOfflineMapPreview,
  fetchRosRuntimeParams,
  fetchRosTopics,
  fetchPcdTilePreview,
  inspectRosDataSource,
  openLocalPath,
  saveNavRecording,
  saveRosDataSourceConfig,
} from "../api/client";
import type { NavOfflineMapPreviewResponse } from "../api/client";
import type {
  BrowseDialogPayload,
  NavRecordingFileItem,
  NavRecordingSavePayload,
  RosDataSourceConfig,
  RosInspectionResponse,
  RosRuntimeParamsResponse,
  RosTopicItem,
  ToolDefinition,
} from "../types";
import {
  buildDisplayLabel,
  inferDisplayKind,
  isPointCloudMessageType,
  type NavViewerDisplay,
} from "../lib/ros/displayRegistry";
import {
  inspectRosDataSourceDirect,
  listRosRuntimeParamsDirect,
  listRosTopicsDirect,
} from "../lib/ros/directRosClient";
import {
  createRosLiveAdapter,
  createSharedRosLiveAdapter,
  getSharedRosSessionStats,
  type RosSubscriptionOptions,
  type SharedRosSessionStats,
} from "../lib/ros/liveAdapter";
import {
  buildNativeOfflineMapPreview,
  canUseNativeRosFilePicker,
  pickNativeLocalFile,
} from "../lib/nativeFilePicker";
interface NavTopicOption {
  key: string;
  label: string;
  type: string;
  note: string;
}
interface InitialPoseCandidatePayload {
  x: number;
  y: number;
  z: number;
  roll: number;
  pitch: number;
  yaw: number;
}

type OfflineMapDisplayMode = "voxel" | "pointcloud" | "render";

interface Nav3DViewerComponentExpose extends TaskScene {
  focusOnNdtPose: () => { ok: boolean; message: string };
  attachOfflineMapPointCloud: (payload: NavOfflineMapPreviewResponse) => {
    ok: boolean;
    message: string;
  };
  clearOfflineMapPointCloud: () => void;
  setOfflineMapDisplayMode: (mode: OfflineMapDisplayMode) => {
    ok: boolean;
    message: string;
  };
  updateOfflineMapVisualSettings: (settings: {
    displayMode?: OfflineMapDisplayMode;
    pointSize?: number;
    pointColor?: string;
    voxelColor?: string;
  }) => void;
  attachInitialPosePointCloud: (payload: {
    topic: string;
    message: any;
    color?: string;
    pointSize?: number;
    pointColorMode?: "solid" | "layered";
  }) => { ok: boolean; message: string };
  updateInitialPosePointCloudSize: (pointSize: number) => {
    ok: boolean;
    message: string;
  };
  getInitialPoseCandidate: () => InitialPoseCandidatePayload | null;
  clearInitialPoseCandidate: () => void;
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
  navDelayTopicsText?: string;
  hasSidePanels?: boolean;
  hasFullPanels?: boolean;
  hasMainDisplays?: boolean;
  hasNavDelayTopicsText?: boolean;
}
interface NavDelayTopicDefinition {
  topic: string;
  messageType: string;
  label: string;
  color: string;
  resolved: boolean;
}

const ROS_NAV_LOCAL_CONFIG_KEY = "moontoolbox.rosPlatform.navConfig";
interface NavDelaySample {
  recvMs: number;
  stampMs: number;
  ageMs: number;
}
interface NavDelayTopicState {
  topic: string;
  label: string;
  messageType: string;
  color: string;
  lastStampMs: number | null;
  lastRecvMs: number | null;
  ageMs: number | null;
  hz: number;
  avgAgeMs10s: number | null;
  maxAgeMs10s: number | null;
  stampSecText: string;
  recvWallTimeText: string;
  points: string;
  sampleCount: number;
}
interface NavDelayAggregateLine {
  topic: string;
  label: string;
  color: string;
  points: string;
  ageMs: number | null;
  latestStampMs: number | null;
}
interface NavDelayRecordedMetricPoint {
  offsetMs: number;
  value: number;
}
interface NavDelayRecordedMetricSeries {
  label: string;
  unit: string;
  color: string;
  samples: NavDelayRecordedMetricPoint[];
}
interface NavDelayRecordingState {
  isRecording: boolean;
  startedAtMs: number;
  startedAtText: string;
  stoppedAtText: string;
  durationMs: number;
  entries: string[];
  metricSeries: NavDelayRecordedMetricSeries[];
}
interface NavDelayAxisInfo {
  xLabel: string;
  yLabel: string;
  minText: string;
  maxText: string;
}
/** 接收当前工具与执行回调；组件卸载时自动释放连接和监听。 */
export function useNavigationController(
  props: {
    tool: ToolDefinition;
    loading: boolean;
    summary: string;
    logs: string[];
    resultData: Record<string, any>;
  },
  emit: {
    (event: "run", values: Record<string, string>): void;
    (event: "clearLogs"): void;
  },
) {
  const connectionEnabled = ref(false);
  const formValues = reactive<Record<string, string>>({});
  const tilePreview = ref("");
  function defaultMainDisplayColor(
    topic: string,
    kind: NavViewerDisplay["kind"],
  ) {
    if (kind === "path") {
      return "#f6a237";
    }
    if (kind === "bspline") {
      return "#ff5f76";
    }
    if (kind === "pose") {
      if (topic.includes("ekf")) {
        return "#7bdff2";
      }
      if (topic.includes("ndt")) {
        return "#ffd166";
      }
      return "#2f8cff";
    }
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
    if (kind === "marker") {
      if (topic.includes("self_inflation")) {
        return "#4cc9f0";
      }
      if (topic.includes("optimal")) {
        return "#ff5f76";
      }
      if (topic.includes("a_star")) {
        return "#ffd166";
      }
      if (topic.includes("global")) {
        return "#2ec4b6";
      }
      return "#8ea1ba";
    }
    if (kind === "twist") {
      if (topic.includes("scanplanner")) {
        return "#ff8c42";
      }
      return "#31d28a";
    }
    return "#ffffff";
  }
  function defaultNavDelayTopicsText() {
    return NAV_DELAY_DEFAULT_TOPICS.join("\n");
  }
  function normalizeNavDelayTopicsInput(value: string) {
    const seen = new Set<string>();
    return value
      .split(/[\n,，;；]+/)
      .map((item) => item.trim())
      .filter((item) => item.startsWith("/"))
      .filter((item) => {
        if (seen.has(item)) {
          return false;
        }
        seen.add(item);
        return true;
      });
  }
  function subscriptionOptionsForNavDelay(
    definition: NavDelayTopicDefinition,
  ): RosSubscriptionOptions {
    const topic = definition.topic;
    const messageType = definition.messageType;
    if (
      messageType === "sensor_msgs/msg/PointCloud2" ||
      messageType === "sensor_msgs/PointCloud2"
    ) {
      return { throttleRateMs: 500, queueLength: 1 };
    }
    if (
      messageType === "nav_msgs/msg/OccupancyGrid" ||
      messageType === "nav_msgs/OccupancyGrid"
    ) {
      return { throttleRateMs: 2000, queueLength: 1 };
    }
    if (
      messageType === "tf2_msgs/msg/TFMessage" ||
      messageType === "tf2_msgs/TFMessage" ||
      topic === "/tf" ||
      topic === "/tf_static"
    ) {
      return {
        throttleRateMs: topic === "/tf_static" ? 5000 : 200,
        queueLength: 1,
      };
    }
    return { queueLength: 1 };
  }
  function fallbackNavDelayLabel(topic: string) {
    return topic.split("/").filter(Boolean).pop() || topic;
  }
  const NAV_RECORDING_JSON_BEGIN = "--- NAV_RECORDING_JSON BEGIN ---";
  const NAV_RECORDING_JSON_END = "--- NAV_RECORDING_JSON END ---";
  const NAV_RECORDING_PREVIEW_MAX_CHARS = 24000;
  const NAV_RECORDING_PREVIEW_MAX_LINES = 320;
  const NAV_RECORDING_CHART_MAX_SAMPLES = 4000;
  const NAV_DELAY_WINDOW_MS = 10_000;
  const NAV_DELAY_MAX_SAMPLES = 180;
  const ROSBRIDGE_TIMEOUT_MIN_MS = 8000;
  const NAV_DELAY_DEFAULT_TOPICS: string[] = [];
  const NAV_DELAY_TOPIC_COLORS = [
    "#2f8cff",
    "#31d28a",
    "#f6a237",
    "#8a63ff",
    "#f15d78",
    "#ffd166",
    "#7bdff2",
    "#4cc9f0",
    "#ff8fab",
    "#c7f464",
    "#ffa94d",
    "#9b8cff",
  ];
  const defaultNavTopicOptions: NavTopicOption[] = [
    {
      key: "/map",
      label: "二维地图",
      type: "nav_msgs/OccupancyGrid",
      note: "Nav2 常用二维栅格地图话题，适合直接叠加到主视图。",
    },
    {
      key: "/debug/loaded_pointcloud_map",
      label: "地图点云",
      type: "sensor_msgs/msg/PointCloud2",
      note: "文档推荐优先接入，用于和实时点云做重合验证。",
    },
    {
      key: "/points_aligned",
      label: "对齐结果点云",
      type: "sensor_msgs/msg/PointCloud2",
      note: "文档最关键的几何验证话题之一，用来看 NDT 是否真正贴图。",
    },
    {
      key: "/cloud_registered_bl",
      label: "NDT 输入点云",
      type: "sensor_msgs/msg/PointCloud2",
      note: "NDT 实际输入点云，适合和 points_aligned 对比。",
    },
    {
      key: "/cloud_registered_body",
      label: "FAST-LIO 输出点云",
      type: "sensor_msgs/msg/PointCloud2",
      note: "结构参考点云，也是 scan 链路上游。",
    },
    {
      key: "/ndt_pose",
      label: "NDT 位姿",
      type: "geometry_msgs/msg/PoseStamped",
      note: "文档明确推荐优先接入，用于显示定位箭头。",
    },
    {
      key: "/initialpose_candidates",
      label: "候选位姿数组",
      type: "geometry_msgs/msg/PoseArray",
      note: "用于观察自动定位或重定位候选点，主视图会按位姿箭头批量显示。",
    },
    {
      key: "/odometry/filtered",
      label: "融合里程计",
      type: "nav_msgs/msg/Odometry",
      note: "查看导航运动和位姿连续性。",
    },
    {
      key: "/plan",
      label: "当前路径",
      type: "nav_msgs/msg/Path",
      note: "文档建议作为几何验证主视图的常规叠加项。",
    },
    {
      key: "/tf",
      label: "TF 树",
      type: "tf2_msgs/msg/TFMessage",
      note: "查看 base_link 与地图坐标系链路。",
    },
    {
      key: "/scan",
      label: "LaserScan",
      type: "sensor_msgs/msg/LaserScan",
      note: "文档建议用于查看 Nav2 局部避障输入。",
    },
    {
      key: "/geneox_mid360_obstacle",
      label: "冷静区/危险区",
      type: "std_msgs/msg/UInt8",
      note: "按文档推荐在主视图中绑定定位位姿绘制冷静区、危险区和忽略区。",
    },
    {
      key: "/lio/cloud_local_base_exact",
      label: "SCAN 局部点云",
      type: "sensor_msgs/msg/PointCloud2",
      note: "SCAN-Planner 原始局部点云，用于确认前方障碍是否真的被感知到。",
    },
    {
      key: "/grid_map/occupancy_inflate",
      label: "SCAN 膨胀占据点云",
      type: "sensor_msgs/msg/PointCloud2",
      note: "观察障碍是否真正进入 SCAN 的碰撞占据图。",
    },
    {
      key: "/self_inflation",
      label: "SCAN 机体包络",
      type: "visualization_msgs/msg/Marker",
      note: "双圆柱机体包络，判断碰撞模型与障碍相对位置。",
    },
    {
      key: "/planning/bspline",
      label: "SCAN B-spline 轨迹",
      type: "scan_planner_msgs/msg/Bspline",
      note: "SCAN 实际输出的局部轨迹，主视图会按采样折线显示。",
    },
    {
      key: "/initial_path",
      label: "SCAN 参考路径",
      type: "nav_msgs/msg/Path",
      note: "Nav2 给 SCAN 的参考路径，用来看全局参考是否本身绕不开障碍。",
    },
    {
      key: "/cmd_vel_scanplanner_raw",
      label: "SCAN 原始控制",
      type: "geometry_msgs/msg/Twist",
      note: "SCAN controller 原始控制输出，便于判断是否已经尝试避障。",
    },
    {
      key: "/global_list",
      label: "SCAN 全局参考可视化",
      type: "visualization_msgs/msg/Marker",
      note: "规划器全局参考点与折线可视化。",
    },
    {
      key: "/a_star_list",
      label: "SCAN A* 初始路径",
      type: "visualization_msgs/msg/Marker",
      note: "搜索阶段初始路径，可与最终轨迹对比。",
    },
    {
      key: "/init_list",
      label: "SCAN 优化前轨迹",
      type: "visualization_msgs/msg/Marker",
      note: "优化前的轨迹点和折线。",
    },
    {
      key: "/optimal_list",
      label: "SCAN 优化后轨迹",
      type: "visualization_msgs/msg/Marker",
      note: "优化后的轨迹点和折线，部分场景下可能不稳定。",
    },
    {
      key: "/grid_map/sliding_map_bbox",
      label: "SCAN 局部地图窗口",
      type: "visualization_msgs/msg/Marker",
      note: "滑动局部地图窗口范围，用来确认障碍是否落入规划窗口。",
    },
    {
      key: "/planning/data_display",
      label: "SCAN 规划诊断",
      type: "scan_planner_msgs/msg/DataDisp",
      note: "规划内部诊断数据，目前建议放在小窗里看原始数值。",
    },
    {
      key: "/ndt_status",
      label: "NDT 状态",
      type: "std_msgs/msg/UInt8",
      note: "0 unknown / 1 healthy / 2 degraded / 3 lost。",
    },
    {
      key: "/iteration_num",
      label: "NDT 迭代数",
      type: "autoware_internal_debug_msgs/msg/Int32Stamped",
      note: "判断是否接近失配或吃满迭代。",
    },
    {
      key: "/exe_time_ms",
      label: "NDT 耗时",
      type: "autoware_internal_debug_msgs/msg/Float32Stamped",
      note: "判断环境复杂度和性能抖动。",
    },
    {
      key: "/ndt_score",
      label: "NDT 评分",
      type: "std_msgs/msg/Float32",
      note: "适合趋势显示和失配预警。",
    },
    {
      key: "/fastlio_ndt_observation_debug",
      label: "NDT 观测调试",
      type: "std_msgs/msg/String",
      note: "字符串 JSON，重点看 sigma_xy_m / sigma_yaw_deg / planar_dist_before_m / z_err_before_m。",
    },
    {
      key: "/nav2_status",
      label: "Nav2 状态汇总",
      type: "std_msgs/msg/String",
      note: "字符串 JSON，总状态看板核心话题。",
    },
    {
      key: "/nav2_goal_context",
      label: "导航任务上下文",
      type: "std_msgs/msg/String",
      note: "字符串 JSON，适合看 active / paused / request_planid。",
    },
    {
      key: "/cmd_vel",
      label: "控制输出",
      type: "geometry_msgs/msg/Twist",
      note: "判断 Nav2 是否真的在输出控制指令。",
    },
  ];
  function createDefaultNavSidePanels(): NavPanelItem[] {
    return [];
  }
  function createDefaultNavFullPanels(): NavPanelItem[] {
    return [];
  }
  const selectedNavTopics = ref<string[]>([]);
  const navSidePanels = ref<NavPanelItem[]>(createDefaultNavSidePanels());
  const navFullPanels = ref<NavPanelItem[]>(createDefaultNavFullPanels());
  const navMainDisplays = ref<NavViewerDisplay[]>([]);
  const rosInspectLoading = ref(false);
  const rosTopicsLoading = ref(false);
  const rosDataSourceSaving = ref(false);
  const rosRuntimeParamsLoading = ref(false);
  const rosTopicQuery = ref("");
  const rosTopicOptions = ref<NavTopicOption[]>(defaultNavTopicOptions);
  const rosInspectResult = ref<RosInspectionResponse | null>(null);
  const rosTopicsMessage = ref("");
  const rosRuntimeLogs = ref<string[]>([]);
  const rosReconnectToken = ref(0);
  const rosDataSourceConfigLoaded = ref(false);
  const rosRuntimeParams = ref<RosRuntimeParamsResponse | null>(null);
  const rosRuntimeParamsMessage = ref("");
  const rosSharedSessionStats = ref<SharedRosSessionStats>({
    sharedKey: "",
    exists: false,
    clientCount: 0,
    subscriptionCount: 0,
    connected: false,
    reconnecting: false,
    message: "当前页面还没有建立共享连接",
  });
  const navDelayPanelCollapsed = ref(false);
  const navViewerRef = ref<Nav3DViewerComponentExpose | null>(null);
  const navDelayTopicsInput = ref(NAV_DELAY_DEFAULT_TOPICS.join("\n"));
  const navDelayTopicsApplied = ref(NAV_DELAY_DEFAULT_TOPICS.join("\n"));
  const navDelayStateMap = ref<Record<string, NavDelayTopicState>>({});
  const navDelayAggregateLines = ref<NavDelayAggregateLine[]>([]);
  const navDelayOverviewSelectionMap = ref<Record<string, boolean>>({});
  const navDelayOverviewRecording = ref<NavDelayRecordingState>({
    isRecording: false,
    startedAtMs: 0,
    startedAtText: "-",
    stoppedAtText: "-",
    durationMs: 0,
    entries: [],
    metricSeries: [],
  });
  const navDelayMessage = ref("等待链路延迟数据。");
  const navRuntimeParamsPanelCollapsed = ref(true);
  const navRuntimeGroupCollapsedMap = ref<Record<string, boolean>>({});
  const navRuntimeNodeCollapsedMap = ref<Record<string, boolean>>({});
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
  const manualInitialPoseX = ref("");
  const manualInitialPoseY = ref("");
  const manualInitialPoseZ = ref("0");
  const manualInitialPoseYaw = ref("");
  const initialPosePointCloudTopic = ref("/cloud_registered_bl");
  const initialPosePointCloudLoading = ref(false);
  const initialPosePointCloudSize = ref("0.055");
  const initialPoseCandidateActive = ref(false);
  const initialPoseTopicDropdownOpen = ref(false);
  const offlineMapLoading = ref(false);
  const offlineMapMessage = ref("");
  const offlineMapPreview = ref<NavOfflineMapPreviewResponse | null>(null);
  const offlineMapDisplayMode = ref<OfflineMapDisplayMode>("voxel");
  let rosSharedStatsTimer: number | undefined;
  let navDelayAdapter: ReturnType<typeof createSharedRosLiveAdapter> | null =
    null;
  let navControlAdapter: ReturnType<typeof createSharedRosLiveAdapter> | null =
    null;
  let navSessionAutoSaved = false;
  let navExitSaveInFlight: Promise<void> | null = null;
  const navDelayUnsubscribeMap = new Map<string, () => void>();
  const navDelaySampleMap = new Map<string, NavDelaySample[]>();
  watch(
    () => props.tool,
    (tool, previousTool) => {
      if (previousTool?.key === "ros_nav_test") {
        saveRosNavConfigOnExit();
      }
      Object.keys(formValues).forEach((key) => delete formValues[key]);
      tool.fields.forEach((field) => {
        formValues[field.key] = field.value ?? "";
      });

      tilePreview.value = "";

      selectedNavTopics.value = [];
      navSidePanels.value = createDefaultNavSidePanels();
      navFullPanels.value = createDefaultNavFullPanels();
      navMainDisplays.value = [];
      rosInspectResult.value = null;
      rosTopicsMessage.value = "";
      rosRuntimeLogs.value = [];
      rosReconnectToken.value = 0;
      rosDataSourceConfigLoaded.value = false;
      navSessionAutoSaved = false;
      rosRuntimeParams.value = null;
      rosRuntimeParamsMessage.value = "";
      initialPosePointCloudTopic.value = "/cloud_registered_bl";
      initialPosePointCloudLoading.value = false;
      initialPosePointCloudSize.value = "0.055";
      initialPoseCandidateActive.value = false;
      offlineMapLoading.value = false;
      offlineMapMessage.value = "";
      offlineMapPreview.value = null;
      navViewerRef.value?.clearOfflineMapPointCloud();
      navViewerRef.value?.clearInitialPoseCandidate();
      navDelayPanelCollapsed.value = false;
      navDelayTopicsInput.value = defaultNavDelayTopicsText();
      navDelayTopicsApplied.value = defaultNavDelayTopicsText();
      navDelayStateMap.value = {};
      navDelayOverviewSelectionMap.value = {};
      navDelayOverviewRecording.value = {
        isRecording: false,
        startedAtMs: 0,
        startedAtText: "-",
        stoppedAtText: "-",
        durationMs: 0,
        entries: [],
        metricSeries: [],
      };
      navDelayMessage.value = "等待链路延迟数据。";
      rosSharedSessionStats.value = {
        sharedKey: "",
        exists: false,
        clientCount: 0,
        subscriptionCount: 0,
        connected: false,
        reconnecting: false,
        message: "当前页面还没有建立共享连接",
      };
      navRuntimeParamsPanelCollapsed.value = true;
      navRuntimeGroupCollapsedMap.value = {};
      navRuntimeNodeCollapsedMap.value = {};
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

        void reconnectNavDelayPanel();
        startRosSharedStatsPolling();
      } else {
        disconnectNavDelayPanel();
        stopRosSharedStatsPolling();
      }
    },
    { immediate: true },
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
      if (
        !currentOutput ||
        currentOutput ===
          buildDefaultTileOutputDir(currentOutput.replace(/_tiles$/, ".pcd"))
      ) {
        formValues.output_dir = suggested;
        return;
      }
      if (currentOutput.endsWith("_tiles")) {
        formValues.output_dir = suggested;
      }
    },
  );
  watch(
    () => [
      props.tool.key,
      formValues.ros_provider,
      formValues.ros_bridge_url,
      formValues.timeout_ms,
    ],
    () => {
      disconnectNavControlAdapter();
      if (props.tool.key !== "ros_nav_test") {
        return;
      }
      refreshRosSharedStats();
      void reconnectNavDelayPanel();
    },
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
  const pcdMapImageUrl = computed(() => {
    const path = props.resultData.preview_path || props.resultData.color_path;
    if (!path) {
      return "";
    }
    return buildBackendImageUrl(
      String(path),
      String(props.resultData.generated_at || ""),
    );
  });
  const selectedNavTopicOptions = computed(() =>
    rosTopicOptions.value.filter((item) =>
      selectedNavTopics.value.includes(item.key),
    ),
  );
  const initialPosePointCloudTopicOptions = computed(() =>
    rosTopicOptions.value.filter(
      (item) => inferDisplayKind(item.key, item.type) === "pointcloud",
    ),
  );
  const filteredInitialPosePointCloudTopicOptions = computed(() => {
    const keyword = initialPosePointCloudTopic.value.trim().toLowerCase();
    if (!keyword) {
      return initialPosePointCloudTopicOptions.value;
    }
    return initialPosePointCloudTopicOptions.value.filter((topic) =>
      [topic.key, topic.label, topic.type, topic.note].some((value) =>
        value.toLowerCase().includes(keyword),
      ),
    );
  });
  const mergedToolLogs = computed(() => [
    ...props.logs,
    ...rosRuntimeLogs.value,
  ]);
  const navActiveSidePanelCount = computed(
    () => navSidePanels.value.filter((panel) => !panel.paused).length,
  );
  const navActiveFullPanelCount = computed(
    () => navFullPanels.value.filter((panel) => !panel.paused).length,
  );
  const navDisplayManagerLabel = computed(() =>
    navDisplayManagerCollapsed.value
      ? `展开显示项管理 (${navMainDisplays.value.length})`
      : `收起显示项管理 (${navMainDisplays.value.length})`,
  );
  const initialPoseModeButtonLabel = computed(() =>
    navInteractionMode.value === "initialpose" ||
    initialPoseCandidateActive.value
      ? "取消初始化定位"
      : "初始化定位",
  );
  const filteredRosTopicOptions = computed(() => {
    const keyword = rosTopicQuery.value.trim().toLowerCase();
    if (!keyword) {
      return rosTopicOptions.value;
    }
    return rosTopicOptions.value.filter((item) =>
      `${item.key} ${item.label} ${item.type} ${item.note}`
        .toLowerCase()
        .includes(keyword),
    );
  });
  const navDelayTopicDefinitions = computed<NavDelayTopicDefinition[]>(() => {
    const optionMap = new Map(
      rosTopicOptions.value.map((item) => [item.key, item]),
    );
    return normalizeNavDelayTopicsInput(navDelayTopicsApplied.value).map(
      (topic, index) => {
        const option = optionMap.get(topic);
        return {
          topic,
          messageType: option?.type || "",
          label: option?.label || fallbackNavDelayLabel(topic),
          color: NAV_DELAY_TOPIC_COLORS[index % NAV_DELAY_TOPIC_COLORS.length],
          resolved: Boolean(option?.type),
        };
      },
    );
  });
  const navDelayOverviewAxisInfo = computed(() =>
    buildOverviewAxisInfo(navDelayAggregateLines.value),
  );
  watch(
    () =>
      navDelayTopicDefinitions.value
        .map((definition) => `${definition.topic}:${definition.messageType}`)
        .join("|"),
    () => {
      if (props.tool.key !== "ros_nav_test" || navDelayPanelCollapsed.value) {
        return;
      }
      void reconnectNavDelayPanel();
    },
  );
  function normalizeRosBridgeTimeoutMs(value: string | number | undefined) {
    const parsed = Number(value ?? "");
    if (!Number.isFinite(parsed)) {
      return String(ROSBRIDGE_TIMEOUT_MIN_MS);
    }
    return String(Math.max(ROSBRIDGE_TIMEOUT_MIN_MS, Math.round(parsed)));
  }
  /**
   * 规范化机器人 TF 子坐标系，避免用户输入前导斜杠或空值导致查找失败。
   * 空值回退到平台默认的 body，以兼容没有保存此项的旧配置。
   */
  function normalizeRobotTfFrame(value: string | undefined) {
    return (
      String(value || "body")
        .trim()
        .replace(/^\/+/, "") || "body"
    );
  }
  function clearToolLogs() {
    rosRuntimeLogs.value = [];
    emit("clearLogs");
  }
  function appendRosRuntimeLog(
    level: "info" | "warning" | "error",
    message: string,
  ) {
    const prefix =
      level === "error"
        ? "[ROS][ERROR]"
        : level === "warning"
          ? "[ROS][WARN]"
          : "[ROS][INFO]";
    const line = `${prefix} ${new Date().toLocaleTimeString("zh-CN", { hour12: false })} ${message}`;
    rosRuntimeLogs.value = [...rosRuntimeLogs.value.slice(-159), line];
  }
  function handleRosRuntimeLog(payload: {
    source: string;
    level: "info" | "warning" | "error";
    message: string;
  }) {
    appendRosRuntimeLog(payload.level, `${payload.source}: ${payload.message}`);
    refreshRosSharedStats();
  }
  function triggerRosReconnect() {
    rosReconnectToken.value += 1;
    appendRosRuntimeLog("warning", "测试工作台: 手动触发 ROS 重连。");
    refreshRosSharedStats();
    void reconnectNavDelayPanel();
    void loadRosRuntimeParamsPanel();
  }
  function buildRosSharedSessionKey() {
    return `ros-nav-test:${formValues.ros_provider || "rosbridge"}:${formValues.ros_bridge_url || ""}:${normalizeRosBridgeTimeoutMs(formValues.timeout_ms)}`;
  }
  function disconnectNavControlAdapter() {
    navControlAdapter?.disconnect();
    navControlAdapter = null;
  }
  async function ensureNavControlAdapterConnected() {
    if (!connectionEnabled.value) throw new Error("请先在平台设置中连接 ROS。");
    if (!navControlAdapter) {
      navControlAdapter = createSharedRosLiveAdapter({
        ...buildRosLiveConfig(),
        adapterName: "导航控制下发",
        autoReconnect: false,
        sharedKey: buildRosSharedSessionKey(),
        onError: (event) => {
          appendRosRuntimeLog(
            event.recoverable ? "warning" : "error",
            `${event.scope}: ${event.message}${event.detail ? ` (${event.detail})` : ""}`,
          );
        },
      });
    }
    const snapshot = navControlAdapter.getConnectionSnapshot();
    if (snapshot.connected) {
      return navControlAdapter;
    }
    await navControlAdapter.requestReconnect(
      "导航控制下发前确认 rosbridge 连接",
    );
    return navControlAdapter;
  }
  function refreshRosSharedStats() {
    if (props.tool.key !== "ros_nav_test") {
      return;
    }
    rosSharedSessionStats.value = getSharedRosSessionStats(
      buildRosSharedSessionKey(),
    );
  }
  function stopRosSharedStatsPolling() {
    if (rosSharedStatsTimer) {
      window.clearInterval(rosSharedStatsTimer);
      rosSharedStatsTimer = undefined;
    }
  }
  function startRosSharedStatsPolling() {
    stopRosSharedStatsPolling();
    refreshRosSharedStats();
    rosSharedStatsTimer = window.setInterval(() => {
      refreshRosSharedStats();
    }, 1000);
  }
  function formatDelayWallTime(timeMs: number | null) {
    if (!timeMs || !Number.isFinite(timeMs)) {
      return "-";
    }
    return new Date(timeMs).toLocaleTimeString("zh-CN", {
      hour12: false,
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      fractionalSecondDigits: 3,
    });
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
  function formatDelayStampSec(stampMs: number | null) {
    if (!stampMs || !Number.isFinite(stampMs)) {
      return "-";
    }
    return (stampMs / 1000).toFixed(3);
  }
  function formatDelayMs(value: number | null, digits = 1) {
    if (value === null || !Number.isFinite(value)) {
      return "-";
    }
    return value.toFixed(digits);
  }
  function formatDelayDuration(durationMs: number) {
    return `${(Math.max(0, durationMs) / 1000).toFixed(2)} s`;
  }
  function delaySparklinePoints(
    samples: NavDelaySample[],
    minStampMs: number,
    maxStampMs: number,
  ) {
    if (samples.length === 0) {
      return "";
    }
    const range = Math.max(1, maxStampMs - minStampMs);
    return samples
      .map((sample, index) => {
        const x =
          samples.length === 1 ? 0 : (index / (samples.length - 1)) * 100;
        const y = 46 - ((sample.stampMs - minStampMs) / range) * 42;
        return `${x.toFixed(2)},${y.toFixed(2)}`;
      })
      .join(" ");
  }
  function delayAggregateLinePoints(
    samples: NavDelaySample[],
    minRecvMs: number,
    maxRecvMs: number,
    minAgeMs: number,
    maxAgeMs: number,
  ) {
    if (samples.length === 0) {
      return "";
    }
    const recvRange = Math.max(1, maxRecvMs - minRecvMs);
    const ageRange = Math.max(1, maxAgeMs - minAgeMs);
    return samples
      .map((sample) => {
        const x = ((sample.recvMs - minRecvMs) / recvRange) * 100;
        const y = 46 - ((sample.ageMs - minAgeMs) / ageRange) * 42;
        return `${x.toFixed(2)},${y.toFixed(2)}`;
      })
      .join(" ");
  }
  function delayAggregateDisplayValue(
    sample: NavDelaySample,
    baselineRecvMs: number,
    baselineStampMs: number,
  ) {
    return sample.stampMs - baselineStampMs - (sample.recvMs - baselineRecvMs);
  }
  function delayAggregateAbsoluteStampSec(sample: NavDelaySample) {
    return sample.stampMs / 1000;
  }
  function delayAggregateEnhancedLinePoints(
    samples: NavDelaySample[],
    minRecvMs: number,
    maxRecvMs: number,
    baselineRecvMs: number,
    baselineStampMs: number,
    minDisplayMs: number,
    maxDisplayMs: number,
  ) {
    if (samples.length === 0) {
      return "";
    }
    const recvRange = Math.max(1, maxRecvMs - minRecvMs);
    const displayRange = Math.max(1, maxDisplayMs - minDisplayMs);
    return samples
      .map((sample) => {
        const x = ((sample.recvMs - minRecvMs) / recvRange) * 100;
        const displayMs = delayAggregateDisplayValue(
          sample,
          baselineRecvMs,
          baselineStampMs,
        );
        const y = 46 - ((displayMs - minDisplayMs) / displayRange) * 42;
        return `${x.toFixed(2)},${y.toFixed(2)}`;
      })
      .join(" ");
  }
  function buildOverviewAxisInfo(
    lines: NavDelayAggregateLine[],
  ): NavDelayAxisInfo {
    const visibleTopics = new Set(lines.map((item) => item.topic));
    const visibleSamples = navDelayTopicDefinitions.value.flatMap(
      (definition) =>
        visibleTopics.has(definition.topic)
          ? (navDelaySampleMap.get(definition.topic) ?? [])
          : [],
    );
    if (visibleSamples.length === 0) {
      return {
        xLabel: "X: recv_time (最近10s)",
        yLabel: "Y: stamp_offset_ms(绝对时间戳去趋势)",
        minText: "-",
        maxText: "-",
      };
    }
    const baselineRecvMs = Math.min(
      ...visibleSamples.map((item) => item.recvMs),
    );
    const baselineStampMs = Math.min(
      ...visibleSamples.map((item) => item.stampMs),
    );
    const displayValues = visibleSamples.map((item) =>
      delayAggregateDisplayValue(item, baselineRecvMs, baselineStampMs),
    );
    return {
      xLabel: "X: recv_time (最近10s)",
      yLabel: "Y: stamp_offset_ms(绝对时间戳去趋势)",
      minText: Math.min(...displayValues).toFixed(1),
      maxText: Math.max(...displayValues).toFixed(1),
    };
  }
  function rebuildNavDelayStates() {
    const topicStates: Record<string, NavDelayTopicState> = {};
    const now = Date.now();
    let minRecvMs = Number.POSITIVE_INFINITY;
    let maxRecvMs = Number.NEGATIVE_INFINITY;
    let minStampMs = Number.POSITIVE_INFINITY;
    let minDisplayMs = Number.POSITIVE_INFINITY;
    let maxDisplayMs = Number.NEGATIVE_INFINITY;

    navDelayTopicDefinitions.value.forEach((definition) => {
      const samples = (navDelaySampleMap.get(definition.topic) ?? []).filter(
        (item) => now - item.recvMs <= NAV_DELAY_WINDOW_MS,
      );
      navDelaySampleMap.set(definition.topic, samples);
      samples.forEach((sample) => {
        minRecvMs = Math.min(minRecvMs, sample.recvMs);
        maxRecvMs = Math.max(maxRecvMs, sample.recvMs);
        minStampMs = Math.min(minStampMs, sample.stampMs);
      });
    });

    const safeMinRecvMs = Number.isFinite(minRecvMs)
      ? minRecvMs
      : now - NAV_DELAY_WINDOW_MS;
    const safeMaxRecvMs = Number.isFinite(maxRecvMs) ? maxRecvMs : now;
    const safeMinStampMs = Number.isFinite(minStampMs)
      ? minStampMs
      : safeMinRecvMs;

    navDelayTopicDefinitions.value.forEach((definition) => {
      const samples = navDelaySampleMap.get(definition.topic) ?? [];
      samples.forEach((sample) => {
        const displayMs = delayAggregateDisplayValue(
          sample,
          safeMinRecvMs,
          safeMinStampMs,
        );
        minDisplayMs = Math.min(minDisplayMs, displayMs);
        maxDisplayMs = Math.max(maxDisplayMs, displayMs);
      });
    });

    const safeMinDisplayMs = Number.isFinite(minDisplayMs) ? minDisplayMs : 0;
    const safeMaxDisplayMs = Number.isFinite(maxDisplayMs)
      ? maxDisplayMs
      : safeMinDisplayMs + 1;

    navDelayAggregateLines.value = navDelayTopicDefinitions.value
      .map((definition) => {
        const samples = navDelaySampleMap.get(definition.topic) ?? [];
        const latest = samples[samples.length - 1] ?? null;
        return {
          topic: definition.topic,
          label: definition.label,
          color: definition.color,
          points: delayAggregateEnhancedLinePoints(
            samples,
            safeMinRecvMs,
            safeMaxRecvMs,
            safeMinRecvMs,
            safeMinStampMs,
            safeMinDisplayMs,
            safeMaxDisplayMs,
          ),
          ageMs: latest?.ageMs ?? null,
          latestStampMs: latest?.stampMs ?? null,
        };
      })
      .filter(
        (line) => line.points && isNavDelayOverviewTopicSelected(line.topic),
      );

    navDelayTopicDefinitions.value.forEach((definition) => {
      const samples = navDelaySampleMap.get(definition.topic) ?? [];
      const latest = samples[samples.length - 1] ?? null;
      const ageValues = samples.map((item) => item.ageMs);
      const avgAge =
        ageValues.length > 0
          ? ageValues.reduce((sum, item) => sum + item, 0) / ageValues.length
          : null;
      const maxAge = ageValues.length > 0 ? Math.max(...ageValues) : null;
      const lastRecvMs = latest?.recvMs ?? null;
      const lastStampMs = latest?.stampMs ?? null;
      const hz =
        samples.length >= 2 && samples[0] && samples[samples.length - 1]
          ? ((samples.length - 1) * 1000) /
            Math.max(1, samples[samples.length - 1].recvMs - samples[0].recvMs)
          : 0;

      topicStates[definition.topic] = {
        topic: definition.topic,
        label: definition.label,
        messageType: definition.messageType,
        color: definition.color,
        lastStampMs,
        lastRecvMs,
        ageMs: latest?.ageMs ?? null,
        hz,
        avgAgeMs10s: avgAge,
        maxAgeMs10s: maxAge,
        stampSecText: formatDelayStampSec(lastStampMs),
        recvWallTimeText: formatDelayWallTime(lastRecvMs),
        points: delaySparklinePoints(
          samples,
          Number.isFinite(Math.min(...samples.map((item) => item.stampMs)))
            ? Math.min(...samples.map((item) => item.stampMs))
            : 0,
          Number.isFinite(Math.max(...samples.map((item) => item.stampMs)))
            ? Math.max(...samples.map((item) => item.stampMs))
            : 1,
        ),
        sampleCount: samples.length,
      };
    });

    navDelayStateMap.value = topicStates;
  }
  function extractMessageStampMs(message: unknown) {
    const header = (message as Record<string, any> | null)?.header;
    const sec = Number(header?.stamp?.sec ?? Number.NaN);
    const nanosec = Number(header?.stamp?.nanosec ?? Number.NaN);
    if (!Number.isFinite(sec) || !Number.isFinite(nanosec)) {
      return null;
    }
    return sec * 1000 + nanosec / 1e6;
  }
  function handleNavDelayMessage(
    definition: NavDelayTopicDefinition,
    message: unknown,
  ) {
    const recvMs = Date.now();
    const stampMs = extractMessageStampMs(message);
    if (stampMs === null) {
      return;
    }
    const nextSamples = [
      ...(navDelaySampleMap.get(definition.topic) ?? []),
      {
        recvMs,
        stampMs,
        ageMs: recvMs - stampMs,
      },
    ];
    const trimmed = nextSamples
      .filter((item) => recvMs - item.recvMs <= NAV_DELAY_WINDOW_MS)
      .slice(-NAV_DELAY_MAX_SAMPLES);
    navDelaySampleMap.set(definition.topic, trimmed);
    rebuildNavDelayStates();
    updateNavDelayOverviewRecording(recvMs);
  }
  function ensureDelayRecordingState(
    current?: NavDelayRecordingState,
  ): NavDelayRecordingState {
    return (
      current ?? {
        isRecording: false,
        startedAtMs: 0,
        startedAtText: "-",
        stoppedAtText: "-",
        durationMs: 0,
        entries: [],
        metricSeries: [],
      }
    );
  }
  function mergeDelayRecordedMetricSeries(
    recording: NavDelayRecordingState,
    metrics: Array<{
      label: string;
      unit: string;
      color: string;
      value: number | null;
    }>,
    offsetMs: number,
  ) {
    const previousSeries = new Map(
      recording.metricSeries.map((item) => [item.label, item]),
    );
    return metrics.map((metric) => {
      const previousMetric = previousSeries.get(metric.label);
      return {
        label: metric.label,
        unit: metric.unit,
        color: metric.color,
        samples:
          metric.value === null
            ? (previousMetric?.samples ?? [])
            : [
                ...(previousMetric?.samples ?? []),
                { offsetMs, value: metric.value },
              ],
      };
    });
  }
  function appendDelayRecordedEntry(
    recording: NavDelayRecordingState,
    timeMs: number,
    content: string,
  ) {
    return [
      `[${formatTimestampWithMs(timeMs)}] ${content}`,
      ...recording.entries,
    ];
  }
  function navDelayRecordingDurationText(recording: NavDelayRecordingState) {
    const durationMs =
      recording.durationMs ||
      (recording.isRecording
        ? Math.max(0, Date.now() - recording.startedAtMs)
        : 0);
    return formatDelayDuration(durationMs);
  }
  function overviewRecordingEntriesText() {
    return navDelayAggregateLines.value
      .map((line) => {
        const stampText =
          line.latestStampMs === null
            ? "-"
            : formatDelayStampSec(line.latestStampMs);
        const ageText =
          line.ageMs === null ? "-" : `${formatDelayMs(line.ageMs)} ms`;
        return `${line.label}: stamp=${stampText}, age=${ageText}`;
      })
      .join(" | ");
  }
  function updateNavDelayOverviewRecording(now: number) {
    const recording = navDelayOverviewRecording.value;
    if (!recording.isRecording) {
      return;
    }
    const offsetMs = Math.max(0, now - recording.startedAtMs);
    const metrics = navDelayAggregateLines.value.flatMap((line) => {
      const samples = navDelaySampleMap.get(line.topic) ?? [];
      const latest = samples[samples.length - 1] ?? null;
      if (!latest) {
        return [];
      }
      return [
        {
          label: `${line.label} stamp_sec`,
          unit: "sec",
          color: line.color,
          value: delayAggregateAbsoluteStampSec(latest),
        },
        {
          label: `${line.label} age_ms`,
          unit: "ms",
          color: line.color,
          value: line.ageMs,
        },
      ];
    });
    if (metrics.length === 0) {
      return;
    }
    navDelayOverviewRecording.value = {
      ...recording,
      durationMs: offsetMs,
      entries: appendDelayRecordedEntry(
        recording,
        now,
        overviewRecordingEntriesText(),
      ),
      metricSeries: mergeDelayRecordedMetricSeries(
        recording,
        metrics,
        offsetMs,
      ),
    };
  }
  function applyNavRecordingFileList(
    response: Awaited<ReturnType<typeof fetchNavRecordingFiles>>,
    message: string,
  ) {
    navRecordingFiles.value = response.items;
    navRecordingFilesDirectory.value = response.directory;
    navRecordingFilesMessage.value = message;
  }
  function handleNavDelayRecordingSaveError(scope: string, error: unknown) {
    const message = error instanceof Error ? error.message : "未知错误";
    navRecordingFilesMessage.value = `${scope}录制保存失败: ${message}`;
    navDelayMessage.value = `${scope}录制保存失败: ${message}`;
  }
  async function finalizeNavDelayRecordingSave(
    payload: NavRecordingSavePayload,
    successMessage: string,
  ) {
    const response = await saveNavRecording(payload);
    applyNavRecordingFileList(response, successMessage);
    navDelayMessage.value = successMessage;
  }
  async function toggleNavDelayOverviewRecording() {
    const current = navDelayOverviewRecording.value;
    if (!current.isRecording) {
      const now = Date.now();
      navDelayOverviewRecording.value = {
        isRecording: true,
        startedAtMs: now,
        startedAtText: formatTimestampWithMs(now),
        stoppedAtText: "-",
        durationMs: 0,
        entries: [],
        metricSeries: [],
      };
      navDelayMessage.value = `链路时间戳总览录制中，开始于 ${formatTimestampWithMs(now)}。`;
      return;
    }

    const stopTime = Date.now();
    const nextRecordingState: NavDelayRecordingState = {
      ...current,
      isRecording: false,
      stoppedAtText: formatTimestampWithMs(stopTime),
      durationMs: Math.max(0, stopTime - current.startedAtMs),
    };
    navDelayOverviewRecording.value = nextRecordingState;
    try {
      await finalizeNavDelayRecordingSave(
        {
          panel_id: "delay-overview",
          title: "链路时间戳总览",
          topic: navDelayTopicDefinitions.value
            .map((item) => item.topic)
            .join(" | "),
          message_type: "nav_delay_overview",
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
        },
        "已保存录制文件: 链路时间戳总览",
      );
    } catch (error) {
      // 保存失败时保留当前录制结果，避免页面中的诊断数据丢失。
      handleNavDelayRecordingSaveError("链路时间戳总览", error);
    }
  }
  function disconnectNavDelayPanel() {
    navDelayUnsubscribeMap.forEach((unsubscribe) => unsubscribe());
    navDelayUnsubscribeMap.clear();
    navDelayAdapter?.disconnect();
    navDelayAdapter = null;
    navDelaySampleMap.clear();
    navDelayStateMap.value = {};
    navDelayAggregateLines.value = [];
  }
  function applyNavDelayTopics() {
    setNavDelayTopics(normalizeNavDelayTopicsInput(navDelayTopicsInput.value));
  }
  async function reconnectNavDelayPanel() {
    disconnectNavDelayPanel();
    if (!connectionEnabled.value || props.tool.key !== "ros_nav_test") {
      return;
    }
    if (!rosDataSourceConfigLoaded.value) {
      navDelayMessage.value = "等待 ROS 数据源配置加载完成。";
      return;
    }
    if (navDelayPanelCollapsed.value) {
      navDelayMessage.value = "链路延迟窗口已折叠，已暂停订阅与计算。";
      refreshRosSharedStats();
      return;
    }
    if (!formValues.ros_bridge_url && formValues.ros_provider !== "mock") {
      navDelayMessage.value = "未配置 rosbridge 地址，链路延迟窗口未启动。";
      return;
    }
    navDelayMessage.value = "链路延迟窗口连接中...";
    const activeDefinitions = navDelayTopicDefinitions.value;
    if (activeDefinitions.length === 0) {
      navDelayMessage.value = "当前没有配置要监控的话题。";
      return;
    }
    navDelayAdapter = createSharedRosLiveAdapter({
      provider: formValues.ros_provider || "rosbridge",
      url: formValues.ros_bridge_url || "",
      timeoutMs: Number(normalizeRosBridgeTimeoutMs(formValues.timeout_ms)),
      autoReconnect: true,
      reconnectBaseDelayMs: 3000,
      reconnectMaxDelayMs: 30000,
      reconnectMaxAttempts: 4,
      sharedKey: buildRosSharedSessionKey(),
      adapterName: "链路延迟窗口",
      onStatusChange: (snapshot) => {
        navDelayMessage.value = snapshot.message;
        refreshRosSharedStats();
      },
      onError: (event) => {
        appendRosRuntimeLog(
          event.recoverable ? "warning" : "error",
          `链路延迟窗口: ${event.scope}: ${event.message}${event.detail ? ` (${event.detail})` : ""}`,
        );
      },
    });

    try {
      await navDelayAdapter.connect();
      const subscribedTopics: string[] = [];
      const unresolvedTopics: string[] = [];
      activeDefinitions.forEach((definition) => {
        if (!definition.resolved || !definition.messageType) {
          unresolvedTopics.push(definition.topic);
          return;
        }
        const unsubscribe = navDelayAdapter?.subscribe(
          definition.topic,
          definition.messageType,
          (message) => {
            handleNavDelayMessage(definition, message);
          },
          subscriptionOptionsForNavDelay(definition),
        );
        if (unsubscribe) {
          navDelayUnsubscribeMap.set(definition.topic, unsubscribe);
          subscribedTopics.push(definition.topic);
        }
      });
      if (subscribedTopics.length === 0) {
        navDelayMessage.value =
          "没有可订阅的话题，请先刷新 ROS 话题或检查输入的话题名。";
      } else if (unresolvedTopics.length > 0) {
        navDelayMessage.value = `已连接并订阅 ${subscribedTopics.length} 个话题，另有 ${unresolvedTopics.length} 个话题未识别到消息类型。`;
      } else {
        navDelayMessage.value = "链路延迟窗口已连接，等待首批时间戳。";
      }
      refreshRosSharedStats();
    } catch (error) {
      navDelayMessage.value = `链路延迟窗口连接失败: ${(error as Error).message}`;
    }
  }
  function toggleNavDelayPanel() {
    const nextCollapsed = !navDelayPanelCollapsed.value;
    navDelayPanelCollapsed.value = nextCollapsed;
    if (nextCollapsed) {
      disconnectNavDelayPanel();
      navDelayMessage.value = "链路延迟窗口已折叠，已暂停订阅与计算。";
      refreshRosSharedStats();
      return;
    }
    void reconnectNavDelayPanel();
  }
  function isNavDelayOverviewTopicSelected(topic: string) {
    return navDelayOverviewSelectionMap.value[topic] !== false;
  }
  function toggleNavDelayOverviewTopic(topic: string) {
    navDelayOverviewSelectionMap.value = {
      ...navDelayOverviewSelectionMap.value,
      [topic]: !isNavDelayOverviewTopicSelected(topic),
    };
    rebuildNavDelayStates();
  }
  function getBrowseMode(
    fieldKey: string,
    fieldLabel: string,
  ): BrowseDialogPayload["mode"] | null {
    const key = fieldKey.toLowerCase();
    const label = fieldLabel.toLowerCase();
    if (
      key.includes("output_dir") ||
      key.endsWith("_dir") ||
      label.includes("output dir") ||
      label.includes("directory") ||
      label.includes("输出目录")
    ) {
      return "open_dir";
    }
    if (
      key.includes("input") ||
      key.includes("path") ||
      key.includes("pcd") ||
      key.includes("yaml") ||
      key.includes("pgm")
    ) {
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
    const fileName =
      lastSlash >= 0 ? normalized.slice(lastSlash + 1) : normalized;
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
      const path = canUseNativeRosFilePicker()
        ? (await pickNativeLocalFile(fieldKey)).path
        : await browsePath({
            mode,
            title: `选择${fieldLabel}`,
            initial_path: formValues[fieldKey] ?? "",
          });
      if (path) {
        formValues[fieldKey] = path;
      }
    } catch (error) {
      rosTopicsMessage.value = `文件选择失败，可手动输入路径。${(error as Error).message ? ` (${(error as Error).message})` : ""}`;
    }
  }
  async function previewTile() {
    if (!formValues.input_pcd?.trim()) {
      tilePreview.value = "请先选择输入 PCD。";
      return;
    }
    try {
      const result = await fetchPcdTilePreview(
        formValues.input_pcd,
        formValues.tile_size || "20.0",
      );
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
      rosTopicsMessage.value = "打开目录失败，请确认路径是否存在。";
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
      navDelayTopicsText: navDelayTopicsApplied.value,
    };
    return {
      provider: (formValues.ros_provider || "rosbridge").trim() || "rosbridge",
      options: {
        url: (formValues.ros_bridge_url || "").trim(),
        rosapi_service: (
          formValues.ros_api_service || "/rosapi/topics_and_raw_types"
        ).trim(),
        timeout_ms: normalizeRosBridgeTimeoutMs(formValues.timeout_ms),
        robot_tf_frame: normalizeRobotTfFrame(formValues.robot_tf_frame),
        offline_map_display_mode: normalizedOfflineMapDisplayMode(),
        offline_map_point_size: String(normalizedOfflineMapPointSize()),
        offline_map_point_color: normalizedOfflineMapColor(
          formValues.offline_map_point_color,
          "#d7dee8",
        ),
        offline_map_voxel_color: normalizedOfflineMapColor(
          formValues.offline_map_voxel_color,
          "#a79d86",
        ),
        nav_layout_json: JSON.stringify(savedLayout),
      },
    };
  }
  function loadLocalRosNavConfig(): RosDataSourceConfig | null {
    try {
      const raw = window.localStorage.getItem(ROS_NAV_LOCAL_CONFIG_KEY);
      if (!raw) {
        return null;
      }
      const parsed = JSON.parse(raw) as RosDataSourceConfig;
      if (!parsed || typeof parsed !== "object") {
        return null;
      }
      return {
        provider: parsed.provider || "rosbridge",
        options: parsed.options || {},
      };
    } catch {
      return null;
    }
  }
  function saveLocalRosNavConfig(config: RosDataSourceConfig) {
    window.localStorage.setItem(
      ROS_NAV_LOCAL_CONFIG_KEY,
      JSON.stringify(config),
    );
  }
  function applyRosDataSourceConfig(config: RosDataSourceConfig) {
    formValues.ros_provider =
      config.provider || formValues.ros_provider || "rosbridge";
    formValues.ros_bridge_url =
      config.options.url || formValues.ros_bridge_url || "";
    formValues.ros_api_service =
      config.options.rosapi_service ||
      formValues.ros_api_service ||
      "/rosapi/topics_and_raw_types";
    formValues.timeout_ms = normalizeRosBridgeTimeoutMs(
      config.options.timeout_ms || formValues.timeout_ms,
    );
    formValues.robot_tf_frame = normalizeRobotTfFrame(
      config.options.robot_tf_frame || formValues.robot_tf_frame,
    );
    formValues.offline_map_display_mode = normalizedOfflineMapDisplayMode(
      config.options.offline_map_display_mode || formValues.offline_map_display_mode,
    );
    formValues.offline_map_point_size = String(
      normalizedOfflineMapPointSize(
        config.options.offline_map_point_size || formValues.offline_map_point_size,
      ),
    );
    formValues.offline_map_point_color = normalizedOfflineMapColor(
      config.options.offline_map_point_color || formValues.offline_map_point_color,
      "#d7dee8",
    );
    formValues.offline_map_voxel_color = normalizedOfflineMapColor(
      config.options.offline_map_voxel_color || formValues.offline_map_voxel_color,
      "#a79d86",
    );
    const savedLayout = parseSavedNavLayout(config.options.nav_layout_json);
    if (!savedLayout) {
      return false;
    }
    navSidePanels.value = savedLayout.hasSidePanels
      ? savedLayout.sidePanels
      : createDefaultNavSidePanels();
    navFullPanels.value = savedLayout.hasFullPanels
      ? savedLayout.fullPanels
      : createDefaultNavFullPanels();
    navMainDisplays.value = savedLayout.hasMainDisplays
      ? savedLayout.mainDisplays
      : [];
    const navDelayTopicsText = savedLayout.hasNavDelayTopicsText
      ? savedLayout.navDelayTopicsText || ""
      : defaultNavDelayTopicsText();
    navDelayTopicsInput.value = navDelayTopicsText;
    navDelayTopicsApplied.value = navDelayTopicsText;
    return true;
  }
  function sanitizeNavPanelItem(
    raw: unknown,
    fallbackPrefix: string,
    index: number,
  ): NavPanelItem | null {
    if (!raw || typeof raw !== "object") {
      return null;
    }
    const panel = raw as Record<string, unknown>;
    const topic = typeof panel.topic === "string" ? panel.topic.trim() : "";
    const messageType =
      typeof panel.messageType === "string" ? panel.messageType.trim() : "";
    if (!topic || !messageType) {
      return null;
    }
    const id =
      typeof panel.id === "string" && panel.id.trim()
        ? panel.id.trim()
        : `${fallbackPrefix}-${topic.replace(/[^a-z0-9]+/gi, "-").replace(/^-+|-+$/g, "") || index}`;
    return {
      id,
      title:
        typeof panel.title === "string" && panel.title.trim()
          ? panel.title.trim()
          : `${topic}窗`,
      topic,
      type:
        typeof panel.type === "string" && panel.type.trim()
          ? panel.type.trim()
          : "可视化卡片",
      messageType,
      collapsed: false,
      paused: false,
      pointSize:
        typeof panel.pointSize === "number" ? panel.pointSize : undefined,
      hzLimit: typeof panel.hzLimit === "number" ? panel.hzLimit : undefined,
    };
  }
  function sanitizeNavViewerDisplay(raw: unknown): NavViewerDisplay | null {
    if (!raw || typeof raw !== "object") {
      return null;
    }
    const display = raw as Record<string, unknown>;
    const topic = typeof display.topic === "string" ? display.topic.trim() : "";
    const messageType =
      typeof display.messageType === "string" ? display.messageType.trim() : "";
    if (!topic || !messageType) {
      return null;
    }
    const kind = inferDisplayKind(topic, messageType);
    return {
      topic,
      messageType,
      kind,
      label:
        typeof display.label === "string" && display.label.trim()
          ? display.label.trim()
          : buildDisplayLabel(topic, kind),
      mapOpacity:
        typeof display.mapOpacity === "number" ? display.mapOpacity : undefined,
      pointSize:
        typeof display.pointSize === "number" ? display.pointSize : undefined,
      pointEmissiveIntensity:
        typeof display.pointEmissiveIntensity === "number"
          ? display.pointEmissiveIntensity
          : undefined,
      hzLimit:
        typeof display.hzLimit === "number" ? display.hzLimit : undefined,
      pointColorMode:
        display.pointColorMode === "layered" ? "layered" : "solid",
      color:
        typeof display.color === "string" && display.color.trim()
          ? display.color.trim()
          : undefined,
      tfShowNames:
        typeof display.tfShowNames === "boolean"
          ? display.tfShowNames
          : undefined,
      tfLabelSize:
        typeof display.tfLabelSize === "number"
          ? display.tfLabelSize
          : undefined,
      tfVisibleFrames: Array.isArray(display.tfVisibleFrames)
        ? display.tfVisibleFrames.filter(
            (item): item is string =>
              typeof item === "string" && item.trim().length > 0,
          )
        : undefined,
    };
  }
  function parseSavedNavLayout(
    rawValue: string | undefined,
  ): SavedNavPanelLayout | null {
    if (!rawValue) {
      return null;
    }
    try {
      const parsed = JSON.parse(rawValue) as Record<string, unknown>;
      const hasSidePanels = Array.isArray(parsed.sidePanels);
      const hasFullPanels = Array.isArray(parsed.fullPanels);
      const hasMainDisplays = Array.isArray(parsed.mainDisplays);
      const hasNavDelayTopicsText =
        typeof parsed.navDelayTopicsText === "string";
      const sidePanels = Array.isArray(parsed.sidePanels)
        ? parsed.sidePanels
            .map((item, index) =>
              sanitizeNavPanelItem(item, "side-panel", index),
            )
            .filter((item): item is NavPanelItem => item !== null)
        : [];
      const fullPanels = Array.isArray(parsed.fullPanels)
        ? parsed.fullPanels
            .map((item, index) =>
              sanitizeNavPanelItem(item, "full-panel", index),
            )
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
        navDelayTopicsText: hasNavDelayTopicsText
          ? String(parsed.navDelayTopicsText ?? "")
          : "",
        hasSidePanels,
        hasFullPanels,
        hasMainDisplays,
        hasNavDelayTopicsText,
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
      const leftIsDefault = defaultNavTopicOptions.some(
        (topic) => topic.key === left.key,
      );
      const rightIsDefault = defaultNavTopicOptions.some(
        (topic) => topic.key === right.key,
      );
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
      mapOpacity: kind === "map" ? 0.94 : undefined,
      pointSize: kind === "pointcloud" ? 0.08 : undefined,
      pointEmissiveIntensity: kind === "pointcloud" ? 0 : undefined,
      hzLimit: kind === "pointcloud" ? 5 : undefined,
      pointColorMode: kind === "pointcloud" ? "solid" : undefined,
      color:
        kind === "pointcloud" ||
        kind === "path" ||
        kind === "pose" ||
        kind === "marker" ||
        kind === "bspline" ||
        kind === "twist"
          ? defaultMainDisplayColor(option.key, kind)
          : undefined,
      tfShowNames: kind === "tf" ? true : undefined,
      tfLabelSize: kind === "tf" ? 0.5 : undefined,
      tfVisibleFrames: kind === "tf" ? [] : undefined,
    };
  }
  function hasMainDisplay(topicKey: string) {
    return navMainDisplays.value.some((display) => display.topic === topicKey);
  }
  function hasMapMainDisplay() {
    return navMainDisplays.value.some((display) => display.kind === "map");
  }
  function hasTfMainDisplay() {
    return navMainDisplays.value.some((display) => display.kind === "tf");
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

    const mapTopicKey = formValues.map_topic || "/debug/loaded_pointcloud_map";
    const defaults = [
      {
        key: "/map",
        type: "nav_msgs/msg/OccupancyGrid",
        label: "二维地图",
        note: "",
      },
      ...(mapTopicKey === "/map"
        ? []
        : [
            {
              key: mapTopicKey,
              type: "sensor_msgs/msg/PointCloud2",
              label: "地图点云",
              note: "",
            },
          ]),
      {
        key: "/points_aligned",
        type: "sensor_msgs/msg/PointCloud2",
        label: "对齐结果点云",
        note: "",
      },
      {
        key: "/cloud_registered_bl",
        type: "sensor_msgs/msg/PointCloud2",
        label: "NDT 输入点云",
        note: "",
      },
      { key: "/tf", type: "tf2_msgs/msg/TFMessage", label: "TF 树", note: "" },
      {
        key: formValues.path_topic || "/plan",
        type: "nav_msgs/msg/Path",
        label: "全局路径",
        note: "",
      },
      {
        key: formValues.pose_topic || "/ndt_pose",
        type: "geometry_msgs/msg/PoseStamped",
        label: "NDT 位姿",
        note: "",
      },
      {
        key: "/geneox_mid360_obstacle",
        type: "std_msgs/msg/UInt8",
        label: "冷静区/危险区",
        note: "",
      },
    ];

    navMainDisplays.value = defaults.map(topicOptionToDisplay);
  }
  function resolveDefaultMapTopicOption() {
    const candidates = rosTopicOptions.value.filter(
      (topic) => inferDisplayKind(topic.key, topic.type) === "map",
    );
    return (
      candidates.find((topic) => topic.key === formValues.map_topic) ||
      candidates.find((topic) => topic.key === "/map") ||
      defaultNavTopicOptions.find((topic) => topic.key === "/map") ||
      null
    );
  }
  function ensureMapMainDisplay() {
    if (hasMapMainDisplay()) {
      return;
    }
    const mapTopic = resolveDefaultMapTopicOption();
    if (!mapTopic) {
      return;
    }
    navMainDisplays.value = [
      topicOptionToDisplay(mapTopic),
      ...navMainDisplays.value,
    ];
  }
  /**
   * 历史布局可能只保存了地图和点云显示项；机器人位姿依赖 TF，必须保留一个可视化入口。
   * 现场优先使用汇总的 /display/tf，未发现时仍由三维组件订阅 /tf 与 /tf_static 维持变换链。
   */
  function ensureRobotTfMainDisplay() {
    if (hasTfMainDisplay()) {
      return;
    }
    const tfTopic =
      rosTopicOptions.value.find((topic) => topic.key === "/display/tf") || {
        key: "/display/tf",
        label: "机器人 TF",
        type: "tf2_msgs/msg/TFMessage",
        note: "用于显示机器人坐标系与坐标变换链路。",
      };
    navMainDisplays.value = [
      ...navMainDisplays.value,
      topicOptionToDisplay(tfTopic),
    ];
  }
  async function loadRosDataSourceConfigForNav() {
    let shouldApplyDefaultDisplays = true;
    rosDataSourceConfigLoaded.value = false;
    try {
      const config = await fetchRosDataSourceConfig();
      saveLocalRosNavConfig(config);
      if (applyRosDataSourceConfig(config)) {
        shouldApplyDefaultDisplays = false;
      }
    } catch {
      const localConfig = loadLocalRosNavConfig();
      if (localConfig && applyRosDataSourceConfig(localConfig)) {
        shouldApplyDefaultDisplays = false;
      }
    } finally {
      if (shouldApplyDefaultDisplays) {
        ensureDefaultNavDisplays();
      }
      ensureMapMainDisplay();
      ensureRobotTfMainDisplay();
      rosDataSourceConfigLoaded.value = true;
      void reconnectNavDelayPanel();
      if (!navSessionAutoSaved) {
        navSessionAutoSaved = true;
        void saveRosNavConfig({
          successMessage: "",
          failurePrefix: "导航模块默认配置自动保存失败",
        });
      }
    }
  }
  async function saveRosNavConfig(options?: {
    successMessage?: string;
    failurePrefix?: string;
  }) {
    rosDataSourceSaving.value = true;
    try {
      const config = buildRosDataSourceConfig();
      saveLocalRosNavConfig(config);
      const saved = await saveRosDataSourceConfig(config);
      saveLocalRosNavConfig(saved);
      formValues.ros_provider = saved.provider;
      formValues.ros_bridge_url =
        saved.options.url || formValues.ros_bridge_url || "";
      formValues.ros_api_service =
        saved.options.rosapi_service || formValues.ros_api_service || "";
      formValues.timeout_ms = normalizeRosBridgeTimeoutMs(
        saved.options.timeout_ms || formValues.timeout_ms,
      );
      formValues.robot_tf_frame = normalizeRobotTfFrame(
        saved.options.robot_tf_frame || formValues.robot_tf_frame,
      );
      if (options?.successMessage !== undefined) {
        rosTopicsMessage.value = options.successMessage;
      } else {
        rosTopicsMessage.value = "ROS 数据源配置已保存。";
      }
    } catch (error) {
      const config = buildRosDataSourceConfig();
      saveLocalRosNavConfig(config);
      if (options?.successMessage !== undefined) {
        rosTopicsMessage.value = options.successMessage;
      } else {
        rosTopicsMessage.value = "ROS 数据源配置已保存到本机。";
      }
      appendRosRuntimeLog(
        "warning",
        `${options?.failurePrefix || "后端配置保存失败"}，已写入本机缓存: ${(error as Error).message}`,
      );
    } finally {
      rosDataSourceSaving.value = false;
    }
  }
  function saveRosNavConfigOnExit() {
    if (navExitSaveInFlight || !rosDataSourceConfigLoaded.value) {
      return;
    }
    navExitSaveInFlight = saveRosNavConfig({
      successMessage: "",
      failurePrefix: "退出导航模块前自动保存失败",
    }).finally(() => {
      navExitSaveInFlight = null;
    });
  }
  async function inspectRosNavSource() {
    rosInspectLoading.value = true;
    rosInspectResult.value = null;
    try {
      rosInspectResult.value = await inspectRosDataSource(
        buildRosDataSourceConfig(),
      );
    } catch (error) {
      try {
        rosInspectResult.value = await inspectRosDataSourceDirect(
          buildRosDataSourceConfig(),
        );
        if (rosInspectResult.value.status === "success") {
          appendRosRuntimeLog(
            "info",
            `已通过前端直连完成接入检测: ${rosInspectResult.value.message}`,
          );
        } else {
          rosInspectResult.value.detected_hints = [
            `后端检测不可用: ${(error as Error).message}`,
            ...rosInspectResult.value.detected_hints,
          ];
        }
      } catch (directError) {
        rosInspectResult.value = {
          provider: formValues.ros_provider || "rosbridge",
          status: "error",
          message: `后端和前端直连检测均失败: ${(directError as Error).message}`,
          capabilities: [],
          detected_hints: [`后端检测失败: ${(error as Error).message}`],
          topics_count: 0,
        };
      }
    } finally {
      rosInspectLoading.value = false;
    }
  }
  async function refreshRosTopics() {
    rosTopicsLoading.value = true;
    try {
      let response;
      try {
        response = await fetchRosTopics(buildRosDataSourceConfig());
      } catch (error) {
        response = await listRosTopicsDirect(
          buildRosDataSourceConfig(),
          undefined,
          {
            serviceTimeoutMs: 15000,
          },
        );
        appendRosRuntimeLog(
          "info",
          `后端话题接口不可用，已改用前端直连 rosapi: ${(error as Error).message}`,
        );
      }
      rosTopicsMessage.value = response.message;
      rosTopicOptions.value =
        response.topics.length > 0
          ? mergeRosTopicOptions(response.topics.map(mapTopicItemToOption))
          : defaultNavTopicOptions;
      ensureMapMainDisplay();
      ensureRobotTfMainDisplay();
    } catch (error) {
      rosTopicsMessage.value = `读取 topic 失败: ${(error as Error).message}`;
      rosTopicOptions.value = defaultNavTopicOptions;
      ensureMapMainDisplay();
    } finally {
      rosTopicsLoading.value = false;
    }
  }
  async function loadRosRuntimeParamsPanel() {
    if (props.tool.key !== "ros_nav_test") {
      return;
    }
    rosRuntimeParamsLoading.value = true;
    try {
      const previousStatus = rosRuntimeParams.value?.status || "";
      let response;
      try {
        response = await fetchRosRuntimeParams(buildRosDataSourceConfig());
      } catch (error) {
        response = await listRosRuntimeParamsDirect(buildRosDataSourceConfig());
        appendRosRuntimeLog(
          "info",
          `后端参数接口不可用，已改用前端直连 rosapi: ${(error as Error).message}`,
        );
      }
      rosRuntimeParams.value = response;
      rosRuntimeParamsMessage.value = response.message;
      if (response.status === "partial") {
        appendRosRuntimeLog("warning", `运行时参数窗口: ${response.message}`);
      } else if (response.status === "error") {
        appendRosRuntimeLog("error", `运行时参数窗口: ${response.message}`);
      } else if (previousStatus !== "success") {
        appendRosRuntimeLog("info", `运行时参数窗口: ${response.message}`);
      }
    } catch (error) {
      rosRuntimeParams.value = null;
      rosRuntimeParamsMessage.value = `读取运行时参数失败: ${(error as Error).message}`;
      appendRosRuntimeLog("error", rosRuntimeParamsMessage.value);
    } finally {
      rosRuntimeParamsLoading.value = false;
    }
  }
  function formatRuntimeParamValue(value: unknown) {
    if (value === null || value === undefined) {
      return "-";
    }
    if (
      typeof value === "string" ||
      typeof value === "number" ||
      typeof value === "boolean"
    ) {
      return String(value);
    }
    try {
      return JSON.stringify(value);
    } catch {
      return String(value);
    }
  }
  function toggleNavRuntimeParamsPanel() {
    navRuntimeParamsPanelCollapsed.value =
      !navRuntimeParamsPanelCollapsed.value;
  }
  function toggleNavRuntimeGroup(groupKey: string) {
    navRuntimeGroupCollapsedMap.value = {
      ...navRuntimeGroupCollapsedMap.value,
      [groupKey]: !isNavRuntimeGroupCollapsed(groupKey),
    };
  }
  function isNavRuntimeGroupCollapsed(groupKey: string) {
    return navRuntimeGroupCollapsedMap.value[groupKey] !== false;
  }
  function navRuntimeNodeKey(groupKey: string, nodeName: string) {
    return `${groupKey}:${nodeName}`;
  }
  function toggleNavRuntimeNode(groupKey: string, nodeName: string) {
    const key = navRuntimeNodeKey(groupKey, nodeName);
    navRuntimeNodeCollapsedMap.value = {
      ...navRuntimeNodeCollapsedMap.value,
      [key]: !isNavRuntimeNodeCollapsed(groupKey, nodeName),
    };
  }
  function isNavRuntimeNodeCollapsed(groupKey: string, nodeName: string) {
    return (
      navRuntimeNodeCollapsedMap.value[
        navRuntimeNodeKey(groupKey, nodeName)
      ] !== false
    );
  }
  function buildRosLiveConfig() {
    return {
      provider: (formValues.ros_provider || "rosbridge").trim() || "rosbridge",
      url: (formValues.ros_bridge_url || "").trim(),
      timeoutMs: Number(normalizeRosBridgeTimeoutMs(formValues.timeout_ms)),
    };
  }
  function eulerToQuaternion(roll: number, pitch: number, yaw: number) {
    const halfRoll = roll / 2;
    const halfPitch = pitch / 2;
    const halfYaw = yaw / 2;
    const cr = Math.cos(halfRoll);
    const sr = Math.sin(halfRoll);
    const cp = Math.cos(halfPitch);
    const sp = Math.sin(halfPitch);
    const cy = Math.cos(halfYaw);
    const sy = Math.sin(halfYaw);
    return {
      x: sr * cp * cy - cr * sp * sy,
      y: cr * sp * cy + sr * cp * sy,
      z: cr * cp * sy - sr * sp * cy,
      w: cr * cp * cy + sr * sp * sy,
    };
  }
  async function publishRosMessage(
    topicName: string,
    messageType: string,
    message: Record<string, unknown>,
  ) {
    const adapter = await ensureNavControlAdapterConnected();
    adapter.publish(topicName, messageType, message);
    appendRosRuntimeLog("info", `消息下发成功: ${topicName} (${messageType})`);
  }
  async function callRosService(
    serviceName: string,
    serviceType: string,
    args: Record<string, unknown>,
  ) {
    const adapter = createRosLiveAdapter({
      ...buildRosLiveConfig(),
      adapterName: `调用 ${serviceName}`,
      autoReconnect: false,
      onError: (event) => {
        appendRosRuntimeLog(
          event.recoverable ? "warning" : "error",
          `${event.scope}: ${event.message}${event.detail ? ` (${event.detail})` : ""}`,
        );
      },
    });
    try {
      await adapter.connect();
      const response = await adapter.callService(
        serviceName,
        serviceType,
        args,
      );
      appendRosRuntimeLog(
        "info",
        `服务调用成功: ${serviceName} (${serviceType})`,
      );
      return response;
    } finally {
      adapter.disconnect();
    }
  }
  function nextRequestPlanId() {
    const requestPlanId = `web_test_${String(navGoalSequence.value).padStart(3, "0")}`;
    navGoalSequence.value += 1;
    return requestPlanId;
  }
  function rosHeaderStampNow() {
    const nowMs = Date.now();
    const sec = Math.floor(nowMs / 1000);
    return {
      sec,
      nanosec: (nowMs - sec * 1000) * 1_000_000,
    };
  }
  function enterInitialPoseMode() {
    if (
      navInteractionMode.value === "initialpose" ||
      initialPoseCandidateActive.value ||
      navViewerRef.value?.getInitialPoseCandidate()
    ) {
      cancelInitialPoseCandidate();
      return;
    }
    const entering = true;
    if (entering) {
      navViewerRef.value?.clearInitialPoseCandidate();
    }
    navInteractionMode.value = entering ? "initialpose" : "none";
    navControlMessage.value =
      navInteractionMode.value === "initialpose"
        ? "已进入初始化定位模式，请在主视图点击并拖动方向。"
        : "已退出初始化定位模式。";
  }
  function enterNavGoalMode() {
    navInteractionMode.value =
      navInteractionMode.value === "navgoal" ? "none" : "navgoal";
    navControlMessage.value =
      navInteractionMode.value === "navgoal"
        ? "已进入导航目标模式，请在主视图点击并拖动方向。"
        : "已退出导航目标模式。";
  }
  async function publishInitialPose(
    x: number,
    y: number,
    yaw: number,
    z = 0,
    roll = 0,
    pitch = 0,
  ) {
    const orientation = eulerToQuaternion(roll, pitch, yaw);
    await publishRosMessage(
      "/initialpose",
      "geometry_msgs/msg/PoseWithCovarianceStamped",
      {
        header: {
          stamp: rosHeaderStampNow(),
          frame_id: formValues.fixed_frame || "map",
        },
        pose: {
          pose: {
            position: {
              x,
              y,
              z,
            },
            orientation,
          },
          covariance: [
            0.25, 0, 0, 0, 0, 0, 0, 0.25, 0, 0, 0, 0, 0, 0, 0.25, 0, 0, 0, 0, 0,
            0, 0.0685, 0, 0, 0, 0, 0, 0, 0.0685, 0, 0, 0, 0, 0, 0, 0.0685,
          ],
        },
      },
    );
  }
  function parseManualInitialPoseValue(value: string, label: string) {
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) {
      throw new Error(`${label} 不是有效数值`);
    }
    return parsed;
  }
  async function submitManualInitialPose() {
    navControlLoading.value = true;
    try {
      const x = parseManualInitialPoseValue(manualInitialPoseX.value, "x");
      const y = parseManualInitialPoseValue(manualInitialPoseY.value, "y");
      const z = parseManualInitialPoseValue(
        manualInitialPoseZ.value || "0",
        "z",
      );
      const yaw = parseManualInitialPoseValue(
        manualInitialPoseYaw.value,
        "yaw",
      );
      await publishInitialPose(x, y, yaw, z);
      navInteractionMode.value = "none";
      navControlMessage.value = `已下发手动初始化定位: (${x.toFixed(3)}, ${y.toFixed(3)}, ${z.toFixed(3)}, yaw=${yaw.toFixed(2)})`;
    } catch (error) {
      navControlMessage.value = `手动初始化定位失败: ${(error as Error).message}`;
    } finally {
      navControlLoading.value = false;
    }
  }
  function selectedInitialPosePointCloudOption() {
    return (
      initialPosePointCloudTopicOptions.value.find(
        (item) => item.key === initialPosePointCloudTopic.value,
      ) ??
      rosTopicOptions.value.find(
        (item) => item.key === initialPosePointCloudTopic.value,
      ) ??
      null
    );
  }
  function normalizedInitialPosePointCloudSize() {
    const parsed = Number(initialPosePointCloudSize.value);
    return Math.min(
      0.8,
      Math.max(0.005, Number.isFinite(parsed) ? parsed : 0.055),
    );
  }
  function normalizedOfflineMapVoxelLeaf() {
    const parsed = Number(formValues.offline_map_voxel_leaf_m || "0.20");
    return Math.min(5, Math.max(0.01, Number.isFinite(parsed) ? parsed : 0.2));
  }
  function normalizedOfflineMapOccupancyVoxel() {
    const parsed = Number(formValues.offline_map_occupancy_voxel_m || "0.30");
    return Math.min(2, Math.max(0.05, Number.isFinite(parsed) ? parsed : 0.3));
  }
  function normalizedOfflineMapMaxPoints() {
    const parsed = Number(formValues.offline_map_max_points || "60000");
    return Math.min(
      300000,
      Math.max(1000, Number.isFinite(parsed) ? Math.round(parsed) : 60000),
    );
  }
  function normalizedOfflineMapMaxVoxels() {
    const parsed = Number(formValues.offline_map_max_voxels || "60000");
    return Math.min(
      200000,
      Math.max(1000, Number.isFinite(parsed) ? Math.round(parsed) : 60000),
    );
  }
  function normalizedOfflineMapDisplayMode(value = formValues.offline_map_display_mode) {
    return value === "pointcloud" || value === "render" ? value : "voxel";
  }
  function normalizedOfflineMapPointSize(value = formValues.offline_map_point_size) {
    const parsed = Number(value || "0.06");
    return Math.min(1, Math.max(0.005, Number.isFinite(parsed) ? parsed : 0.06));
  }
  function normalizedOfflineMapColor(value: string | undefined, fallback: string) {
    const candidate = (value || "").trim();
    return /^#[0-9a-fA-F]{6}$/.test(candidate) ? candidate : fallback;
  }
  /** 将离线地图外观配置即时同步至三维场景；PCD 尚未加载时只保存待下次加载使用。 */
  function updateOfflineMapVisualSettings() {
    navViewerRef.value?.updateOfflineMapVisualSettings({
      displayMode: normalizedOfflineMapDisplayMode(),
      pointSize: normalizedOfflineMapPointSize(),
      pointColor: normalizedOfflineMapColor(formValues.offline_map_point_color, "#d7dee8"),
      voxelColor: normalizedOfflineMapColor(formValues.offline_map_voxel_color, "#a79d86"),
    });
  }
  function offlineMapDisplayedVoxelCount() {
    const occupancy = offlineMapPreview.value?.occupancy;
    if (occupancy?.displayed_count && occupancy.displayed_count > 0) {
      return occupancy.displayed_count;
    }
    if (occupancy?.occupied_count && occupancy.occupied_count > 0) {
      return occupancy.occupied_count;
    }
    return offlineMapPreview.value?.pcd?.sampled_count ?? 0;
  }
  function offlineMapTotalVoxelCount() {
    const occupancy = offlineMapPreview.value?.occupancy;
    if (occupancy?.occupied_count && occupancy.occupied_count > 0) {
      return occupancy.occupied_count;
    }
    return offlineMapDisplayedVoxelCount();
  }
  function normalizedInitialPoseBaseHeightOffset() {
    const parsed = Number(
      formValues.initial_pose_base_height_offset_m || "0.35",
    );
    return Math.min(3, Math.max(-1, Number.isFinite(parsed) ? parsed : 0.35));
  }
  function normalizedInitialPoseGroundNormalRadius() {
    const parsed = Number(
      formValues.initial_pose_ground_normal_radius_m || "0.80",
    );
    return Math.min(3, Math.max(0.15, Number.isFinite(parsed) ? parsed : 0.8));
  }
  function normalizedInitialPoseGroundMaxSlope() {
    const parsed = Number(formValues.initial_pose_ground_max_slope_deg || "30");
    return Math.min(75, Math.max(1, Number.isFinite(parsed) ? parsed : 30));
  }
  function openInitialPoseTopicDropdown() {
    initialPoseTopicDropdownOpen.value = true;
  }
  function closeInitialPoseTopicDropdown() {
    initialPoseTopicDropdownOpen.value = false;
  }
  function selectInitialPosePointCloudTopic(topic: NavTopicOption) {
    initialPosePointCloudTopic.value = topic.key;
    closeInitialPoseTopicDropdown();
  }
  function handleInitialPoseTopicInputKeydown(event: KeyboardEvent) {
    if (event.key === "Escape") {
      closeInitialPoseTopicDropdown();
      return;
    }
    if (event.key === "ArrowDown") {
      openInitialPoseTopicDropdown();
    }
  }
  function handleDocumentMouseDown(event: MouseEvent) {
    const target = event.target;
    if (!(target instanceof Element)) {
      closeInitialPoseTopicDropdown();
      return;
    }
    if (target.closest(".initial-pose-topic-field")) {
      return;
    }
    closeInitialPoseTopicDropdown();
  }
  async function captureInitialPosePointCloudFrame() {
    const viewer = navViewerRef.value;
    if (!viewer?.getInitialPoseCandidate()) {
      navControlMessage.value = "请先点击“初始化定位”，在主视图拖出候选位姿。";
      return;
    }
    const topic = initialPosePointCloudTopic.value.trim();
    if (!topic) {
      navControlMessage.value = "请选择或输入初始化点云 topic。";
      return;
    }

    initialPosePointCloudLoading.value = true;
    navControlMessage.value = `正在抓取 ${topic} 的点云帧...`;
    let unsubscribe: (() => void) | null = null;
    let timeoutHandle: number | undefined;
    try {
      const pointSize = normalizedInitialPosePointCloudSize();
      const option = selectedInitialPosePointCloudOption();
      const messageType = option?.type || "sensor_msgs/msg/PointCloud2";
      const adapter = await ensureNavControlAdapterConnected();
      const message = await new Promise<any>((resolve, reject) => {
        timeoutHandle = window.setTimeout(() => {
          (unsubscribe as (() => void) | null)?.();
          unsubscribe = null;
          reject(
            new Error(`等待 ${topic} 新点云帧超时，请确认 ROS 节点仍在发布`),
          );
        }, 15000);
        unsubscribe = adapter.subscribe(
          topic,
          messageType,
          (nextMessage) => {
            if (timeoutHandle) {
              window.clearTimeout(timeoutHandle);
              timeoutHandle = undefined;
            }
            (unsubscribe as (() => void) | null)?.();
            unsubscribe = null;
            resolve(nextMessage);
          },
          { queueLength: 1 },
        );
      });
      const result = viewer.attachInitialPosePointCloud({
        topic,
        message,
        color: "#f4d35e",
        pointSize,
        pointColorMode: "layered",
      });
      navControlMessage.value = result.message;
    } catch (error) {
      navControlMessage.value = `抓取初始化点云失败: ${(error as Error).message}`;
    } finally {
      if (timeoutHandle) {
        window.clearTimeout(timeoutHandle);
      }
      (unsubscribe as (() => void) | null)?.();
      initialPosePointCloudLoading.value = false;
    }
  }
  async function loadOfflineMapPointCloud() {
    const pcdPath = formValues.offline_map_pcd?.trim();
    if (!pcdPath) {
      offlineMapMessage.value = "请先选择离线地图 PCD。";
      return;
    }
    offlineMapLoading.value = true;
    offlineMapMessage.value = "正在加载离线地图点云...";
    try {
      const result = canUseNativeRosFilePicker()
        ? await buildNativeOfflineMapPreview({
            pcdPath,
            yamlPath: formValues.offline_map_yaml?.trim() || "",
            pgmPath: formValues.offline_map_pgm?.trim() || "",
            voxelLeafM: normalizedOfflineMapVoxelLeaf(),
            occupancyVoxelM: normalizedOfflineMapOccupancyVoxel(),
            maxPoints: normalizedOfflineMapMaxPoints(),
            maxVoxels: normalizedOfflineMapMaxVoxels(),
          })
        : await fetchRosNavOfflineMapPreview(
            pcdPath,
            formValues.offline_map_yaml?.trim() || "",
            formValues.offline_map_pgm?.trim() || "",
            String(normalizedOfflineMapVoxelLeaf()),
            String(normalizedOfflineMapOccupancyVoxel()),
            String(normalizedOfflineMapMaxPoints()),
            String(normalizedOfflineMapMaxVoxels()),
          );
      offlineMapPreview.value = result;
      offlineMapDisplayMode.value = normalizedOfflineMapDisplayMode();
      const attachResult =
        navViewerRef.value?.attachOfflineMapPointCloud(result);
      updateOfflineMapVisualSettings();
      offlineMapMessage.value =
        attachResult?.message ||
        `已加载离线地图点云: ${result.pcd.sampled_count} / ${result.pcd.input_points} 点`;
    } catch (error) {
      const message = (error as Error).message;
      offlineMapMessage.value =
        message === "Not Found" || message.includes("404")
          ? "离线地图点云加载失败: 当前后端还没有加载离线地图接口，请重启 backend 后再试。"
          : `离线地图点云加载失败: ${message}`;
    } finally {
      offlineMapLoading.value = false;
    }
  }
  function clearOfflineMapPointCloud() {
    navViewerRef.value?.clearOfflineMapPointCloud();
    offlineMapPreview.value = null;
    offlineMapDisplayMode.value = "voxel";
    offlineMapMessage.value = "已清除离线地图点云。";
  }
  function setOfflineMapDisplayMode(mode: OfflineMapDisplayMode) {
    offlineMapDisplayMode.value = mode;
    formValues.offline_map_display_mode = mode;
    const result = navViewerRef.value?.setOfflineMapDisplayMode(mode);
    offlineMapMessage.value = result?.message || "请先加载离线地图。";
  }
  function cancelInitialPoseCandidate() {
    navViewerRef.value?.clearInitialPoseCandidate();
    navInteractionMode.value = "none";
    initialPoseCandidateActive.value = false;
    navControlMessage.value = "已取消初始化候选位姿。";
  }
  async function confirmInitialPoseCandidate() {
    const candidate = navViewerRef.value?.getInitialPoseCandidate() ?? null;
    if (!candidate) {
      navControlMessage.value = "当前没有可确认的初始化候选位姿。";
      return;
    }
    navControlLoading.value = true;
    try {
      await publishInitialPose(
        candidate.x,
        candidate.y,
        candidate.yaw,
        candidate.z,
        candidate.roll,
        candidate.pitch,
      );
      navViewerRef.value?.clearInitialPoseCandidate();
      navInteractionMode.value = "none";
      initialPoseCandidateActive.value = false;
      navControlMessage.value = `已下发 3D 初始化定位: (${candidate.x.toFixed(3)}, ${candidate.y.toFixed(3)}, ${candidate.z.toFixed(3)}, roll=${candidate.roll.toFixed(2)}, pitch=${candidate.pitch.toFixed(2)}, yaw=${candidate.yaw.toFixed(2)})`;
    } catch (error) {
      navControlMessage.value = `确认初始化定位失败: ${(error as Error).message}`;
    } finally {
      navControlLoading.value = false;
    }
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
  async function handleNavViewerInteraction(payload: {
    mode: "initialpose" | "navgoal";
    x: number;
    y: number;
    z?: number;
    roll?: number;
    pitch?: number;
    yaw: number;
  }) {
    navControlLoading.value = true;
    try {
      if (payload.mode === "initialpose") {
        initialPoseCandidateActive.value = true;
        navControlMessage.value = `已生成初始化候选: (${payload.x.toFixed(2)}, ${payload.y.toFixed(2)}, z=${(payload.z ?? 0).toFixed(2)}, yaw=${payload.yaw.toFixed(2)})，请抓取点云后微调并确认。`;
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
  async function triggerAutoLocalization() {
    navControlLoading.value = true;
    try {
      const response = await callRosService(
        "/fallback_global_localization_trigger",
        "std_srvs/srv/Trigger",
        {},
      );
      const success = response?.success === true;
      const message =
        typeof response?.message === "string" && response.message.trim()
          ? response.message
          : "";
      navControlMessage.value = success
        ? `已触发自动定位${message ? `: ${message}` : ""}`
        : `自动定位触发返回失败${message ? `: ${message}` : ""}`;
    } catch (error) {
      navControlMessage.value = `自动定位触发失败: ${(error as Error).message}`;
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
      navRecordingFilesMessage.value =
        response.items.length > 0
          ? `已读取 ${response.items.length} 个录制文件。`
          : "录制目录当前没有文件。";
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
      const normalizedJson = stripRecordingEntriesForPreview(jsonText);
      const parsed = JSON.parse(normalizedJson) as NavRecordingSavePayload;
      return {
        ...parsed,
        entries: [],
        metric_series: parsed.metric_series.map((metric) => ({
          ...metric,
          samples: downsampleNavRecordingSamples(metric.samples),
        })),
      };
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
  function stripRecordingEntriesForPreview(jsonText: string) {
    const keyIndex = jsonText.indexOf('"entries"');
    if (keyIndex < 0) {
      return jsonText;
    }
    const arrayStart = jsonText.indexOf("[", keyIndex);
    if (arrayStart < 0) {
      return jsonText;
    }
    let inString = false;
    let isEscaped = false;
    let depth = 0;
    for (let index = arrayStart; index < jsonText.length; index += 1) {
      const char = jsonText[index];
      if (inString) {
        if (isEscaped) {
          isEscaped = false;
        } else if (char === "\\") {
          isEscaped = true;
        } else if (char === '"') {
          inString = false;
        }
        continue;
      }
      if (char === '"') {
        inString = true;
        continue;
      }
      if (char === "[") {
        depth += 1;
        continue;
      }
      if (char !== "]") {
        continue;
      }
      depth -= 1;
      if (depth === 0) {
        return `${jsonText.slice(0, arrayStart)}[]${jsonText.slice(index + 1)}`;
      }
    }
    return jsonText;
  }
  function downsampleNavRecordingSamples(
    samples: Array<{ offset_ms: number; value: number }>,
  ) {
    if (samples.length <= NAV_RECORDING_CHART_MAX_SAMPLES) {
      return samples;
    }
    const nextSamples: Array<{ offset_ms: number; value: number }> = [];
    const step = samples.length / NAV_RECORDING_CHART_MAX_SAMPLES;
    for (let index = 0; index < NAV_RECORDING_CHART_MAX_SAMPLES; index += 1) {
      const sampleIndex = Math.min(
        samples.length - 1,
        Math.round(index * step),
      );
      nextSamples.push(samples[sampleIndex]);
    }
    return nextSamples;
  }
  function buildNavRecordingPreviewText(rawText: string) {
    const stripped = stripNavRecordingPayload(rawText);
    const lines = stripped.split(/\r?\n/);
    const truncatedLines =
      lines.length > NAV_RECORDING_PREVIEW_MAX_LINES
        ? lines.slice(0, NAV_RECORDING_PREVIEW_MAX_LINES)
        : lines;
    let previewText = truncatedLines.join("\n");
    let truncated = truncatedLines.length < lines.length;
    if (previewText.length > NAV_RECORDING_PREVIEW_MAX_CHARS) {
      previewText = previewText.slice(0, NAV_RECORDING_PREVIEW_MAX_CHARS);
      truncated = true;
    }
    if (!truncated) {
      return previewText;
    }
    return `${previewText}\n\n[预览已截断：文件较大，这里仅展示前 ${NAV_RECORDING_PREVIEW_MAX_LINES} 行 / ${NAV_RECORDING_PREVIEW_MAX_CHARS} 字符，录制原文件仍完整保留。]`;
  }
  function resetNavRecordingChartState(
    payload: NavRecordingSavePayload | null,
  ) {
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
    return (
      payload.metric_series.find(
        (item) => item.label === navRecordingChartMetricLabel.value,
      ) ||
      payload.metric_series[0] ||
      null
    );
  });
  const activeNavRecordingMetricSamples = computed(() => {
    const metric = activeNavRecordingMetric.value;
    if (!metric) {
      return [];
    }
    return metric.samples.filter(
      (sample) =>
        sample.offset_ms >= navRecordingChartRangeStart.value &&
        sample.offset_ms <= navRecordingChartRangeEnd.value,
    );
  });
  function navRecordingChartTimeText(offsetMs: number) {
    const payload = navRecordingParsedPayload.value;
    if (!payload) {
      return "-";
    }
    return new Date(payload.started_at_ms + offsetMs).toLocaleTimeString(
      "zh-CN",
      {
        hour12: false,
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        fractionalSecondDigits: 3,
      },
    );
  }
  function navRecordingChartPolylinePoints() {
    const samples = activeNavRecordingMetricSamples.value;
    if (samples.length === 0) {
      return "";
    }
    const rangeSpan = Math.max(
      1,
      navRecordingChartRangeEnd.value - navRecordingChartRangeStart.value,
    );
    const values = samples.map((item) => item.value);
    const minValue = Math.min(...values);
    const maxValue = Math.max(...values);
    const valueSpan = Math.max(1e-6, maxValue - minValue);
    return samples
      .map((sample) => {
        const x =
          ((sample.offset_ms - navRecordingChartRangeStart.value) / rangeSpan) *
          1000;
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
    const currentSpan = Math.max(
      1,
      navRecordingChartRangeEnd.value - navRecordingChartRangeStart.value,
    );
    const nextSpan = Math.max(
      200,
      Math.min(totalDuration, currentSpan * factor),
    );
    const anchorOffset =
      navRecordingChartRangeStart.value + currentSpan * anchorRatio;
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
    const anchorRatio = Math.max(
      0,
      Math.min(1, (event.clientX - rect.left) / Math.max(1, rect.width)),
    );
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
    const ratio = Math.max(
      0,
      Math.min(1, (event.clientX - rect.left) / Math.max(1, rect.width)),
    );
    const hoverOffset =
      navRecordingChartRangeStart.value +
      ratio *
        Math.max(
          1,
          navRecordingChartRangeEnd.value - navRecordingChartRangeStart.value,
        );
    const nearest = metric.samples.reduce((best, sample) => {
      if (!best) {
        return sample;
      }
      return Math.abs(sample.offset_ms - hoverOffset) <
        Math.abs(best.offset_ms - hoverOffset)
        ? sample
        : best;
    }, metric.samples[0]);
    if (nearest) {
      navRecordingChartHover.value = {
        offsetMs: nearest.offset_ms,
        value: nearest.value,
        x:
          ((nearest.offset_ms - navRecordingChartRangeStart.value) /
            Math.max(
              1,
              navRecordingChartRangeEnd.value -
                navRecordingChartRangeStart.value,
            )) *
          1000,
      };
    }
    if (!navRecordingChartDragging.value) {
      return;
    }
    const pixelDelta = event.clientX - navRecordingChartDragAnchorX;
    const totalDuration = Math.max(1, payload.duration_ms);
    const currentSpan = Math.max(
      1,
      navRecordingChartDragRangeEnd - navRecordingChartDragRangeStart,
    );
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
    navRecordingChartRangeEnd.value = Math.min(
      totalDuration,
      Math.round(Math.max(nextStart + 1, nextEnd)),
    );
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
      navRecordingPreviewText.value = buildNavRecordingPreviewText(rawText);
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
  function hasDelayTopic(topicKey: string) {
    return normalizeNavDelayTopicsInput(navDelayTopicsInput.value).includes(
      topicKey,
    );
  }
  function setNavDelayTopics(topics: string[]) {
    const normalized = normalizeNavDelayTopicsInput(topics.join("\n"));
    navDelayTopicsInput.value = normalized.join("\n");
    navDelayTopicsApplied.value = navDelayTopicsInput.value;
    navDelayOverviewSelectionMap.value = Object.fromEntries(
      normalized.map((topic) => [
        topic,
        isNavDelayOverviewTopicSelected(topic),
      ]),
    );
    disconnectNavDelayPanel();
    if (navDelayPanelCollapsed.value || props.tool.key !== "ros_nav_test") {
      navDelayMessage.value = "已更新延迟总览话题，展开窗口后会开始订阅。";
      return;
    }
    void reconnectNavDelayPanel();
  }
  function addTopicToDelayWindow(topic: NavTopicOption) {
    if (hasDelayTopic(topic.key)) {
      return;
    }
    const nextTopics = [
      ...normalizeNavDelayTopicsInput(navDelayTopicsInput.value),
      topic.key,
    ];
    setNavDelayTopics(nextTopics);
  }
  function addSelectedTopicsToDelayWindow() {
    if (selectedNavTopicOptions.value.length === 0) {
      return;
    }
    const nextTopics = [
      ...normalizeNavDelayTopicsInput(navDelayTopicsInput.value),
      ...selectedNavTopicOptions.value.map((topic) => topic.key),
    ];
    setNavDelayTopics(nextTopics);
    selectedNavTopics.value = [];
  }
  function addTopicToMainView(topic: NavTopicOption) {
    if (hasMainDisplay(topic.key)) {
      return;
    }
    navMainDisplays.value = [
      ...navMainDisplays.value,
      topicOptionToDisplay(topic),
    ];
  }
  function createNavPanelFromTopic(
    topic: NavTopicOption,
    idPrefix: string,
  ): NavPanelItem {
    const isPointCloudTopic = isPointCloudMessageType(topic.type);
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
    navSidePanels.value = [
      ...navSidePanels.value,
      createNavPanelFromTopic(topic, "side-panel"),
    ];
  }
  function addTopicAsFullPanel(topic: NavTopicOption) {
    if (hasFullPanel(topic.key)) {
      return;
    }
    navFullPanels.value = [
      ...navFullPanels.value,
      createNavPanelFromTopic(topic, "full-panel"),
    ];
  }
  function removeMainDisplay(topic: string) {
    navMainDisplays.value = navMainDisplays.value.filter(
      (display) => display.topic !== topic,
    );
  }
  function updateMainDisplayConfig(
    topic: string,
    patch: Partial<NavViewerDisplay>,
  ) {
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
    const pointSize = Math.min(
      0.6,
      Math.max(0.01, Number(rawValue || "0.08") || 0.08),
    );
    updateMainDisplayConfig(topic, { pointSize });
  }
  function updateMainDisplayPointEmissiveIntensity(
    topic: string,
    rawValue: string,
  ) {
    const pointEmissiveIntensity = Math.min(
      3,
      Math.max(0, Number(rawValue || "0") || 0),
    );
    updateMainDisplayConfig(topic, { pointEmissiveIntensity });
  }
  function updateMainDisplayHzLimit(topic: string, rawValue: string) {
    const hzLimit = Math.max(0, Math.round(Number(rawValue || "0") || 0));
    updateMainDisplayConfig(topic, { hzLimit });
  }
  function updateMainDisplayPointColorMode(topic: string, rawValue: string) {
    updateMainDisplayConfig(topic, {
      pointColorMode: rawValue === "layered" ? "layered" : "solid",
    });
  }
  function updateMainDisplayColor(topic: string, rawValue: string) {
    const display = navMainDisplays.value.find((item) => item.topic === topic);
    const fallbackColor = defaultMainDisplayColor(
      topic,
      display?.kind || "unknown",
    );
    updateMainDisplayConfig(topic, { color: rawValue || fallbackColor });
  }
  function updateMainDisplayMapOpacity(topic: string, rawValue: string) {
    const mapOpacity = Math.min(
      1,
      Math.max(0.05, Number(rawValue || "0.94") || 0.94),
    );
    updateMainDisplayConfig(topic, { mapOpacity });
  }
  function updateMainDisplayTfLabelSize(topic: string, rawValue: string) {
    const tfLabelSize = Math.min(
      2,
      Math.max(0.2, Number(rawValue || "0.5") || 0.5),
    );
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
    navSidePanels.value = navSidePanels.value.filter(
      (panel) => panel.id !== panelId,
    );
  }
  function removeNavFullPanel(panelId: string) {
    navFullPanels.value = navFullPanels.value.filter(
      (panel) => panel.id !== panelId,
    );
  }
  function updatePanelListConfig(
    list: NavPanelItem[],
    panelId: string,
    patch: Partial<NavPanelItem>,
  ) {
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
  function updateNavSidePanelConfig(
    panelId: string,
    patch: Partial<NavPanelItem>,
  ) {
    navSidePanels.value = updatePanelListConfig(
      navSidePanels.value,
      panelId,
      patch,
    );
  }
  function updateNavFullPanelConfig(
    panelId: string,
    patch: Partial<NavPanelItem>,
  ) {
    navFullPanels.value = updatePanelListConfig(
      navFullPanels.value,
      panelId,
      patch,
    );
  }
  watch(
    () => initialPosePointCloudSize.value,
    () => {
      navViewerRef.value?.updateInitialPosePointCloudSize(
        normalizedInitialPosePointCloudSize(),
      );
    },
  );
  watch(
    () => [
      formValues.offline_map_point_size,
      formValues.offline_map_point_color,
      formValues.offline_map_voxel_color,
    ],
    () => updateOfflineMapVisualSettings(),
  );
  onMounted(() => {
    document.addEventListener("mousedown", handleDocumentMouseDown);
  });
  onBeforeUnmount(() => {
    document.removeEventListener("mousedown", handleDocumentMouseDown);
    if (props.tool.key === "ros_nav_test") {
      saveRosNavConfigOnExit();
    }

    stopRosSharedStatsPolling();
    disconnectNavDelayPanel();
    disconnectNavControlAdapter();
  });
  return {
    connectionEnabled,
    formValues,
    defaultMainDisplayColor,
    selectedNavTopics,
    navSidePanels,
    navFullPanels,
    navMainDisplays,
    rosRuntimeParamsLoading,
    rosTopicQuery,
    rosTopicOptions,
    rosInspectResult,
    rosTopicsMessage,
    rosReconnectToken,
    rosDataSourceConfigLoaded,
    rosRuntimeParams,
    rosRuntimeParamsMessage,
    rosSharedSessionStats,
    navDelayPanelCollapsed,
    navViewerRef,
    navDelayTopicsInput,
    navDelayAggregateLines,
    navDelayOverviewRecording,
    navDelayMessage,
    navRuntimeParamsPanelCollapsed,
    navDisplayManagerCollapsed,
    navRecordingFiles,
    navRecordingFilesDirectory,
    navRecordingFilesLoading,
    navRecordingFilesMessage,
    navRecordingPreviewPath,
    navRecordingPreviewText,
    navRecordingPreviewKind,
    navRecordingParsedPayload,
    navRecordingChartMetricLabel,
    navRecordingChartRangeStart,
    navRecordingChartRangeEnd,
    navRecordingChartHover,
    navInteractionMode,
    navControlLoading,
    navControlMessage,
    manualInitialPoseX,
    manualInitialPoseY,
    manualInitialPoseZ,
    manualInitialPoseYaw,
    initialPosePointCloudTopic,
    initialPosePointCloudLoading,
    initialPosePointCloudSize,
    initialPoseTopicDropdownOpen,
    offlineMapLoading,
    offlineMapMessage,
    offlineMapPreview,
    offlineMapDisplayMode,
    selectedNavTopicOptions,
    filteredInitialPosePointCloudTopicOptions,
    mergedToolLogs,
    navDisplayManagerLabel,
    initialPoseModeButtonLabel,
    filteredRosTopicOptions,
    navDelayTopicDefinitions,
    navDelayOverviewAxisInfo,
    normalizeRosBridgeTimeoutMs,
    clearToolLogs,
    handleRosRuntimeLog,
    triggerRosReconnect,
    disconnectNavControlAdapter,
    navDelayRecordingDurationText,
    toggleNavDelayOverviewRecording,
    disconnectNavDelayPanel,
    applyNavDelayTopics,
    reconnectNavDelayPanel,
    toggleNavDelayPanel,
    isNavDelayOverviewTopicSelected,
    toggleNavDelayOverviewTopic,
    browseField,
    saveRosNavConfig,
    inspectRosNavSource,
    refreshRosTopics,
    loadRosRuntimeParamsPanel,
    formatRuntimeParamValue,
    toggleNavRuntimeParamsPanel,
    toggleNavRuntimeGroup,
    isNavRuntimeGroupCollapsed,
    toggleNavRuntimeNode,
    isNavRuntimeNodeCollapsed,
    enterInitialPoseMode,
    enterNavGoalMode,
    submitManualInitialPose,
    offlineMapDisplayedVoxelCount,
    offlineMapTotalVoxelCount,
    normalizedOfflineMapPointSize,
    normalizedInitialPoseBaseHeightOffset,
    normalizedInitialPoseGroundNormalRadius,
    normalizedInitialPoseGroundMaxSlope,
    openInitialPoseTopicDropdown,
    selectInitialPosePointCloudTopic,
    handleInitialPoseTopicInputKeydown,
    captureInitialPosePointCloudFrame,
    loadOfflineMapPointCloud,
    clearOfflineMapPointCloud,
    setOfflineMapDisplayMode,
    updateOfflineMapVisualSettings,
    cancelInitialPoseCandidate,
    confirmInitialPoseCandidate,
    handleNavViewerInteraction,
    sendNavControlCommand,
    triggerAutoLocalization,
    loadNavRecordingFiles,
    resetNavRecordingChartState,
    activeNavRecordingMetric,
    activeNavRecordingMetricSamples,
    navRecordingChartTimeText,
    navRecordingChartPolylinePoints,
    setNavRecordingMetric,
    zoomNavRecordingChart,
    handleNavRecordingChartWheel,
    handleNavRecordingChartPointerDown,
    handleNavRecordingChartPointerMove,
    stopNavRecordingChartDrag,
    previewNavRecordingFile,
    removeNavRecordingFile,
    addSelectedTopicsAsSidePanels,
    addSelectedTopicsToMainView,
    addTopicToDelayWindow,
    addTopicToMainView,
    addTopicAsSidePanel,
    addTopicAsFullPanel,
    removeMainDisplay,
    updateMainDisplayPointSize,
    updateMainDisplayPointEmissiveIntensity,
    updateMainDisplayHzLimit,
    updateMainDisplayPointColorMode,
    updateMainDisplayColor,
    updateMainDisplayMapOpacity,
    updateMainDisplayTfLabelSize,
    updateMainDisplayTfShowNames,
    tfFramesForDisplay,
    isTfFrameSelected,
    showAllMainDisplayTfFrames,
    toggleMainDisplayTfFrame,
    handleTfFramesChange,
    toggleNavDisplayManager,
    toggleNavSidePanel,
    toggleNavFullPanel,
    removeNavSidePanel,
    removeNavFullPanel,
    updateNavSidePanelConfig,
    updateNavFullPanelConfig,
  };
}
