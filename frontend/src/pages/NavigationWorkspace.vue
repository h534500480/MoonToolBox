<!-- 功能说明：platform 全屏工作台；业务操作保留旧控制器语义并分组放入玻璃面板。 -->
<script setup lang="ts">
import { ref, computed, watch } from "vue";
import { useTaskNavigation } from "../composables/useTaskNavigation";
import { usePlatformTelemetry } from "../composables/usePlatformTelemetry";
import {
  isDetailsOpen,
  onDetailsToggle,
} from "../composables/usePersistentDetails";
import { openLocalPath, buildBackendImageUrl } from "../api/client";
import {
  Settings,
  RotateCcw,
  Battery,
  LocateFixed,
  Radar,
  Gauge,
  Radio,
  SlidersHorizontal,
  Activity,
  FolderOpen,
  Navigation,
  X,
} from "@lucide/vue";
import PlatformLauncher from "../components/PlatformLauncher.vue";
import GlassDrawer from "../components/GlassDrawer.vue";
import Nav3DViewer from "../components/Nav3DViewer.vue";
import NavTopicPanelList from "../components/NavTopicPanelList.vue";
import NavigationTasks from "../components/NavigationTasks.vue";
import MappingWorkspace from "../components/MappingWorkspace.vue";
import type { TaskPoint } from "../lib/navigationTasks";
import DemoDock from "../components/DemoDock.vue";
import { demoData, demoTopics } from "../platform/demo";
import { visual, platformState } from "../platform/ui";
import { useNavigationController } from "../composables/useNavigationController";
import type { ToolDefinition } from "../types";
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
const {
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
} = useNavigationController(props, emit);
const { batteryText, speedText } = usePlatformTelemetry(
  connectionEnabled,
  formValues,
);
const { transport: taskTransport, status: taskNavigationStatus } =
  useTaskNavigation(connectionEnabled, formValues);
const activeDrawer = ref("");
const poseHelperHint =
  "直接拖动箭头或平面移动，拖动外侧圆环旋转，无需切换模式。";
const workspaceMode = ref<"localization" | "navigation" | "mapping">("localization");
const taskPanel = ref<InstanceType<typeof NavigationTasks>>();
const taskPicking = ref(false);
const taskPoints = ref<TaskPoint[]>([]);
/** 顶部只切换工具面板，共用同一个 Viewer 和 ROS 会话。 */
function switchWorkspace(mode: "localization" | "navigation" | "mapping") {
  if (mode === workspaceMode.value) return;
  navInteractionMode.value = "none";
  navViewerRef.value?.clearInitialPoseCandidate();
  activeDrawer.value = "";
  taskPicking.value = false;
  workspaceMode.value = mode;
}
/** 工具带抽屉按钮：点击已打开的抽屉时收起，便于配合场景反复操作。 */
function toggleDrawer(id: string) {
  activeDrawer.value = activeDrawer.value === id ? "" : id;
}
// 右侧工具面板：单值互斥展开，null 表示全部收起
type SideToolId = "topics" | "offlineClip";
const activeSideTool = ref<SideToolId | null>("topics");
/** 右侧工具栏注册表：新增工具面板时在此追加定义即可接入互斥展开。 */
const sideTools = computed<
  { id: SideToolId; label: string; icon: typeof Radio; enabled: boolean }[]
>(() => [
  { id: "topics", label: "话题列表", icon: Radio, enabled: true },
  {
    id: "offlineClip",
    label: "地图裁剪",
    icon: SlidersHorizontal,
    enabled: Boolean(offlineMapPreview.value),
  },
]);
function toggleSideTool(id: SideToolId) {
  activeSideTool.value = activeSideTool.value === id ? null : id;
}
// 离线地图加载成功后自动展开裁剪面板，清除后回落到话题列表
watch(offlineMapPreview, (preview) => {
  if (preview && activeSideTool.value !== "offlineClip") {
    activeSideTool.value = "offlineClip";
  } else if (!preview && activeSideTool.value === "offlineClip") {
    activeSideTool.value = "topics";
  }
});
const demoDock = ref<InstanceType<typeof DemoDock>>();
const selectedTopic = ref("/plan");
const displayedTopics = computed(() =>
  platformState.demo
    ? demoTopics.filter((t) =>
        t.key.toLowerCase().includes(rosTopicQuery.value.toLowerCase()),
      )
    : filteredRosTopicOptions.value,
);
function addMonitor(topic: {
  key: string;
  type: string;
  label: string;
  note: string;
}) {
  if (platformState.demo) demoDock.value?.add(topic.key);
  else addTopicAsSidePanel(topic);
}
const customName = ref(""),
  customType = ref("std_msgs/msg/Float64"),
  customError = ref("");
function addCustom() {
  customError.value = "";
  activeDrawer.value = "custom";
}
/** 自定义话题使用同一监控入口，演示模式不编造未知类型的数据。 */
function confirmCustom() {
  const name = customName.value.trim(),
    type = customType.value.trim();
  if (!/^\/[A-Za-z0-9_/]+$/.test(name) || !type.includes("/")) {
    customError.value = "请输入以 / 开头的话题名及完整消息类型。";
    return;
  }
  const topic = { key: name, label: name, type, note: "" };
  if (!rosTopicOptions.value.some((t) => t.key === name))
    rosTopicOptions.value.push(topic);
  if (platformState.demo && !demoTopics.some((t) => t.key === name))
    demoTopics.push(topic);
  addMonitor(topic);
  activeDrawer.value = "";
}
const drawerTitles: Record<string, string> = {
  settings: "平台设置",
  control: "定位控制",
  displays: "主视图显示项",
  diagnostics: "诊断与录制",
  custom: "添加话题",
};
const mainDisplayKindLabels: Record<string, string> = {
  map: "地图",
  pointcloud: "点云",
  path: "路径",
  bspline: "轨迹",
  pose: "定位",
  pose_array: "位姿",
  tf: "TF",
  marker: "标记",
  twist: "速度",
  obstacle_zone: "风险区",
};
function mainDisplayKindLabel(kind: string) {
  return mainDisplayKindLabels[kind] || kind;
}
function compactMessageType(type: string) {
  return type.split("/").slice(-1)[0] || type;
}
function connect() {
  connectionEnabled.value = true;
  triggerRosReconnect();
  void refreshRosTopics();
}
function returnDemo() {
  connectionEnabled.value = false;
  disconnectNavControlAdapter();
  disconnectNavDelayPanel();
  clearOfflineMapPointCloud();
  platformState.demo = true;
  platformState.connected = false;
}
/** 卡片顺序保存在原有工作台配置中。 */
function movePanel(list: typeof navSidePanels.value, from: string, to: string) {
  const a = list.findIndex((p) => p.id === from),
    b = list.findIndex((p) => p.id === to);
  if (a < 0 || b < 0 || a === b) return;
  list.splice(b, 0, list.splice(a, 1)[0]);
}
function dragTopic(event: DragEvent, topic: string) {
  event.dataTransfer?.setData("text/ros-topic", topic);
  event.dataTransfer?.setData("text/plain", topic);
  if (event.dataTransfer) {
    event.dataTransfer.effectAllowed = "copy";
  }
}
function findDraggedTopic(event: DragEvent) {
  const topicKey =
    event.dataTransfer?.getData("text/ros-topic") ||
    event.dataTransfer?.getData("text/plain") ||
    "";
  return displayedTopics.value.find((t) => t.key === topicKey);
}
function dropTopic(event: DragEvent) {
  const topic = findDraggedTopic(event);
  if (topic) addMonitor(topic);
}
function dropTopicFromPanel(topicKey: string) {
  const topic = displayedTopics.value.find((t) => t.key === topicKey);
  if (topic) addMonitor(topic);
}
</script>
<template>
  <main
    class="navigation-workspace"
    :style="{ '--glass-alpha': visual.hudOpacity }"
  >
    <div class="scene-fill">
      <Nav3DViewer
        ref="navViewerRef"
        :provider="formValues.ros_provider || 'rosbridge'"
        :url="
          connectionEnabled && rosDataSourceConfigLoaded
            ? formValues.ros_bridge_url || ''
            : ''
        "
        :timeout-ms="Number(normalizeRosBridgeTimeoutMs(formValues.timeout_ms))"
        :fixed-frame="formValues.fixed_frame || 'map'"
        :robot-pose-frame="formValues.robot_tf_frame || 'body'"
        :displays="navMainDisplays"
        :interaction-mode="
          workspaceMode === 'navigation'
            ? taskPicking
              ? 'waypoint'
              : 'none'
            : navInteractionMode
        "
        :task-points="taskPoints"
        :task-editing="workspaceMode === 'navigation'"
        @task-pose-change="taskPanel?.receivePose($event)"
        @task-pose-placed="taskPanel?.placeMapPoint($event)"
        @task-point-select="taskPanel?.editPoint($event)"
        @task-route-insert="taskPanel?.insertRoutePoint($event)"
        :reconnect-token="rosReconnectToken"
        :initial-pose-base-height-offset-m="
          normalizedInitialPoseBaseHeightOffset()
        "
        :initial-pose-ground-normal-radius-m="
          normalizedInitialPoseGroundNormalRadius()
        "
        :initial-pose-ground-max-slope-deg="
          normalizedInitialPoseGroundMaxSlope()
        "
        :offline-clip-panel-open="
          workspaceMode === 'localization' && activeSideTool === 'offlineClip'
        "
        @interaction-complete="handleNavViewerInteraction"
        @tf-frames-change="handleTfFramesChange"
        @ros-log="handleRosRuntimeLog"
      />
    </div>
    <div class="workspace-mode-switch glass" role="group" aria-label="工作模式">
      <button
        :class="{ active: workspaceMode === 'localization' }"
        :aria-pressed="workspaceMode === 'localization'"
        @click="switchWorkspace('localization')"
      >
        定位
      </button>
      <button
        :class="{ active: workspaceMode === 'navigation' }"
        :aria-pressed="workspaceMode === 'navigation'"
        @click="switchWorkspace('navigation')"
      >
        导航
      </button>
      <button
        :class="{ active: workspaceMode === 'mapping' }"
        :aria-pressed="workspaceMode === 'mapping'"
        @click="switchWorkspace('mapping')"
      >
        建图
      </button>
    </div>
    <NavigationTasks
      ref="taskPanel"
      :active="workspaceMode === 'navigation'"
      :frame="formValues.fixed_frame || 'map'"
      :viewer="navViewerRef"
      :transport="taskTransport"
      :navigation-status="taskNavigationStatus"
      @picking="taskPicking = $event"
      @points="taskPoints = $event"
    />
    <MappingWorkspace :active="workspaceMode === 'mapping'" />
    <div class="platform-top-left">
      <PlatformLauncher />
      <div class="glass status-hud">
        <div
          v-for="item in [
            {
              icon: Battery,
              label: '电量',
              value: platformState.demo
                ? Math.round(demoData.battery) + '%'
                : platformState.connected
                  ? batteryText
                  : '—',
            },
            {
              icon: LocateFixed,
              label: '定位',
              value: platformState.demo
                ? '演示'
                : platformState.connected
                  ? '已连接'
                  : '未连接',
            },
            {
              icon: Radar,
              label: 'LiDAR',
              value: platformState.demo
                ? '演示'
                : platformState.lidarActive
                  ? '接收中'
                  : '待话题',
            },
            {
              icon: Gauge,
              label: '速度',
              value: platformState.demo
                ? demoData.speed.toFixed(2) + ' m/s'
                : platformState.connected
                  ? speedText
                  : '—',
            },
          ]"
          :key="item.label"
        >
          <span class="hud-icon"><component :is="item.icon" :size="14" /></span
          ><span
            ><strong
              >{{ item.value }}
              <i
                class="dot"
                :class="{
                  'dot-ok': platformState.demo || platformState.connected,
                }" /></strong
            ><small>{{ item.label }}</small></span
          >
        </div>
      </div>
    </div>
    <button
      class="glass settings-button icon-button"
      aria-label="平台设置"
      @click="activeDrawer = 'settings'"
    >
      <Settings :size="19" />
    </button>
    <Transition name="workspace-fade"
      ><div
        v-show="workspaceMode === 'localization'"
        class="monitor-dock"
        @dragover.prevent
        @drop.prevent="dropTopic"
      >
        <DemoDock v-if="platformState.demo" ref="demoDock" /><NavTopicPanelList
          v-if="!platformState.demo"
          :provider="formValues.ros_provider || 'rosbridge'"
          :url="
            connectionEnabled && rosDataSourceConfigLoaded
              ? formValues.ros_bridge_url || ''
              : ''
          "
          :timeout-ms="
            Number(normalizeRosBridgeTimeoutMs(formValues.timeout_ms))
          "
          :panels="navSidePanels"
          :compact="true"
          :reconnect-token="rosReconnectToken"
          @reorder="(from, to) => movePanel(navSidePanels, from, to)"
          @toggle="toggleNavSidePanel"
          @remove="removeNavSidePanel"
          @update-config="updateNavSidePanelConfig"
          @add-topic="dropTopicFromPanel"
          @recording-saved="loadNavRecordingFiles"
          @ros-log="handleRosRuntimeLog"
        /></div
    ></Transition>
    <Transition name="workspace-fade"
      ><div
        v-show="workspaceMode === 'localization'"
        class="nav-side-tools glass"
      >
        <button
          v-for="tool in sideTools"
          :key="tool.id"
          type="button"
          class="nav-side-tool-btn"
          :class="{ active: activeSideTool === tool.id }"
          :disabled="!tool.enabled"
          :title="tool.label"
          :aria-label="tool.label"
          :aria-pressed="activeSideTool === tool.id"
          @click="toggleSideTool(tool.id)"
        >
          <component :is="tool.icon" :size="15" />
        </button></div
    ></Transition>
    <Transition name="popover"
      ><aside
        v-if="workspaceMode === 'localization' && activeSideTool === 'topics'"
        class="glass-panel topics-drawer"
      >
        <header>
          <Radio :size="14" /><strong>ROS 话题</strong
          ><span class="glass-chip">{{ displayedTopics.length }}</span>
        </header>
        <input
          v-model="rosTopicQuery"
          class="text-field topic-search"
          placeholder="搜索话题…"
        />
        <div class="topic-list">
          <article
            v-for="topic in displayedTopics"
            :key="topic.key"
            :class="{ selected: selectedTopic === topic.key }"
            @click="selectedTopic = topic.key"
            @dblclick="addMonitor(topic)"
            draggable="true"
            @dragstart="dragTopic($event, topic.key)"
          >
            <label
              ><input
                v-if="!platformState.demo"
                v-model="selectedNavTopics"
                @click.stop
                type="checkbox"
                :value="topic.key"
              /><strong :title="topic.key">{{ topic.key }}</strong></label
            ><small>{{ topic.type }}</small>
            <div
              class="topic-actions"
              v-if="!platformState.demo && selectedTopic === topic.key"
            >
              <button @click.stop="addMonitor(topic)">+ 监控</button
              ><button
                @click="
                  addTopicAsFullPanel(topic);
                  activeDrawer = 'diagnostics';
                "
              >
                详情</button
              ><button @click="addTopicToMainView(topic)">3D</button
              ><button @click="addTopicToDelayWindow(topic)">延迟</button>
            </div>
          </article>
        </div>
        <footer>
          <button v-if="platformState.demo" @click="addCustom">
            ＋ 添加话题</button
          ><button v-else @click="refreshRosTopics">刷新</button
          ><button
            v-if="!platformState.demo"
            :disabled="!selectedNavTopics.length"
            @click="addSelectedTopicsAsSidePanels"
          >
            批量监控</button
          ><button
            v-if="!platformState.demo"
            :disabled="!selectedNavTopics.length"
            @click="addSelectedTopicsToMainView"
          >
            批量 3D
          </button>
        </footer>
        <small>{{
          platformState.demo ? "拖拽话题到左侧监控区" : rosTopicsMessage
        }}</small>
      </aside>
    </Transition>
    <div v-show="workspaceMode !== 'mapping'" class="platform-bottom-left">
      <button class="glass pill-button" @click="platformState.cameraReset++">
        <RotateCcw :size="13" />重置视角</button
      ><span>探索 · 测试 · 构建 · 面向真实世界的机器人</span>
    </div>
    <Transition name="workspace-fade"
      ><div
        v-show="workspaceMode === 'localization'"
        class="platform-toolbelt glass"
      >
        <button title="定位控制" @click="toggleDrawer('control')">
          <Navigation :size="16" />定位控制</button
        ><button title="主视图显示项" @click="toggleDrawer('displays')">
          <SlidersHorizontal :size="16" />显示项</button
        ><button title="诊断与录制" @click="toggleDrawer('diagnostics')">
          <Activity :size="16" />诊断
        </button>
      </div></Transition
    >
    <div class="glass pose-widget">
      <header>
        <strong>机器人位置信息</strong
        ><span class="glass-chip">{{ formValues.fixed_frame || "map" }}</span
        ><small>pose</small>
      </header>
      <div v-if="platformState.demo" class="pose-values">
        <span v-for="axis in ['x', 'y', 'z', 'yaw'] as const" :key="axis"
          ><small>{{ axis }}</small
          ><b
            >{{ demoData.pose[axis].toFixed(3) }}
            {{ axis === "yaw" ? "rad" : "m" }}</b
          ></span
        >
      </div>
      <pre v-else>{{ platformState.pose }}</pre>
    </div>
    <GlassDrawer
      :open="!!activeDrawer"
      :title="drawerTitles[activeDrawer] || ''"
      :wide="activeDrawer === 'diagnostics'"
      :persistent="activeDrawer === 'control'"
      @close="activeDrawer = ''"
    >
      <template v-if="activeDrawer === 'custom'"
        ><form @submit.prevent="confirmCustom">
          <label class="field"
            >话题名称<input
              v-model="customName"
              class="text-field"
              placeholder="/my_topic"
              required /></label
          ><label class="field"
            >消息类型<input
              v-model="customType"
              class="text-field"
              placeholder="std_msgs/msg/Float64"
              required
          /></label>
          <p class="feedback" role="alert">{{ customError }}</p>
          <button class="primary-btn" type="submit">添加到监控</button>
        </form></template
      ><template v-if="activeDrawer === 'settings'"
        ><details
          :open="isDetailsOpen('settings-ros', true)"
          @toggle="onDetailsToggle('settings-ros', $event)"
        >
          <summary>ROS 接入</summary>
          <label class="field"
            >rosbridge 地址<input
              v-model="formValues.ros_bridge_url"
              class="text-field"
              placeholder="ws://192.168.1.100:9090"
          /></label>
          <label class="field"
            >机器人 TF 坐标系<input
              v-model="formValues.robot_tf_frame"
              class="text-field"
              placeholder="body"
          /></label>
          <div class="button-row">
            <button class="primary-btn" @click="connect">
              {{ platformState.connected ? "重新连接" : "连接 ROS" }}</button
            ><button @click="inspectRosNavSource">检测接入</button
            ><button @click="saveRosNavConfig()">保存配置</button
            ><button @click="returnDemo">返回演示</button>
          </div>
          <p class="feedback">{{ rosSharedSessionStats.message }}</p>
          <label
            v-for="field in tool.fields.filter(
              (f) =>
                !f.key.startsWith('offline_map') &&
                f.key !== 'ros_bridge_url' &&
                f.key !== 'robot_tf_frame',
            )"
            :key="field.key"
            class="field"
            ><span>{{ field.label }}</span
            ><input v-model="formValues[field.key]" class="text-field"
          /></label>
        </details>
        <details
          :open="isDetailsOpen('settings-offline-map', false)"
          @toggle="onDetailsToggle('settings-offline-map', $event)"
        >
          <summary>离线地图</summary>
          <div class="nav-control-card nav-offline-map-card">
            <div class="nav-control-card-head">
              <div class="result-title">离线地图点云</div>
              <div class="section-subtitle">
                PCD 会按体素强度下采样后加载，map.yaml/PGM
                用于显示地图坐标范围。
              </div>
            </div>
            <div class="offline-map-group-label">
              <span class="kv-key">文件来源</span>
            </div>
            <div class="offline-map-file-grid">
              <label class="nav-display-config-item">
                <span class="kv-key">离线地图 PCD</span>
                <div class="field-row">
                  <input
                    v-model="formValues.offline_map_pcd"
                    class="field-input"
                    placeholder="G:/path/map.pcd"
                  />
                  <button
                    class="field-browse-btn"
                    type="button"
                    title="选择 PCD 文件"
                    @click="browseField('offline_map_pcd', '离线地图 PCD')"
                  >
                    选择
                  </button>
                </div>
              </label>
              <label class="nav-display-config-item">
                <span class="kv-key">map.yaml</span>
                <div class="field-row">
                  <input
                    v-model="formValues.offline_map_yaml"
                    class="field-input"
                    placeholder="G:/path/map.yaml"
                  />
                  <button
                    class="field-browse-btn"
                    type="button"
                    title="选择 map.yaml 文件"
                    @click="browseField('offline_map_yaml', 'map.yaml')"
                  >
                    选择
                  </button>
                </div>
              </label>
              <label class="nav-display-config-item">
                <span class="kv-key">map.pgm</span>
                <div class="field-row">
                  <input
                    v-model="formValues.offline_map_pgm"
                    class="field-input"
                    placeholder="不填则使用 map.yaml 的 image"
                  />
                  <button
                    class="field-browse-btn"
                    type="button"
                    title="选择 map.pgm 文件"
                    @click="browseField('offline_map_pgm', 'map.pgm')"
                  >
                    选择
                  </button>
                </div>
              </label>
            </div>
            <div class="offline-map-group-label">
              <span class="kv-key">采样与占据参数</span>
            </div>
            <div class="offline-map-param-grid">
              <label class="nav-display-config-item">
                <span class="kv-key">下采样 m</span>
                <input
                  v-model="formValues.offline_map_voxel_leaf_m"
                  class="field-input"
                  type="number"
                  min="0.01"
                  max="5"
                  step="0.01"
                />
              </label>
              <label class="nav-display-config-item">
                <span class="kv-key">占据 voxel m</span>
                <input
                  v-model="formValues.offline_map_occupancy_voxel_m"
                  class="field-input"
                  type="number"
                  min="0.05"
                  max="2"
                  step="0.01"
                />
              </label>
              <label class="nav-display-config-item">
                <span class="kv-key">最大点数</span>
                <input
                  v-model="formValues.offline_map_max_points"
                  class="field-input"
                  type="number"
                  min="1000"
                  max="300000"
                  step="1000"
                />
              </label>
              <label class="nav-display-config-item">
                <span class="kv-key">最大 voxel</span>
                <input
                  v-model="formValues.offline_map_max_voxels"
                  class="field-input"
                  type="number"
                  min="1000"
                  max="200000"
                  step="1000"
                />
              </label>
            </div>
            <div class="offline-map-group-label">
              <span class="kv-key">显示外观（加载后可即时调整）</span>
            </div>
            <div class="offline-map-param-grid">
              <label class="nav-display-config-item">
                <span class="kv-key">显示方式</span>
                <select
                  v-model="formValues.offline_map_display_mode"
                  class="field-input"
                  :disabled="offlineMapLoading"
                  @change="setOfflineMapDisplayMode(formValues.offline_map_display_mode === 'pointcloud' || formValues.offline_map_display_mode === 'render' ? formValues.offline_map_display_mode : 'voxel')"
                >
                  <option value="voxel">占据网格</option>
                  <option value="pointcloud">点云</option>
                  <option value="render">占据网格渲染</option>
                </select>
              </label>
              <label class="nav-display-config-item">
                <span class="kv-key">点云大小 m</span>
                <input
                  v-model="formValues.offline_map_point_size"
                  class="field-input"
                  type="number"
                  min="0.005"
                  max="1"
                  step="0.005"
                />
              </label>
              <label class="nav-display-config-item">
                <span class="kv-key">点云颜色</span>
                <input
                  v-model="formValues.offline_map_point_color"
                  class="field-input color-input"
                  type="color"
                />
              </label>
              <label class="nav-display-config-item">
                <span class="kv-key">占据网格颜色</span>
                <input
                  v-model="formValues.offline_map_voxel_color"
                  class="field-input color-input"
                  type="color"
                />
              </label>
            </div>
            <div class="offline-map-param-grid">
              <label class="nav-display-config-item">
                <span class="kv-key">base 高度偏移 m</span>
                <input
                  v-model="formValues.initial_pose_base_height_offset_m"
                  class="field-input"
                  type="number"
                  min="-1"
                  max="3"
                  step="0.01"
                />
              </label>
              <label class="nav-display-config-item">
                <span class="kv-key">法线半径 m</span>
                <input
                  v-model="formValues.initial_pose_ground_normal_radius_m"
                  class="field-input"
                  type="number"
                  min="0.15"
                  max="3"
                  step="0.05"
                />
              </label>
              <label class="nav-display-config-item">
                <span class="kv-key">最大坡度 °</span>
                <input
                  v-model="formValues.initial_pose_ground_max_slope_deg"
                  class="field-input"
                  type="number"
                  min="1"
                  max="75"
                  step="1"
                />
              </label>
            </div>
            <div class="offline-map-actions">
              <div class="offline-map-action-buttons">
                <button
                  class="primary-btn"
                  type="button"
                  :disabled="offlineMapLoading"
                  @click="loadOfflineMapPointCloud"
                >
                  {{ offlineMapLoading ? "加载中..." : "加载离线点云" }}
                </button>
                <button
                  class="secondary-btn"
                  type="button"
                  :disabled="offlineMapLoading || !offlineMapPreview"
                  @click="clearOfflineMapPointCloud"
                >
                  清除离线点云
                </button>
              </div>
              <div
                class="segmented-control offline-map-display-mode"
                role="group"
                aria-label="离线地图显示模式"
              >
                <button
                  type="button"
                  :class="{ active: offlineMapDisplayMode === 'voxel' }"
                  :disabled="offlineMapLoading || !offlineMapPreview"
                  title="显示占据 voxel 方块"
                  @click="setOfflineMapDisplayMode('voxel')"
                >
                  占据网格
                </button>
                <button
                  type="button"
                  :class="{ active: offlineMapDisplayMode === 'pointcloud' }"
                  :disabled="offlineMapLoading || !offlineMapPreview"
                  title="显示下采样点云"
                  @click="setOfflineMapDisplayMode('pointcloud')"
                >
                  点云
                </button>
                <button
                  type="button"
                  :class="{ active: offlineMapDisplayMode === 'render' }"
                  :disabled="offlineMapLoading || !offlineMapPreview"
                  title="使用暮光材质和阴影渲染占据 voxel"
                  @click="setOfflineMapDisplayMode('render')"
                >
                  渲染
                </button>
              </div>
              <span class="nav-viewer-status offline-map-status">
                {{ offlineMapMessage || "未加载离线地图点云" }}
              </span>
            </div>
            <div v-if="offlineMapPreview" class="stat-strip offline-map-stats">
              <div>
                <span>输入点数</span>
                <strong>{{ offlineMapPreview.pcd.input_points }}</strong>
              </div>
              <div>
                <span>显示点数</span>
                <strong>{{ offlineMapPreview.pcd.sampled_count }}</strong>
              </div>
              <div>
                <span>占据 voxel</span>
                <strong
                  >{{ offlineMapDisplayedVoxelCount() }} /
                  {{ offlineMapTotalVoxelCount() }}</strong
                >
              </div>
              <div>
                <span>体素强度</span>
                <strong
                  >{{
                    (
                      offlineMapPreview.occupancy?.voxel_m ||
                      offlineMapPreview.pcd.voxel_leaf_m
                    ).toFixed(2)
                  }}m</strong
                >
              </div>
              <div>
                <span>PGM 地图</span>
                <strong>{{
                  offlineMapPreview.map
                    ? `${offlineMapPreview.map.width}x${offlineMapPreview.map.height}`
                    : "未绑定"
                }}</strong>
              </div>
            </div>
          </div>
        </details>
        <details
          :open="isDetailsOpen('settings-appearance', true)"
          @toggle="onDetailsToggle('settings-appearance', $event)"
        >
          <summary>外观与场景</summary>
          <label class="field"
            >HUD 透明度<input
              v-model.number="visual.hudOpacity"
              type="range"
              min="0.12"
              max="0.65"
              step="0.01" /></label
          ><label
            v-for="option in [
              { key: 'showGrid', label: '地面网格' },
              { key: 'showTrail', label: '运动轨迹' },
              { key: 'showCone', label: '传感器视野' },
              { key: 'showShadows', label: '柔和阴影' },
            ]"
            :key="option.key"
            class="toggle-row"
            >{{ option.label
            }}<input
              v-model="visual[option.key as keyof typeof visual]"
              type="checkbox"
          /></label>
          <div class="segmented">
            <button
              v-for="mode in ['idle', 'walk', 'run'] as const"
              :key="mode"
              :class="{ active: visual.robotAnim === mode }"
              @click="visual.robotAnim = mode"
            >
              {{ { idle: "待机", walk: "行走", run: "奔跑" }[mode] }}
            </button>
          </div>
        </details></template
      >
      <template v-if="activeDrawer === 'control'"
        ><div class="nav-control-card">
          <div class="nav-control-card-head">
            <div class="result-title">定位控制</div>
            <div class="section-subtitle">
              初始化定位会先生成三维候选位姿，可绑定一帧点云微调后再确认下发。
            </div>
          </div>

          <div class="nav-tool-group">
            <div class="nav-tool-group-title">任务控制</div>
            <div class="nav-control-grid">
              <button
                class="primary-btn"
                type="button"
                :disabled="navControlLoading"
                @click="enterInitialPoseMode"
              >
                {{ initialPoseModeButtonLabel }}
              </button>
              <button
                class="primary-btn"
                type="button"
                :disabled="navControlLoading"
                @click="triggerAutoLocalization"
              >
                自动定位
              </button>
            </div>
          </div>
          <div class="nav-tool-group">
            <div class="nav-tool-group-title">初始位姿候选</div>
            <div class="initial-pose-3d-row">
              <label class="nav-display-config-item initial-pose-topic-field">
                <span class="kv-key">点云 Topic</span>
                <div class="initial-pose-topic-combobox">
                  <input
                    v-model="initialPosePointCloudTopic"
                    class="field-input"
                    placeholder="/cloud_registered_bl"
                    autocomplete="off"
                    @focus="openInitialPoseTopicDropdown"
                    @input="openInitialPoseTopicDropdown"
                    @keydown="handleInitialPoseTopicInputKeydown"
                  />
                  <button
                    class="initial-pose-topic-toggle"
                    type="button"
                    aria-label="展开点云 Topic"
                    @mousedown.prevent
                    @click="
                      initialPoseTopicDropdownOpen =
                        !initialPoseTopicDropdownOpen
                    "
                  ></button>
                  <div
                    v-if="initialPoseTopicDropdownOpen"
                    class="initial-pose-topic-menu"
                  >
                    <button
                      v-for="topic in filteredInitialPosePointCloudTopicOptions"
                      :key="topic.key"
                      class="initial-pose-topic-option"
                      type="button"
                      @mousedown.prevent="
                        selectInitialPosePointCloudTopic(topic)
                      "
                    >
                      <strong>{{ topic.key }}</strong>
                      <span>{{ topic.label }}</span>
                    </button>
                    <div
                      v-if="
                        filteredInitialPosePointCloudTopicOptions.length === 0
                      "
                      class="initial-pose-topic-empty"
                    >
                      没有匹配的点云 topic
                    </div>
                  </div>
                </div>
              </label>
              <label class="nav-display-config-item initial-pose-size-field">
                <span class="kv-key">点大小</span>
                <input
                  v-model="initialPosePointCloudSize"
                  class="field-input"
                  type="number"
                  min="0.005"
                  max="0.8"
                  step="0.005"
                />
              </label>
              <button
                class="secondary-btn"
                type="button"
                :disabled="navControlLoading || initialPosePointCloudLoading"
                @click="captureInitialPosePointCloudFrame"
              >
                {{ initialPosePointCloudLoading ? "抓取中..." : "刷新点云帧" }}
              </button>
              <p class="section-subtitle">{{ poseHelperHint }}</p>
              <button
                class="primary-btn"
                type="button"
                :disabled="navControlLoading"
                @click="confirmInitialPoseCandidate"
              >
                确定初始化位姿
              </button>
              <button
                class="secondary-btn"
                type="button"
                :disabled="navControlLoading"
                @click="cancelInitialPoseCandidate"
              >
                取消预览
              </button>
            </div>
          </div>
          <div class="nav-tool-group">
            <div class="nav-tool-group-title">手动输入位姿</div>
            <div class="manual-initial-pose-row">
              <input
                v-model="manualInitialPoseX"
                class="field-input compact-input"
                type="number"
                step="0.001"
                placeholder="x"
              />
              <input
                v-model="manualInitialPoseY"
                class="field-input compact-input"
                type="number"
                step="0.001"
                placeholder="y"
              />
              <input
                v-model="manualInitialPoseZ"
                class="field-input compact-input"
                type="number"
                step="0.001"
                placeholder="z"
              />
              <input
                v-model="manualInitialPoseYaw"
                class="field-input compact-input"
                type="number"
                step="0.01"
                placeholder="yaw(rad)"
              />
              <button
                class="primary-btn"
                type="button"
                :disabled="navControlLoading"
                @click="submitManualInitialPose"
              >
                确认初始化
              </button>
            </div>
          </div>
        </div>
        <p class="feedback">{{ navControlMessage }}</p></template
      >
      <template v-if="activeDrawer === 'displays'"
        ><div class="section-head nav-display-section-head">
          <div>
            <div class="result-title">三维主视图</div>
            <div class="section-subtitle">
              当前支持 Map / TF / Path / Pose / ObstacleZone
              等常用显示项，交互方式按 RViz 的“添加显示项”思路组织。
            </div>
          </div>
          <button
            class="secondary-btn nav-display-manage-btn"
            type="button"
            @click="toggleNavDisplayManager"
          >
            {{ navDisplayManagerLabel }}
          </button>
        </div>
        <div class="nav-view-tags-row">
          <div class="nav-view-tags" aria-label="支持的显示项类型">
            <span class="nav-view-tag">地图</span>
            <span class="nav-view-tag">定位</span>
            <span class="nav-view-tag">路径</span>
            <span class="nav-view-tag">TF</span>
            <span class="nav-view-tag">风险区</span>
          </div>
          <div class="nav-display-count">
            当前显示
            <span class="glass-chip nav-display-count-chip">{{
              navMainDisplays.length
            }}</span>
            项
          </div>
        </div>
        <div v-if="!navDisplayManagerCollapsed" class="nav-display-strip">
          <div
            v-for="display in navMainDisplays"
            :key="display.topic"
            class="nav-display-chip"
          >
            <div class="nav-display-chip-head">
              <span class="nav-display-kind">{{
                mainDisplayKindLabel(display.kind)
              }}</span>
              <div class="nav-display-chip-main">
                <strong :title="display.topic">{{ display.label }}</strong>
                <span :title="display.messageType">{{
                  compactMessageType(display.messageType)
                }}</span>
              </div>
              <button
                class="nav-display-remove"
                type="button"
                title="移除显示项"
                @click="removeMainDisplay(display.topic)"
              >
                <X :size="13" />
              </button>
            </div>
            <div class="nav-display-detail">
              <span class="kv-key">话题</span>
              <span class="kv-value">{{ display.topic }}</span>
            </div>
            <div
              v-if="display.kind === 'pointcloud'"
              class="nav-display-config-row"
            >
              <label class="nav-display-config-item">
                <span class="kv-key">颜色</span>
                <input
                  class="nav-display-color-input"
                  type="color"
                  :value="display.color ?? '#ffffff'"
                  @input="
                    updateMainDisplayColor(
                      display.topic,
                      ($event.target as HTMLInputElement).value,
                    )
                  "
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
                  @input="
                    updateMainDisplayPointSize(
                      display.topic,
                      ($event.target as HTMLInputElement).value,
                    )
                  "
                />
              </label>
              <label class="nav-display-config-item">
                <span class="kv-key">发光</span>
                <input
                  class="field-input nav-display-config-input"
                  type="number"
                  min="0"
                  max="3"
                  step="0.1"
                  :value="display.pointEmissiveIntensity ?? 0"
                  @input="
                    updateMainDisplayPointEmissiveIntensity(
                      display.topic,
                      ($event.target as HTMLInputElement).value,
                    )
                  "
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
                  @input="
                    updateMainDisplayHzLimit(
                      display.topic,
                      ($event.target as HTMLInputElement).value,
                    )
                  "
                />
              </label>
              <label class="nav-display-config-item">
                <span class="kv-key">配色</span>
                <select
                  class="field-input nav-display-config-input"
                  :value="display.pointColorMode ?? 'solid'"
                  @change="
                    updateMainDisplayPointColorMode(
                      display.topic,
                      ($event.target as HTMLSelectElement).value,
                    )
                  "
                >
                  <option value="solid">纯色</option>
                  <option value="layered">分层增强</option>
                </select>
              </label>
            </div>
            <div
              v-else-if="
                display.kind === 'path' ||
                display.kind === 'pose' ||
                display.kind === 'marker' ||
                display.kind === 'bspline' ||
                display.kind === 'twist'
              "
              class="nav-display-config-row"
            >
              <label class="nav-display-config-item">
                <span class="kv-key">颜色</span>
                <input
                  class="nav-display-color-input"
                  type="color"
                  :value="
                    display.color ??
                    defaultMainDisplayColor(display.topic, display.kind)
                  "
                  @input="
                    updateMainDisplayColor(
                      display.topic,
                      ($event.target as HTMLInputElement).value,
                    )
                  "
                />
              </label>
            </div>
            <div
              v-else-if="display.kind === 'map'"
              class="nav-display-config-row"
            >
              <label class="nav-display-config-item">
                <span class="kv-key">透明度</span>
                <input
                  class="field-input nav-display-config-input"
                  type="number"
                  min="0.05"
                  max="1"
                  step="0.05"
                  :value="display.mapOpacity ?? 0.94"
                  @input="
                    updateMainDisplayMapOpacity(
                      display.topic,
                      ($event.target as HTMLInputElement).value,
                    )
                  "
                />
              </label>
            </div>
            <div
              v-else-if="display.kind === 'tf'"
              class="nav-display-tf-config"
            >
              <div class="nav-display-config-row tf">
                <label class="nav-display-config-item nav-display-check-item">
                  <span class="kv-key">显示名字</span>
                  <input
                    type="checkbox"
                    :checked="display.tfShowNames !== false"
                    @change="
                      updateMainDisplayTfShowNames(
                        display.topic,
                        ($event.target as HTMLInputElement).checked,
                      )
                    "
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
                    @input="
                      updateMainDisplayTfLabelSize(
                        display.topic,
                        ($event.target as HTMLInputElement).value,
                      )
                    "
                  />
                </label>
              </div>
              <div class="nav-tf-frame-filter">
                <div class="nav-tf-frame-filter-head">
                  <span class="kv-key">TF 节点筛选</span>
                  <button
                    class="secondary-btn small"
                    type="button"
                    @click="showAllMainDisplayTfFrames(display.topic)"
                  >
                    显示全部
                  </button>
                </div>
                <div
                  v-if="tfFramesForDisplay(display.topic).length > 0"
                  class="nav-tf-frame-chip-list"
                >
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
                <div v-else class="section-subtitle">
                  连接后读取 TF 节点列表。
                </div>
              </div>
            </div>
            <div
              v-else-if="display.kind === 'obstacle_zone'"
              class="section-subtitle"
            >
              绑定当前主位姿话题绘制检测圈、冷静区、危险区与忽略区，状态来自
              {{ display.topic }}。
            </div>
          </div>
          <div v-if="navMainDisplays.length === 0" class="section-empty">
            当前没有主视图显示项，请从右侧话题列表中添加。
          </div>
        </div></template
      >
      <template v-if="activeDrawer === 'diagnostics'"
        ><details
          :open="isDetailsOpen('diagnostics-topic-panels', true)"
          @toggle="onDetailsToggle('diagnostics-topic-panels', $event)"
        >
          <summary>话题详情</summary>
          <section class="panel nav-panel-list-panel">
            <div class="section-head">
              <div>
                <div class="result-title">完整小窗列表</div>
                <div class="section-subtitle">
                  这里保留更大的卡片视图，方便完整查看折线和消息内容。
                </div>
              </div>
            </div>

            <NavTopicPanelList
              v-if="!platformState.demo"
              :provider="formValues.ros_provider || 'rosbridge'"
              :url="
                connectionEnabled && rosDataSourceConfigLoaded
                  ? formValues.ros_bridge_url || ''
                  : ''
              "
              :timeout-ms="
                Number(normalizeRosBridgeTimeoutMs(formValues.timeout_ms))
              "
              :panels="navFullPanels"
              :reconnect-token="rosReconnectToken"
              @reorder="(from, to) => movePanel(navFullPanels, from, to)"
              @toggle="toggleNavFullPanel"
              @remove="removeNavFullPanel"
              @update-config="updateNavFullPanelConfig"
              @recording-saved="loadNavRecordingFiles"
              @ros-log="handleRosRuntimeLog"
            />
          </section>
        </details>
        <details
          :open="isDetailsOpen('diagnostics-latency', false)"
          @toggle="onDetailsToggle('diagnostics-latency', $event)"
        >
          <summary>链路延迟与时间戳</summary>
          <section class="panel nav-delay-panel">
            <div class="section-head">
              <button
                class="nav-runtime-toggle"
                type="button"
                @click="toggleNavDelayPanel"
              >
                <span class="collapse-trigger-label">
                  <span
                    class="collapse-caret"
                    :class="{ expanded: !navDelayPanelCollapsed }"
                    >▸</span
                  >
                  <span>链路延迟窗口</span>
                </span>
                <span class="section-card-meta"
                  >按文档第一优先级主链路显示各话题时间戳与年龄变化</span
                >
              </button>
              <div class="nav-recordings-actions">
                <button
                  class="secondary-btn"
                  type="button"
                  @click="reconnectNavDelayPanel"
                >
                  重连延迟窗口
                </button>
              </div>
            </div>

            <div
              v-if="!navDelayPanelCollapsed"
              class="section-subtitle nav-topic-feedback"
            >
              {{ navDelayMessage }}
            </div>

            <div v-if="!navDelayPanelCollapsed" class="nav-delay-overview-card">
              <div class="nav-delay-overview-head">
                <div>
                  <div class="result-title">链路时间戳总览</div>
                  <div class="section-subtitle">
                    同一张图里叠加所有主链路话题的绝对时间戳，并对显示做去趋势处理，方便把话题之间的时间差拉开看清楚；录制文件会同时保留绝对时间戳与
                    age_ms。
                  </div>
                </div>
                <div class="nav-delay-overview-tools">
                  <div class="nav-delay-topic-editor">
                    <textarea
                      v-model="navDelayTopicsInput"
                      class="field-input nav-delay-topic-textarea"
                      rows="5"
                      placeholder="/cloud_registered_body&#10;/cloud_registered_bl&#10;/points_aligned"
                    ></textarea>
                    <div class="nav-delay-topic-editor-actions">
                      <button
                        class="secondary-btn small"
                        type="button"
                        @click="applyNavDelayTopics"
                      >
                        应用话题
                      </button>
                    </div>
                  </div>
                  <div class="nav-delay-legend">
                    <button
                      v-for="definition in navDelayTopicDefinitions"
                      :key="`legend-${definition.topic}`"
                      class="nav-delay-legend-item"
                      :class="{
                        active: isNavDelayOverviewTopicSelected(
                          definition.topic,
                        ),
                      }"
                      type="button"
                      @click="toggleNavDelayOverviewTopic(definition.topic)"
                    >
                      <span
                        class="nav-delay-legend-dot"
                        :style="{ backgroundColor: definition.color }"
                      ></span>
                      <span
                        >{{ definition.label
                        }}<template v-if="!definition.resolved"
                          >（未识别类型）</template
                        ></span
                      >
                    </button>
                  </div>
                  <div class="nav-recording-inline">
                    <span
                      v-if="
                        navDelayOverviewRecording.isRecording ||
                        navDelayOverviewRecording.entries.length
                      "
                      class="nav-recording-pill"
                      :class="{ active: navDelayOverviewRecording.isRecording }"
                    >
                      {{
                        navDelayOverviewRecording.isRecording
                          ? "录制中"
                          : "已录制"
                      }}
                    </span>
                    <span
                      v-if="
                        navDelayOverviewRecording.isRecording ||
                        navDelayOverviewRecording.entries.length
                      "
                      class="nav-recording-meta"
                    >
                      {{
                        navDelayRecordingDurationText(navDelayOverviewRecording)
                      }}
                    </span>
                    <button
                      class="secondary-btn small"
                      :class="{
                        recording: navDelayOverviewRecording.isRecording,
                      }"
                      type="button"
                      @click="toggleNavDelayOverviewRecording"
                    >
                      {{
                        navDelayOverviewRecording.isRecording
                          ? "停止录制"
                          : "录制总览"
                      }}
                    </button>
                  </div>
                </div>
              </div>

              <svg
                class="nav-delay-overview-chart"
                viewBox="0 0 100 48"
                preserveAspectRatio="none"
              >
                <line
                  x1="0"
                  y1="46"
                  x2="100"
                  y2="46"
                  class="nav-delay-axis-line"
                />
                <polyline
                  v-for="line in navDelayAggregateLines"
                  :key="`line-${line.topic}`"
                  :points="line.points"
                  fill="none"
                  :stroke="line.color"
                  stroke-width="1.6"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  vector-effect="non-scaling-stroke"
                />
              </svg>
              <div class="nav-delay-axis-meta">
                <span>{{ navDelayOverviewAxisInfo.yLabel }}</span>
                <span>min {{ navDelayOverviewAxisInfo.minText }}</span>
                <span>max {{ navDelayOverviewAxisInfo.maxText }}</span>
                <span>{{ navDelayOverviewAxisInfo.xLabel }}</span>
              </div>
            </div>
          </section>
        </details>
        <details
          :open="isDetailsOpen('diagnostics-runtime-params', false)"
          @toggle="onDetailsToggle('diagnostics-runtime-params', $event)"
        >
          <summary>运行时参数</summary>
          <section class="panel nav-runtime-params-panel">
            <div class="section-head">
              <button
                class="nav-runtime-toggle"
                type="button"
                @click="toggleNavRuntimeParamsPanel"
              >
                <span class="collapse-trigger-label">
                  <span
                    class="collapse-caret"
                    :class="{ expanded: !navRuntimeParamsPanelCollapsed }"
                    >▸</span
                  >
                  <span>运行时参数窗口</span>
                </span>
                <span class="section-card-meta"
                  >按 Nav2 / NDT 分组展示实时参数</span
                >
              </button>
              <div class="nav-recordings-actions">
                <button
                  class="secondary-btn"
                  type="button"
                  :disabled="rosRuntimeParamsLoading"
                  @click="loadRosRuntimeParamsPanel"
                >
                  {{ rosRuntimeParamsLoading ? "刷新中..." : "刷新参数" }}
                </button>
              </div>
            </div>

            <div
              v-if="!navRuntimeParamsPanelCollapsed"
              class="section-subtitle nav-topic-feedback"
            >
              {{
                rosRuntimeParamsMessage ||
                "参数窗口按需手动刷新；你已经展开过的分组和节点会在刷新后保持展开，其余默认收起。"
              }}
            </div>

            <div
              v-if="
                !navRuntimeParamsPanelCollapsed &&
                rosRuntimeParams?.groups?.length
              "
              class="nav-runtime-groups"
            >
              <section
                v-for="group in rosRuntimeParams.groups"
                :key="group.key"
                class="nav-runtime-group"
              >
                <div class="nav-runtime-group-head">
                  <button
                    class="nav-runtime-group-toggle"
                    type="button"
                    @click="toggleNavRuntimeGroup(group.key)"
                  >
                    <span class="collapse-trigger-label">
                      <span
                        class="collapse-caret"
                        :class="{
                          expanded: !isNavRuntimeGroupCollapsed(group.key),
                        }"
                        >▸</span
                      >
                      <span class="result-title">{{ group.label }}</span>
                    </span>
                  </button>
                  <span
                    class="status-pill"
                    :class="{ success: rosRuntimeParams.status === 'success' }"
                    >{{ rosRuntimeParams.updated_at || "未更新时间" }}</span
                  >
                </div>

                <template v-if="!isNavRuntimeGroupCollapsed(group.key)">
                  <div
                    v-for="section in group.sections"
                    :key="`${group.key}-${section.title}`"
                    class="nav-runtime-section"
                  >
                    <div class="nav-runtime-section-title">
                      {{ section.title }}
                    </div>
                    <div
                      v-for="node in section.nodes"
                      :key="node.node"
                      class="nav-runtime-node"
                    >
                      <div class="nav-runtime-node-head">
                        <button
                          class="nav-runtime-node-toggle"
                          type="button"
                          @click="toggleNavRuntimeNode(group.key, node.node)"
                        >
                          <span class="collapse-trigger-label">
                            <span
                              class="collapse-caret"
                              :class="{
                                expanded: !isNavRuntimeNodeCollapsed(
                                  group.key,
                                  node.node,
                                ),
                              }"
                              >▸</span
                            >
                            <strong>{{ node.node }}</strong>
                          </span>
                        </button>
                        <span
                          v-if="node.error"
                          class="nav-runtime-node-error"
                          >{{ node.error }}</span
                        >
                        <span v-else class="nav-runtime-node-count"
                          >{{
                            Object.keys(node.params || {}).length
                          }}
                          个参数</span
                        >
                      </div>
                      <div
                        v-if="
                          !isNavRuntimeNodeCollapsed(group.key, node.node) &&
                          !node.error &&
                          Object.keys(node.params || {}).length
                        "
                        class="nav-runtime-param-grid"
                      >
                        <div
                          v-for="(value, key) in node.params"
                          :key="`${node.node}-${key}`"
                          class="nav-runtime-param-item"
                        >
                          <span class="kv-key">{{ key }}</span>
                          <span
                            class="kv-value"
                            :title="formatRuntimeParamValue(value)"
                            >{{ formatRuntimeParamValue(value) }}</span
                          >
                        </div>
                      </div>
                      <div
                        v-else-if="
                          !isNavRuntimeNodeCollapsed(group.key, node.node) &&
                          !node.error
                        "
                        class="section-empty"
                      >
                        当前节点没有读取到参数。
                      </div>
                    </div>
                  </div>
                </template>
              </section>
            </div>

            <div
              v-else-if="!navRuntimeParamsPanelCollapsed"
              class="section-empty"
            >
              当前还没有读取到运行时参数。请确认 rosbridge
              连通，且机器人侧参数服务可访问。
            </div>

            <div
              v-if="
                !navRuntimeParamsPanelCollapsed &&
                rosRuntimeParams?.failed_nodes?.length
              "
              class="logs nav-runtime-failures"
            >
              {{ rosRuntimeParams.failed_nodes.join("\n") }}
            </div>
          </section>
        </details>
        <details
          :open="isDetailsOpen('diagnostics-recordings', false)"
          @toggle="onDetailsToggle('diagnostics-recordings', $event)"
        >
          <summary>录制文件</summary>
          <section class="panel nav-recordings-panel-shell">
            <div class="nav-recordings-panel">
              <div class="section-head">
                <div>
                  <div class="result-title">录制文件</div>
                  <div class="section-subtitle">
                    固定读取录制目录中的文本和图片，便于回看和整理。
                  </div>
                </div>
                <div class="nav-recordings-actions">
                  <button
                    class="secondary-btn"
                    type="button"
                    :disabled="navRecordingFilesLoading"
                    @click="loadNavRecordingFiles"
                  >
                    {{ navRecordingFilesLoading ? "刷新中..." : "刷新文件" }}
                  </button>
                  <button
                    class="secondary-btn"
                    type="button"
                    @click="
                      openLocalPath(
                        navRecordingFilesDirectory || 'output_nav/recordings',
                      )
                    "
                  >
                    打开目录
                  </button>
                </div>
              </div>

              <div class="section-subtitle nav-topic-feedback">
                {{
                  navRecordingFilesMessage ||
                  "录制停止后会在固定目录中生成录制文本文件；若文本中包含指标数据，这里会自动生成可交互图表。"
                }}
              </div>

              <div class="nav-recordings-browser">
                <div class="nav-recordings-filelist">
                  <div
                    v-for="item in navRecordingFiles"
                    :key="item.path"
                    class="nav-recordings-fileitem"
                    :class="{ active: navRecordingPreviewPath === item.path }"
                  >
                    <button
                      class="nav-recordings-filemain"
                      type="button"
                      @click="previewNavRecordingFile(item)"
                    >
                      <span class="nav-recordings-filemeta">
                        <strong>{{ item.name }}</strong>
                        <span>{{ item.modified_at }} · {{ item.kind }}</span>
                      </span>
                    </button>
                    <span class="nav-recordings-filemeta">
                      <button
                        class="secondary-btn small"
                        type="button"
                        @click.stop="removeNavRecordingFile(item.path)"
                      >
                        删除
                      </button>
                    </span>
                  </div>
                  <div
                    v-if="navRecordingFiles.length === 0"
                    class="section-empty"
                  >
                    当前没有录制文件。
                  </div>
                </div>

                <div class="nav-recordings-preview">
                  <img
                    v-if="
                      navRecordingPreviewKind === 'image' &&
                      navRecordingPreviewPath
                    "
                    class="nav-recordings-preview-image"
                    :src="buildBackendImageUrl(navRecordingPreviewPath)"
                    alt="录制图片预览"
                  />
                  <template
                    v-else-if="
                      navRecordingPreviewKind === 'text' &&
                      navRecordingPreviewPath
                    "
                  >
                    <pre class="logs nav-recordings-preview-text">{{
                      navRecordingPreviewText
                    }}</pre>
                    <div
                      v-if="navRecordingParsedPayload?.metric_series?.length"
                      class="nav-recordings-chart"
                    >
                      <div class="nav-recordings-chart-head">
                        <div class="result-title">录制图表</div>
                        <div class="nav-recordings-chart-actions">
                          <button
                            v-for="metric in navRecordingParsedPayload.metric_series"
                            :key="metric.label"
                            class="nav-recordings-chart-chip"
                            :class="{
                              active:
                                navRecordingChartMetricLabel === metric.label,
                            }"
                            type="button"
                            @click="setNavRecordingMetric(metric.label)"
                          >
                            {{ metric.label }}
                          </button>
                          <button
                            class="secondary-btn small"
                            type="button"
                            @click="zoomNavRecordingChart(0.8)"
                          >
                            放大
                          </button>
                          <button
                            class="secondary-btn small"
                            type="button"
                            @click="zoomNavRecordingChart(1.25)"
                          >
                            缩小
                          </button>
                          <button
                            class="secondary-btn small"
                            type="button"
                            @click="
                              resetNavRecordingChartState(
                                navRecordingParsedPayload,
                              )
                            "
                          >
                            重置
                          </button>
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
                        <div
                          v-if="navRecordingChartHover"
                          class="nav-recordings-chart-tooltip"
                        >
                          <strong>{{
                            navRecordingChartTimeText(
                              navRecordingChartHover.offsetMs,
                            )
                          }}</strong>
                          <span
                            >{{ activeNavRecordingMetric?.label }}:
                            {{ navRecordingChartHover.value.toFixed(3) }}</span
                          >
                        </div>
                        <svg
                          class="nav-recordings-chart-svg"
                          viewBox="0 0 1000 220"
                          preserveAspectRatio="none"
                        >
                          <line
                            x1="0"
                            y1="190"
                            x2="1000"
                            y2="190"
                            stroke="#21334d"
                            stroke-width="1"
                          />
                          <line
                            x1="0"
                            y1="24"
                            x2="0"
                            y2="190"
                            stroke="#21334d"
                            stroke-width="1"
                          />
                          <polyline
                            v-if="activeNavRecordingMetricSamples.length"
                            :points="navRecordingChartPolylinePoints()"
                            :stroke="
                              activeNavRecordingMetric?.color || '#2f8cff'
                            "
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
                  <div v-else class="section-empty">
                    选择一个录制文件后，这里会显示文本或图片预览。
                  </div>
                </div>
              </div>
            </div>
          </section>
        </details>
        <details
          :open="isDetailsOpen('diagnostics-inspection', false)"
          @toggle="onDetailsToggle('diagnostics-inspection', $event)"
        >
          <summary>接入检测</summary>
          <section class="panel nav-status-panel">
            <div class="section-head">
              <div>
                <div class="result-title">主视图状态</div>
                <div class="section-subtitle">
                  这里同时展示数据层检测结果，便于判断机器狗当前到底暴露了什么接入方式。
                </div>
              </div>
            </div>

            <div class="kv-list">
              <div class="kv-item">
                <span class="kv-key">接入方式</span>
                <span class="kv-value">{{
                  formValues.ros_provider || "rosbridge"
                }}</span>
              </div>
              <div class="kv-item">
                <span class="kv-key">Bridge 地址</span>
                <span class="kv-value">{{
                  formValues.ros_bridge_url || "未配置"
                }}</span>
              </div>
              <div class="kv-item">
                <span class="kv-key">地图 Topic</span>
                <span class="kv-value">{{
                  formValues.map_topic || "/debug/loaded_pointcloud_map"
                }}</span>
              </div>
              <div class="kv-item">
                <span class="kv-key">定位 Topic</span>
                <span class="kv-value">{{
                  formValues.pose_topic || "/ndt_pose"
                }}</span>
              </div>
              <div class="kv-item">
                <span class="kv-key">计划路径 Topic</span>
                <span class="kv-value">{{
                  formValues.path_topic || "/plan"
                }}</span>
              </div>
              <div class="kv-item">
                <span class="kv-key">已选 Topic</span>
                <span class="kv-value">{{
                  selectedNavTopicOptions.map((item) => item.key).join("、") ||
                  "暂未临时选择"
                }}</span>
              </div>
              <div class="kv-item">
                <span class="kv-key">共享连接键</span>
                <span class="kv-value">{{
                  rosSharedSessionStats.sharedKey || "未生成"
                }}</span>
              </div>
            </div>

            <div class="nav-detection-card">
              <div class="result-title nav-detection-title">接入检测结果</div>
              <p class="summary">
                {{
                  rosInspectResult?.message ||
                  "点击“检测接入方式”后，这里会显示当前桥接能力、可用提示和 topic 检测结果。"
                }}
              </p>
              <div class="nav-detection-meta">
                <span
                  class="status-pill"
                  :class="{ success: rosInspectResult?.status === 'success' }"
                  >{{ rosInspectResult?.status || "未检测" }}</span
                >
                <span class="nav-detection-count"
                  >topics: {{ rosInspectResult?.topics_count ?? 0 }}</span
                >
              </div>
              <div
                v-if="rosInspectResult?.capabilities?.length"
                class="nav-capability-list"
              >
                <span
                  v-for="capability in rosInspectResult.capabilities"
                  :key="capability"
                  class="nav-capability-chip"
                  >{{ capability }}</span
                >
              </div>
              <ul
                v-if="rosInspectResult?.detected_hints?.length"
                class="nav-hints-list"
              >
                <li v-for="hint in rosInspectResult.detected_hints" :key="hint">
                  {{ hint }}
                </li>
              </ul>
            </div>
          </section>
        </details>
        <details
          :open="isDetailsOpen('diagnostics-logs', false)"
          @toggle="onDetailsToggle('diagnostics-logs', $event)"
        >
          <summary>运行日志</summary>
          <button @click="clearToolLogs">清空日志</button>
          <pre class="logs">{{ mergedToolLogs.join("\n") }}</pre>
        </details></template
      >
    </GlassDrawer>
  </main>
</template>

<style scoped>
.workspace-fade-enter-active,
.workspace-fade-leave-active {
  transition: opacity 180ms ease;
}
.workspace-fade-enter-from,
.workspace-fade-leave-to {
  opacity: 0;
}
.workspace-fade-leave-active {
  pointer-events: none;
}
.workspace-mode-switch {
  position: absolute;
  top: 24px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 15;
  display: flex;
  padding: 4px;
  border-radius: 14px;
}
.workspace-mode-switch button {
  border: 0;
  background: transparent;
  padding: 10px 32px;
  font-size: 15px;
  font-weight: 600;
}
.workspace-mode-switch button.active {
  background: #ee5268;
  color: white;
  box-shadow: 0 3px 12px #ee526830;
}
@media (max-width: 850px) {
  .workspace-mode-switch {
    top: 90px;
  }
  .workspace-mode-switch button {
    padding: 7px 22px;
  }
}
</style>
