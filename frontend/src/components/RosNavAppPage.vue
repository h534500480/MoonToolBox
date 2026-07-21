<!-- 功能说明：独立 ROS 移动端工作台，采用横屏沉浸式 APP 布局，把主视图常驻、工具能力以浮层形式覆盖。 -->
<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import Nav3DViewer from "./Nav3DViewer.vue";
import NavTopicPanelList from "./NavTopicPanelList.vue";
import { buildSharedRosKey, createSharedRosLiveAdapter, type RosLiveAdapter, type RosLiveConfig } from "../lib/ros/liveAdapter";
import { createMobileDetailPanel, type MobileNavTopicOption, type MobileRosConnectionConfig } from "../lib/ros/mobileCatalog";
import {
  addTopicToMobileMainView,
  hasMobileMainDisplay,
  inspectMobileRosConnection as inspectMobileRosConnectionState,
  loadMobileRosAppState,
  mobileRosAppState,
  refreshMobileRuntimeParams as refreshMobileRuntimeParamsState,
  refreshMobileTopics as refreshMobileTopicsState,
  removeTopicFromMobileMainView,
  updateMobileConnectionConfig,
  updateMobileMainDisplay,
} from "../lib/ros/mobileAppState";

const route = useRoute();
const router = useRouter();

const routePageKeys = ["home", "config", "main", "topics", "runtime"] as const;
type RoutePageKey = typeof routePageKeys[number];

const menuOpen = ref(false);
const exportSheetOpen = ref(false);
const layerDrawerOpen = ref(false);
const statusPanelOpen = ref(false);
const runDockOpen = ref(false);
const topicQuery = ref("");
const navInteractionMode = ref<"none" | "initialpose" | "navgoal">("none");
const navControlLoading = ref(false);
const navControlMessage = ref("");
const navGoalSequence = ref(1);
const rosLogs = ref<string[]>(["[INFO] ROS 移动端工作台已启动"]);
const viewerReconnectToken = ref(0);
const runtimeGroupCollapsed = ref<Record<string, boolean>>({});
const runtimeNodeCollapsed = ref<Record<string, boolean>>({});
const navTfFrameOptions = ref<Record<string, string[]>>({});
const ndtHealthStatus = ref<{ label: string; tone: "neutral" | "success" | "warning" | "danger" }>({
  label: "未定位",
  tone: "neutral",
});
const obstacleZoneStatus = ref<{ label: string; tone: "neutral" | "success" | "warning" | "danger" }>({
  label: "未知",
  tone: "neutral",
});
const layerDrawerRef = ref<HTMLElement | null>(null);
const layerDrawerHeightPx = ref(0);
const layerDrawerDragTranslatePx = ref<number | null>(null);
const connectionDraft = ref<MobileRosConnectionConfig>({ ...mobileRosAppState.connection });
const layerInputDrafts = ref<Record<string, string>>({});

let mobileSharedAdapter: RosLiveAdapter | null = null;
let mobileStatusUnsubscribes: Array<() => void> = [];
let layerDrawerResizeObserver: ResizeObserver | null = null;
let layerDrawerActivePointerId: number | null = null;
let layerDrawerStartClientY = 0;
let layerDrawerStartTranslatePx = 0;
let layerDrawerMoved = false;
let visualViewportCleanup: (() => void) | null = null;

const currentPage = computed<RoutePageKey>(() => {
  const page = typeof route.params.page === "string" ? route.params.page : "main";
  return routePageKeys.includes(page as RoutePageKey) ? (page as RoutePageKey) : "main";
});

const currentTopicKey = computed(() => {
  return typeof route.query.topic === "string" ? route.query.topic : "";
});

const connectionStateLabel = computed(() => {
  const status = mobileRosAppState.inspectResult?.status || "";
  if (status === "success") {
    return "已连接";
  }
  if (status === "partial") {
    return "部分可用";
  }
  if (status === "error") {
    return "检测失败";
  }
  if (mobileRosAppState.inspectLoading) {
    return "检测中";
  }
  return "未检测";
});

const connectionStateTone = computed(() => {
  const status = mobileRosAppState.inspectResult?.status || "";
  if (status === "success") {
    return "connected";
  }
  if (status === "partial") {
    return "partial";
  }
  if (status === "error") {
    return "danger";
  }
  return "idle";
});

const viewerStatusText = computed(() => {
  if (navInteractionMode.value === "initialpose") {
    return "初始化定位模式中，请在主视图中按下并拖动方向。";
  }
  if (navInteractionMode.value === "navgoal") {
    return "导航目标模式中，请在主视图中按下并拖动方向。";
  }
  return navControlMessage.value || mobileRosAppState.inspectResult?.message || "";
});

const latestStatusTitle = computed(() => {
  if (navInteractionMode.value === "initialpose") {
    return "定位模式";
  }
  if (navInteractionMode.value === "navgoal") {
    return "导航模式";
  }
  return "运行日志";
});

const latestStatusMessage = computed(() => {
  if (viewerStatusText.value) {
    return viewerStatusText.value;
  }
  return rosLogs.value[0] || "暂无日志";
});

const filteredTopicOptions = computed(() => {
  const keyword = topicQuery.value.trim().toLowerCase();
  if (!keyword) {
    return mobileRosAppState.topicOptions;
  }
  return mobileRosAppState.topicOptions.filter((item) => `${item.key} ${item.label} ${item.type} ${item.note}`.toLowerCase().includes(keyword));
});

const selectedTopicOption = computed(() => {
  if (!currentTopicKey.value) {
    return null;
  }
  const matched = mobileRosAppState.topicOptions.find((item) => item.key === currentTopicKey.value);
  if (matched) {
    return matched;
  }
  return {
    key: currentTopicKey.value,
    label: currentTopicKey.value.split("/").filter(Boolean).pop() || currentTopicKey.value,
    type: "",
    note: "来自当前选择的话题。",
  } satisfies MobileNavTopicOption;
});

const detailPanels = computed(() => {
  if (!selectedTopicOption.value) {
    return [];
  }
  return [createMobileDetailPanel(selectedTopicOption.value)];
});

const menuEntries = [
  { key: "home", label: "模块中心", kind: "route" },
  { key: "config", label: "连接配置", kind: "route" },
  { key: "topics", label: "话题浏览", kind: "route" },
  { key: "runtime", label: "运行参数", kind: "route" },
  { key: "layers", label: "图层管理", kind: "drawer" },
  { key: "export", label: "快照导出", kind: "local" },
] as const;

const layerDrawerPeekPx = 0;
const layerDrawerCollapsedTranslatePx = computed(() => {
  return Math.max(0, layerDrawerHeightPx.value - layerDrawerPeekPx);
});

const layerDrawerStyle = computed(() => {
  const translateY = layerDrawerDragTranslatePx.value ?? (layerDrawerOpen.value ? 0 : layerDrawerCollapsedTranslatePx.value);
  return {
    transform: `translateY(${Math.max(0, translateY)}px)`,
  };
});

function mapNdtStatus(rawValue: unknown) {
  const statusValue = Number(rawValue ?? 0);
  if (statusValue === 1) {
    return { label: "健康", tone: "success" as const };
  }
  if (statusValue === 2) {
    return { label: "退化", tone: "warning" as const };
  }
  if (statusValue === 3) {
    return { label: "丢失", tone: "danger" as const };
  }
  return { label: "未定位", tone: "neutral" as const };
}

function mapObstacleZoneStatus(rawValue: unknown) {
  const statusValue = Number(rawValue ?? -1);
  if (statusValue === 0) {
    return { label: "安全", tone: "success" as const };
  }
  if (statusValue === 1) {
    return { label: "冷静区", tone: "warning" as const };
  }
  if (statusValue === 2) {
    return { label: "危险区", tone: "danger" as const };
  }
  return { label: "未知", tone: "neutral" as const };
}

function resetMobileStatusCards() {
  ndtHealthStatus.value = { label: "未定位", tone: "neutral" };
  obstacleZoneStatus.value = { label: "未知", tone: "neutral" };
}

function syncConnectionDraftFromState() {
  connectionDraft.value = { ...mobileRosAppState.connection };
}

function layerInputDraftKey(topic: string, field: string) {
  return `${topic}::${field}`;
}

function syncLayerInputDraft(topic: string, field: string, value: string) {
  layerInputDrafts.value = {
    ...layerInputDrafts.value,
    [layerInputDraftKey(topic, field)]: value,
  };
}

function removeLayerInputDraft(topic: string, field: string) {
  const draftKey = layerInputDraftKey(topic, field);
  if (!(draftKey in layerInputDrafts.value)) {
    return;
  }
  const nextDrafts = { ...layerInputDrafts.value };
  delete nextDrafts[draftKey];
  layerInputDrafts.value = nextDrafts;
}

function layerInputValue(topic: string, field: string, fallback: string) {
  return layerInputDrafts.value[layerInputDraftKey(topic, field)] ?? fallback;
}

function buildMobileSharedRosConfig(): RosLiveConfig {
  return {
    provider: connectionDraft.value.provider || mobileRosAppState.connection.provider,
    url: (connectionDraft.value.url || mobileRosAppState.connection.url).trim(),
    timeoutMs: Number(connectionDraft.value.timeoutMs || mobileRosAppState.connection.timeoutMs || "8000"),
    autoReconnect: true,
    reconnectBaseDelayMs: 2000,
    reconnectMaxDelayMs: 30000,
    reconnectMaxAttempts: 5,
    sharedKey: buildSharedRosKey(
      "ros-nav-test",
      connectionDraft.value.provider || mobileRosAppState.connection.provider,
      (connectionDraft.value.url || mobileRosAppState.connection.url).trim(),
      Number(connectionDraft.value.timeoutMs || mobileRosAppState.connection.timeoutMs || "8000")
    ),
    adapterName: "ROS 测试工作台共享连接",
  };
}

function createMobileSharedAdapter() {
  const baseConfig = buildMobileSharedRosConfig();
  return createSharedRosLiveAdapter({
    ...baseConfig,
    adapterName: "移动端工作台",
    onError: (event) => {
      appendRosLog(event.recoverable ? "warning" : "error", `${event.scope}: ${event.message}${event.detail ? ` (${event.detail})` : ""}`);
    },
  });
}

function rebuildMobileSharedAdapter() {
  mobileSharedAdapter?.disconnect();
  mobileSharedAdapter = null;
  const url = mobileRosAppState.connection.url.trim();
  if (!url || mobileRosAppState.connection.provider !== "rosbridge") {
    return null;
  }
  mobileSharedAdapter = createMobileSharedAdapter();
  return mobileSharedAdapter;
}

async function ensureMobileSharedAdapterConnected() {
  const url = (connectionDraft.value.url || mobileRosAppState.connection.url).trim();
  const provider = connectionDraft.value.provider || mobileRosAppState.connection.provider;
  if (!url || provider !== "rosbridge") {
    throw new Error("当前未配置可用的 rosbridge 地址。");
  }
  const adapter = mobileSharedAdapter ?? rebuildMobileSharedAdapter();
  if (!adapter) {
    throw new Error("当前未创建共享连接。");
  }
  await adapter.connect();
  return adapter;
}

function teardownMobileStatusSubscriptions() {
  mobileStatusUnsubscribes.forEach((unsubscribe) => unsubscribe());
  mobileStatusUnsubscribes = [];
}

async function connectMobileStatusSubscriptions() {
  teardownMobileStatusSubscriptions();
  resetMobileStatusCards();

  const url = mobileRosAppState.connection.url.trim();
  if (!url || mobileRosAppState.connection.provider !== "rosbridge") {
    return;
  }

  try {
    const adapter = await ensureMobileSharedAdapterConnected();
    mobileStatusUnsubscribes = [
      adapter.subscribe("/ndt_status", "std_msgs/msg/UInt8", (message) => {
        ndtHealthStatus.value = mapNdtStatus(message?.data);
      }),
      adapter.subscribe("/geneox_mid360_obstacle", "std_msgs/msg/UInt8", (message) => {
        obstacleZoneStatus.value = mapObstacleZoneStatus(message?.data);
      }),
    ];
  } catch (error) {
    appendRosLog("warning", `状态订阅失败: ${(error as Error).message}`);
  }
}

function scrollFocusedFieldIntoView(event: FocusEvent) {
  const target = event.target;
  if (!(target instanceof HTMLElement)) {
    return;
  }
  const field = target.closest("input, select, textarea");
  if (!(field instanceof HTMLElement)) {
    return;
  }
  window.setTimeout(() => {
    const scrollContainer = field.closest(
      ".ros-mobile-bottom-drawer-body, .ros-mobile-config-modal, .ros-mobile-side-sheet-scroll, .ros-mobile-topic-browser, .ros-mobile-topic-preview"
    );
    if (!(scrollContainer instanceof HTMLElement)) {
      field.scrollIntoView({ block: "center", inline: "nearest", behavior: "smooth" });
      return;
    }
    const containerRect = scrollContainer.getBoundingClientRect();
    const fieldRect = field.getBoundingClientRect();
    const keyboardInset = Number.parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--mobile-keyboard-inset")) || 0;
    const safeTop = containerRect.top + 20;
    const safeBottom = containerRect.bottom - Math.max(88, Math.min(containerRect.height * 0.38, keyboardInset + 36));
    if (fieldRect.bottom > safeBottom) {
      scrollContainer.scrollBy({
        top: fieldRect.bottom - safeBottom,
        behavior: "smooth",
      });
      return;
    }
    if (fieldRect.top < safeTop) {
      scrollContainer.scrollBy({
        top: fieldRect.top - safeTop,
        behavior: "smooth",
      });
    }
  }, 180);
}

function installVisualViewportKeyboardSync() {
  const root = document.documentElement;
  const viewport = window.visualViewport;
  if (!viewport) {
    root.style.setProperty("--mobile-keyboard-inset", "0px");
    return () => root.style.setProperty("--mobile-keyboard-inset", "0px");
  }
  const applyInset = () => {
    const inset = Math.max(0, window.innerHeight - viewport.height - viewport.offsetTop);
    root.style.setProperty("--mobile-keyboard-inset", `${Math.round(inset)}px`);
  };
  applyInset();
  viewport.addEventListener("resize", applyInset);
  viewport.addEventListener("scroll", applyInset);
  return () => {
    viewport.removeEventListener("resize", applyInset);
    viewport.removeEventListener("scroll", applyInset);
    root.style.setProperty("--mobile-keyboard-inset", "0px");
  };
}

function isRoutePageKey(page: string): page is RoutePageKey {
  return routePageKeys.includes(page as RoutePageKey);
}

function openPage(pageKey: RoutePageKey, topic = "") {
  const query = topic ? { topic } : {};
  void router.push({ name: "ros-nav-app", params: { page: pageKey }, query });
}

function closeToMain() {
  if (currentPage.value !== "main" || currentTopicKey.value) {
    openPage("main");
  }
}

function openMenuEntry(entry: typeof menuEntries[number]) {
  menuOpen.value = false;
  if (entry.kind === "route" && isRoutePageKey(entry.key)) {
    openPage(entry.key);
    return;
  }
  if (entry.kind === "drawer") {
    layerDrawerOpen.value = true;
    closeToMain();
    return;
  }
  if (entry.key === "export") {
    exportSheetOpen.value = true;
    closeToMain();
  }
}

function appendRosLog(level: "info" | "warning" | "error", message: string) {
  rosLogs.value = [`[${level.toUpperCase()}] ${message}`, ...rosLogs.value].slice(0, 120);
}

async function inspectMobileRosConnection() {
  try {
    const adapter = await ensureMobileSharedAdapterConnected();
    await inspectMobileRosConnectionState(adapter);
  } catch (error) {
    mobileRosAppState.inspectResult = {
      provider: mobileRosAppState.connection.provider,
      status: "error",
      message: `连接 rosbridge 失败: ${(error as Error).message}`,
      capabilities: [],
      detected_hints: [],
      topics_count: 0,
    };
  }
}

async function refreshMobileTopics() {
  try {
    const adapter = await ensureMobileSharedAdapterConnected();
    await refreshMobileTopicsState(adapter);
  } catch (error) {
    mobileRosAppState.topicsLoading = false;
    mobileRosAppState.topicsMessage = `读取话题失败: ${(error as Error).message}`;
  }
}

async function refreshMobileRuntimeParams() {
  try {
    const adapter = await ensureMobileSharedAdapterConnected();
    await refreshMobileRuntimeParamsState(adapter);
  } catch (error) {
    mobileRosAppState.runtimeLoading = false;
    mobileRosAppState.runtimeMessage = `读取运行时参数失败: ${(error as Error).message}`;
  }
}

function persistConnectionConfig() {
  const nextConnection = {
    ...connectionDraft.value,
    timeoutMs: normalizeTimeoutMs(connectionDraft.value.timeoutMs || "8000"),
  };
  updateMobileConnectionConfig(nextConnection);
  syncConnectionDraftFromState();
  viewerReconnectToken.value += 1;
  appendRosLog("info", `已保存连接配置: ${mobileRosAppState.connection.url || "未配置地址"}`);
}

function normalizeTimeoutMs(rawValue: string) {
  const parsed = Number(rawValue || "8000");
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return "8000";
  }
  return `${Math.max(8000, Math.round(parsed))}`;
}

function updateConnectionDraftField(key: keyof MobileRosConnectionConfig, value: string) {
  connectionDraft.value = {
    ...connectionDraft.value,
    [key]: value,
  };
}

function updateConnectionField(key: keyof MobileRosConnectionConfig, value: string) {
  if (key === "timeoutMs") {
    updateConnectionDraftField(key, value);
    return;
  }
  updateConnectionDraftField(key, value);
}

function openTopicDetail(topic: string) {
  openPage("topics", topic);
}

function backToTopicList() {
  openPage("topics");
}

function removeMainDisplay(topic: string) {
  removeTopicFromMobileMainView(topic);
}

function updateMainDisplayColor(topic: string, rawValue: string) {
  updateMobileMainDisplay(topic, { color: rawValue });
}

function updateMainDisplayPointSize(topic: string, rawValue: string) {
  const pointSize = Math.min(0.6, Math.max(0.01, Number(rawValue || "0.08") || 0.08));
  updateMobileMainDisplay(topic, { pointSize });
}

function updateMainDisplayHzLimit(topic: string, rawValue: string) {
  const hzLimit = Math.max(0, Math.round(Number(rawValue || "0") || 0));
  updateMobileMainDisplay(topic, { hzLimit });
}

function updateMainDisplayMapOpacity(topic: string, rawValue: string) {
  const mapOpacity = Math.min(1, Math.max(0.05, Number(rawValue || "0.55") || 0.55));
  updateMobileMainDisplay(topic, { mapOpacity });
}

function updateMainDisplayTfLabelSize(topic: string, rawValue: string) {
  const tfLabelSize = Math.min(2, Math.max(0.2, Number(rawValue || "0.5") || 0.5));
  updateMobileMainDisplay(topic, { tfLabelSize });
}

function updateLayerDraft(topic: string, field: string, value: string) {
  syncLayerInputDraft(topic, field, value);
}

function commitLayerNumberInput(topic: string, field: "pointSize" | "hzLimit" | "mapOpacity" | "tfLabelSize", rawValue: string) {
  if (!rawValue.trim()) {
    const display = mobileRosAppState.mainDisplays.find((item) => item.topic === topic);
    if (display) {
      syncLayerInputDraft(topic, field, String(display[field] ?? ""));
    }
    return;
  }
  if (field === "pointSize") {
    updateMainDisplayPointSize(topic, rawValue);
    syncLayerInputDraft(topic, field, String(mobileRosAppState.mainDisplays.find((item) => item.topic === topic)?.pointSize ?? 0.08));
    return;
  }
  if (field === "hzLimit") {
    updateMainDisplayHzLimit(topic, rawValue);
    syncLayerInputDraft(topic, field, String(mobileRosAppState.mainDisplays.find((item) => item.topic === topic)?.hzLimit ?? 0));
    return;
  }
  if (field === "mapOpacity") {
    updateMainDisplayMapOpacity(topic, rawValue);
    syncLayerInputDraft(topic, field, String(mobileRosAppState.mainDisplays.find((item) => item.topic === topic)?.mapOpacity ?? 0.55));
    return;
  }
  updateMainDisplayTfLabelSize(topic, rawValue);
  syncLayerInputDraft(topic, field, String(mobileRosAppState.mainDisplays.find((item) => item.topic === topic)?.tfLabelSize ?? 0.5));
}

function commitConnectionDraftField(key: keyof MobileRosConnectionConfig) {
  if (key !== "timeoutMs") {
    return;
  }
  connectionDraft.value = {
    ...connectionDraft.value,
    timeoutMs: normalizeTimeoutMs(connectionDraft.value.timeoutMs || "8000"),
  };
}

function handleTextFieldConfirm(event: KeyboardEvent) {
  if (event.key !== "Enter") {
    return;
  }
  event.preventDefault();
  const target = event.target;
  if (target instanceof HTMLElement) {
    target.blur();
  }
}

function updateMainDisplayTfShowNames(topic: string, checked: boolean) {
  updateMobileMainDisplay(topic, { tfShowNames: checked });
}

function tfFramesForDisplay(topic: string) {
  return navTfFrameOptions.value[topic] || [];
}

function isTfFrameSelected(display: (typeof mobileRosAppState.mainDisplays)[number], frameName: string) {
  const selectedFrames = display.tfVisibleFrames ?? [];
  return selectedFrames.length === 0 || selectedFrames.includes(frameName);
}

function showAllMainDisplayTfFrames(topic: string) {
  updateMobileMainDisplay(topic, { tfVisibleFrames: [] });
}

function toggleMainDisplayTfFrame(topic: string, frameName: string) {
  const display = mobileRosAppState.mainDisplays.find((item) => item.topic === topic);
  if (!display) {
    return;
  }
  const currentFrames = display.tfVisibleFrames ?? [];
  if (currentFrames.length === 0) {
    updateMobileMainDisplay(topic, { tfVisibleFrames: [frameName] });
    return;
  }
  const nextFrames = currentFrames.includes(frameName)
    ? currentFrames.filter((item) => item !== frameName)
    : [...currentFrames, frameName];
  updateMobileMainDisplay(topic, { tfVisibleFrames: nextFrames });
}

function handleTfFramesChange(payload: { topic: string; frames: string[] }) {
  navTfFrameOptions.value = {
    ...navTfFrameOptions.value,
    [payload.topic]: payload.frames,
  };
}

function updateLayerDrawerMetrics() {
  if (!layerDrawerRef.value) {
    return;
  }
  layerDrawerHeightPx.value = Math.round(layerDrawerRef.value.getBoundingClientRect().height);
}

function onLayerDrawerHandleClick() {
  if (layerDrawerMoved) {
    layerDrawerMoved = false;
    return;
  }
  layerDrawerOpen.value = !layerDrawerOpen.value;
}

function onLayerDrawerPointerDown(event: PointerEvent) {
  if (event.pointerType === "mouse" && event.button !== 0) {
    return;
  }
  const handle = event.currentTarget;
  if (!(handle instanceof HTMLElement)) {
    return;
  }
  layerDrawerActivePointerId = event.pointerId;
  layerDrawerStartClientY = event.clientY;
  layerDrawerStartTranslatePx = layerDrawerDragTranslatePx.value ?? (layerDrawerOpen.value ? 0 : layerDrawerCollapsedTranslatePx.value);
  layerDrawerMoved = false;
  handle.setPointerCapture(event.pointerId);
}

function onLayerDrawerPointerMove(event: PointerEvent) {
  if (layerDrawerActivePointerId !== event.pointerId) {
    return;
  }
  const deltaY = event.clientY - layerDrawerStartClientY;
  if (Math.abs(deltaY) > 4) {
    layerDrawerMoved = true;
  }
  const nextTranslate = Math.min(layerDrawerCollapsedTranslatePx.value, Math.max(0, layerDrawerStartTranslatePx + deltaY));
  layerDrawerDragTranslatePx.value = nextTranslate;
  event.preventDefault();
}

function finishLayerDrawerDrag() {
  const currentTranslate = layerDrawerDragTranslatePx.value;
  layerDrawerActivePointerId = null;
  if (currentTranslate === null) {
    return;
  }
  const shouldOpen = currentTranslate < layerDrawerCollapsedTranslatePx.value * 0.55;
  layerDrawerOpen.value = shouldOpen;
  layerDrawerDragTranslatePx.value = null;
}

function onLayerDrawerPointerUp(event: PointerEvent) {
  if (layerDrawerActivePointerId !== event.pointerId) {
    return;
  }
  const handle = event.currentTarget;
  if (handle instanceof HTMLElement) {
    handle.releasePointerCapture(event.pointerId);
  }
  finishLayerDrawerDrag();
}

function onLayerDrawerPointerCancel(event: PointerEvent) {
  if (layerDrawerActivePointerId !== event.pointerId) {
    return;
  }
  const handle = event.currentTarget;
  if (handle instanceof HTMLElement) {
    handle.releasePointerCapture(event.pointerId);
  }
  finishLayerDrawerDrag();
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
  const adapter = await ensureMobileSharedAdapterConnected();
  adapter.publish(topicName, messageType, message);
  appendRosLog("info", `消息下发成功: ${topicName}`);
}

function nextRequestPlanId() {
  const requestPlanId = `mobile_test_${String(navGoalSequence.value).padStart(3, "0")}`;
  navGoalSequence.value += 1;
  return requestPlanId;
}

function enterInitialPoseMode() {
  navInteractionMode.value = navInteractionMode.value === "initialpose" ? "none" : "initialpose";
  navControlMessage.value = navInteractionMode.value === "initialpose" ? "已进入初始化定位模式，请在主视图中按下并拖动方向。" : "已退出初始化定位模式。";
}

function enterNavGoalMode() {
  navInteractionMode.value = navInteractionMode.value === "navgoal" ? "none" : "navgoal";
  navControlMessage.value = navInteractionMode.value === "navgoal" ? "已进入导航目标模式，请在主视图中按下并拖动方向。" : "已退出导航目标模式。";
}

async function publishInitialPose(x: number, y: number, yaw: number) {
  await publishRosMessage("/initialpose", "geometry_msgs/msg/PoseWithCovarianceStamped", {
    header: {
      frame_id: mobileRosAppState.connection.fixedFrame || "map",
    },
    pose: {
      pose: {
        position: { x, y, z: 0 },
        orientation: yawToQuaternion(yaw),
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
        frame_id: mobileRosAppState.connection.fixedFrame || "map",
        x,
        y,
        yaw,
      },
      context: {
        source: "mobile",
        scene: "ros_nav_app",
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
    await publishRosMessage("/nav2_goal_control", "std_msgs/msg/String", { data: command });
    navControlMessage.value = `已发送导航控制: ${command}`;
  } catch (error) {
    navControlMessage.value = `控制下发失败: ${(error as Error).message}`;
  } finally {
    navControlLoading.value = false;
  }
}

function formatRuntimeValue(value: unknown) {
  if (Array.isArray(value)) {
    return value.length > 12 ? `${JSON.stringify(value.slice(0, 12))} ... (${value.length})` : JSON.stringify(value);
  }
  if (typeof value === "object" && value !== null) {
    return JSON.stringify(value);
  }
  return String(value);
}

function toggleRuntimeGroup(groupKey: string) {
  runtimeGroupCollapsed.value = {
    ...runtimeGroupCollapsed.value,
    [groupKey]: !isRuntimeGroupCollapsed(groupKey),
  };
}

function isRuntimeGroupCollapsed(groupKey: string) {
  return runtimeGroupCollapsed.value[groupKey] !== false;
}

function toggleRuntimeNode(groupKey: string, nodeName: string) {
  const key = `${groupKey}:${nodeName}`;
  runtimeNodeCollapsed.value = {
    ...runtimeNodeCollapsed.value,
    [key]: !isRuntimeNodeCollapsed(groupKey, nodeName),
  };
}

function isRuntimeNodeCollapsed(groupKey: string, nodeName: string) {
  return runtimeNodeCollapsed.value[`${groupKey}:${nodeName}`] !== false;
}

function closeModalOverlay() {
  if (currentPage.value === "home" || currentPage.value === "config") {
    closeToMain();
  }
  exportSheetOpen.value = false;
  menuOpen.value = false;
}

async function exportViewerSnapshot() {
  const canvas = document.querySelector(".nav-viewer-canvas-host canvas") as HTMLCanvasElement | null;
  if (!canvas) {
    navControlMessage.value = "当前还没有可导出的主视图画面。";
    return;
  }
  const fileName = `ros-nav-snapshot-${Date.now()}.png`;
  const dataUrl = canvas.toDataURL("image/png");
  const anchor = document.createElement("a");
  anchor.href = dataUrl;
  anchor.download = fileName;
  anchor.click();
  exportSheetOpen.value = false;
  navControlMessage.value = `已导出快照: ${fileName}`;
}

watch(
  () => currentPage.value,
  (page) => {
    menuOpen.value = false;
    if (page === "config") {
      syncConnectionDraftFromState();
    }
    if (page === "topics" && mobileRosAppState.topicOptions.length === 0) {
      void refreshMobileTopics();
    }
    if (page === "runtime" && !mobileRosAppState.runtimeParams && mobileRosAppState.connection.url.trim()) {
      void refreshMobileRuntimeParams();
    }
  },
  { immediate: true }
);

watch(
  () => [
    mobileRosAppState.connection.provider,
    mobileRosAppState.connection.url,
    mobileRosAppState.connection.timeoutMs,
    viewerReconnectToken.value,
  ],
  () => {
    rebuildMobileSharedAdapter();
    void connectMobileStatusSubscriptions();
  },
  { immediate: true }
);

onMounted(() => {
  loadMobileRosAppState();
  syncConnectionDraftFromState();
  document.addEventListener("focusin", scrollFocusedFieldIntoView);
  visualViewportCleanup = installVisualViewportKeyboardSync();
  void nextTick(() => {
    updateLayerDrawerMetrics();
    if (!layerDrawerRef.value) {
      return;
    }
    layerDrawerResizeObserver = new ResizeObserver(() => updateLayerDrawerMetrics());
    layerDrawerResizeObserver.observe(layerDrawerRef.value);
  });
});

onBeforeUnmount(() => {
  document.removeEventListener("focusin", scrollFocusedFieldIntoView);
  teardownMobileStatusSubscriptions();
  mobileSharedAdapter?.disconnect();
  mobileSharedAdapter = null;
  layerDrawerResizeObserver?.disconnect();
  layerDrawerResizeObserver = null;
  visualViewportCleanup?.();
  visualViewportCleanup = null;
});
</script>

<template>
  <div class="ros-mobile-shell ros-mobile-landscape-shell">
    <article class="ros-mobile-app-canvas">
      <article class="ros-mobile-viewer-surface">
            <Nav3DViewer
              :provider="mobileRosAppState.connection.provider"
              :url="mobileRosAppState.connection.url"
              :timeout-ms="Number(mobileRosAppState.connection.timeoutMs || '8000')"
              :fixed-frame="mobileRosAppState.connection.fixedFrame || 'map'"
              :displays="mobileRosAppState.mainDisplays"
              :interaction-mode="navInteractionMode"
              :reconnect-token="viewerReconnectToken"
              @interaction-complete="handleNavViewerInteraction"
              @tf-frames-change="handleTfFramesChange"
              @ros-log="appendRosLog($event.level, `${$event.source}: ${$event.message}`)"
            />

            <header class="ros-mobile-viewer-topbar">
              <div class="ros-mobile-hud-stack">
                <div class="ros-mobile-hud-strip">
                  <span class="ros-mobile-hud-pill" :class="connectionStateTone">
                    <i></i>
                    {{ connectionStateLabel }}
                  </span>
                  <span class="ros-mobile-hud-chip">{{ mobileRosAppState.connection.fixedFrame || "map" }} (Fixed Frame)</span>
                  <span class="ros-mobile-hud-chip">图层: {{ mobileRosAppState.mainDisplays.length }}</span>
                </div>
                <div class="ros-mobile-hud-strip ros-mobile-hud-diagnostics">
                  <span class="ros-mobile-hud-chip tone-status" :class="`tone-${ndtHealthStatus.tone}`">
                    <b>NDT</b>
                    {{ ndtHealthStatus.label }}
                  </span>
                  <span class="ros-mobile-hud-chip tone-status" :class="`tone-${obstacleZoneStatus.tone}`">
                    <b>风险区</b>
                    {{ obstacleZoneStatus.label }}
                  </span>
                </div>
              </div>
              <button class="ros-mobile-feature-button" type="button" @click="menuOpen = !menuOpen">
                <span>功能</span>
                <span class="ros-mobile-feature-icon">☰</span>
              </button>
            </header>

            <aside v-if="menuOpen" class="ros-mobile-quick-menu">
              <button
                v-for="entry in menuEntries"
                :key="entry.key"
                class="ros-mobile-quick-menu-item"
                type="button"
                @click="openMenuEntry(entry)"
              >
                <span class="ros-mobile-quick-menu-icon">{{ entry.label.slice(0, 1) }}</span>
                <span>{{ entry.label }}</span>
              </button>
              <button class="ros-mobile-quick-menu-close" type="button" @click="menuOpen = false">×</button>
            </aside>

            <div class="ros-mobile-viewer-bottom">
              <div class="ros-mobile-viewer-mode-row">
                <button
                  class="ros-mobile-mode-chip"
                  :class="{ active: navInteractionMode === 'initialpose' }"
                  type="button"
                  :disabled="navControlLoading"
                  @click="enterInitialPoseMode"
                >
                  {{ navInteractionMode === "initialpose" ? "退出定位" : "初始化定位" }}
                </button>
                <button
                  class="ros-mobile-mode-chip"
                  :class="{ active: navInteractionMode === 'navgoal' }"
                  type="button"
                  :disabled="navControlLoading"
                  @click="enterNavGoalMode"
                >
                  {{ navInteractionMode === "navgoal" ? "退出导航" : "导航目标" }}
                </button>
                <button class="ros-mobile-mode-chip subtle" type="button" @click="openPage('topics')">话题</button>
                <button class="ros-mobile-mode-chip subtle" type="button" @click="layerDrawerOpen = !layerDrawerOpen">图层</button>
              </div>
            </div>

            <div class="ros-mobile-run-dock" :class="{ open: runDockOpen }">
              <button class="ros-mobile-run-dock-toggle" type="button" :disabled="navControlLoading" @click="runDockOpen = !runDockOpen">
                {{ runDockOpen ? "◀" : "▶" }}
              </button>
              <div v-if="runDockOpen" class="ros-mobile-run-dock-menu">
                <button class="ros-mobile-run-chip icon" type="button" title="继续" :disabled="navControlLoading" @click="sendNavControlCommand('resume')">▶</button>
                <button class="ros-mobile-run-chip icon" type="button" title="暂停" :disabled="navControlLoading" @click="sendNavControlCommand('pause')">⏸</button>
                <button class="ros-mobile-run-chip icon danger" type="button" title="取消" :disabled="navControlLoading" @click="sendNavControlCommand('cancel')">✕</button>
              </div>
            </div>

            <div v-if="currentPage === 'home'" class="ros-mobile-overlay-backdrop" @click="closeModalOverlay"></div>
            <section v-if="currentPage === 'home'" class="ros-mobile-module-overlay panel">
              <div class="ros-mobile-overlay-head">
                <div>
                  <div class="result-title">模块中心</div>
                </div>
                <button class="ros-mobile-close-btn" type="button" @click="closeToMain">×</button>
              </div>
              <div class="ros-mobile-module-grid landscape">
                <button class="ros-mobile-module-card" type="button" @click="openPage('config')">
                  <strong>连接配置</strong>
                  <span>设置 rosbridge、固定坐标系和超时。</span>
                </button>
                <button class="ros-mobile-module-card" type="button" @click="openPage('topics')">
                  <strong>话题浏览</strong>
                  <span>查看实时话题并加入主视图。</span>
                </button>
                <button class="ros-mobile-module-card" type="button" @click="openPage('runtime')">
                  <strong>运行参数</strong>
                  <span>读取 Nav2 / NDT 节点参数状态。</span>
                </button>
                <button class="ros-mobile-module-card" type="button" @click="layerDrawerOpen = true; closeToMain();">
                  <strong>图层管理</strong>
                  <span>调整主视图图层颜色、频率与透明度。</span>
                </button>
              </div>
              <aside class="ros-mobile-status-widget embedded" :class="{ open: statusPanelOpen }">
                <button class="ros-mobile-status-widget-toggle" type="button" @click="statusPanelOpen = !statusPanelOpen">
                  <span>{{ latestStatusTitle }}</span>
                  <strong>{{ statusPanelOpen ? "收起" : "展开" }}</strong>
                </button>
                <div v-if="statusPanelOpen" class="ros-mobile-status-widget-body">
                  <div class="ros-mobile-status-widget-message">{{ latestStatusMessage }}</div>
                </div>
              </aside>
            </section>

            <div v-if="currentPage === 'config' || exportSheetOpen" class="ros-mobile-overlay-backdrop" @click="closeModalOverlay"></div>
            <section v-if="currentPage === 'config'" class="ros-mobile-config-modal panel">
              <div class="ros-mobile-overlay-head">
                <div>
                  <div class="result-title">连接配置</div>
                  <div class="section-subtitle">以浮动配置窗覆盖主视图，调整完成后直接返回三维画面。</div>
                </div>
                <button class="ros-mobile-close-btn" type="button" @click="closeToMain">×</button>
              </div>
              <div class="grid-form ros-mobile-config-grid">
                <label class="field">
                  <span class="field-label">接入方式</span>
                  <select class="field-input" :value="connectionDraft.provider" @change="updateConnectionField('provider', ($event.target as HTMLSelectElement).value)">
                    <option value="rosbridge">rosbridge websocket</option>
                    <option value="mock">mock</option>
                  </select>
                </label>
                <label class="field">
                  <span class="field-label">Bridge 地址</span>
                  <input
                    class="field-input"
                    :value="connectionDraft.url"
                    placeholder="ws://10.10.15.64:9090"
                    @input="updateConnectionField('url', ($event.target as HTMLInputElement).value)"
                    @blur="void 0"
                    @keydown="handleTextFieldConfirm"
                  />
                </label>
                <label class="field">
                  <span class="field-label">Topic 查询服务</span>
                  <input
                    class="field-input"
                    :value="connectionDraft.rosapiService"
                    placeholder="/rosapi/topics_and_raw_types"
                    @input="updateConnectionField('rosapiService', ($event.target as HTMLInputElement).value)"
                    @blur="void 0"
                    @keydown="handleTextFieldConfirm"
                  />
                </label>
                <label class="field">
                  <span class="field-label">固定坐标系</span>
                  <input
                    class="field-input"
                    :value="connectionDraft.fixedFrame"
                    placeholder="map"
                    @input="updateConnectionField('fixedFrame', ($event.target as HTMLInputElement).value)"
                    @blur="void 0"
                    @keydown="handleTextFieldConfirm"
                  />
                </label>
                <label class="field">
                  <span class="field-label">连接超时 ms</span>
                  <input
                    class="field-input"
                    :value="connectionDraft.timeoutMs"
                    type="text"
                    inputmode="numeric"
                    placeholder="8000"
                    @input="updateConnectionField('timeoutMs', ($event.target as HTMLInputElement).value)"
                    @blur="commitConnectionDraftField('timeoutMs')"
                    @keydown="handleTextFieldConfirm"
                  />
                </label>
              </div>
              <div class="ros-mobile-modal-foot">
                <div class="ros-mobile-foot-meta">
                  <span>连接状态: {{ connectionStateLabel }}</span>
                  <span>图层: {{ mobileRosAppState.mainDisplays.length }}</span>
                </div>
                <div class="actions">
                  <button class="secondary-btn" type="button" :disabled="mobileRosAppState.inspectLoading" @click="inspectMobileRosConnection">
                    {{ mobileRosAppState.inspectLoading ? "检测中..." : "测试连接" }}
                  </button>
                  <button class="primary-btn" type="button" @click="persistConnectionConfig">应用并返回</button>
                </div>
              </div>
              <aside class="ros-mobile-status-widget embedded" :class="{ open: statusPanelOpen }">
                <button class="ros-mobile-status-widget-toggle" type="button" @click="statusPanelOpen = !statusPanelOpen">
                  <span>{{ latestStatusTitle }}</span>
                  <strong>{{ statusPanelOpen ? "收起" : "展开" }}</strong>
                </button>
                <div v-if="statusPanelOpen" class="ros-mobile-status-widget-body">
                  <div class="ros-mobile-status-widget-message">{{ latestStatusMessage }}</div>
                </div>
              </aside>
            </section>

            <section v-if="currentPage === 'topics'" class="ros-mobile-side-sheet topics">
              <div class="ros-mobile-overlay-head compact">
                <div>
                  <div class="result-title">话题浏览</div>
                  <div class="section-subtitle">侧边层保持主视图可见，浏览后可直接加入图层。</div>
                </div>
                <button class="ros-mobile-close-btn" type="button" @click="closeToMain">×</button>
              </div>
              <div class="ros-mobile-side-sheet-body topics">
                <section class="ros-mobile-topic-browser">
                  <div class="ros-mobile-topic-toolbar">
                    <input v-model="topicQuery" class="field-input" placeholder="搜索话题名、类型或说明" />
                    <button class="secondary-btn" type="button" :disabled="mobileRosAppState.topicsLoading" @click="refreshMobileTopics">
                      {{ mobileRosAppState.topicsLoading ? "刷新中..." : "刷新" }}
                    </button>
                  </div>
                  <div class="section-subtitle nav-topic-feedback">{{ mobileRosAppState.topicsMessage || "直接从 rosapi 读取实时话题，支持加入主视图。" }}</div>
                  <div class="ros-mobile-topic-scroll">
                    <div v-for="topic in filteredTopicOptions" :key="topic.key" class="ros-mobile-topic-list-item">
                      <div class="ros-mobile-topic-list-main">
                        <strong>{{ topic.key }}</strong>
                        <span>{{ topic.type || "未知类型" }}</span>
                      </div>
                      <div class="ros-mobile-topic-list-actions">
                        <button class="secondary-btn" type="button" @click="openTopicDetail(topic.key)">预览</button>
                        <button class="primary-btn" type="button" :disabled="hasMobileMainDisplay(topic.key)" @click="addTopicToMobileMainView(topic)">
                          {{ hasMobileMainDisplay(topic.key) ? "已添加" : "加入主视图" }}
                        </button>
                      </div>
                    </div>
                  </div>
                </section>

                <section class="ros-mobile-topic-preview panel">
                  <template v-if="selectedTopicOption">
                    <div class="ros-mobile-preview-head">
                      <div>
                        <div class="result-title">{{ selectedTopicOption.key }}</div>
                        <div class="section-subtitle">{{ selectedTopicOption.note }}</div>
                      </div>
                      <button class="secondary-btn" type="button" @click="backToTopicList">返回列表</button>
                    </div>
                    <NavTopicPanelList
                      :provider="mobileRosAppState.connection.provider"
                      :url="mobileRosAppState.connection.url"
                      :timeout-ms="Number(mobileRosAppState.connection.timeoutMs || '8000')"
                      :panels="detailPanels"
                      :allow-recording="false"
                      :allow-remove="false"
                      @toggle="() => undefined"
                      @remove="() => undefined"
                      @update-config="() => undefined"
                      @recording-saved="() => undefined"
                      @ros-log="appendRosLog($event.level, `${$event.source}: ${$event.message}`)"
                    />
                  </template>
                  <template v-else>
                    <div class="result-title">智能预览</div>
                    <div class="section-subtitle">从左侧列表中选择话题，即可在这里查看内容和解析结果。</div>
                  </template>
                </section>
              </div>
              <aside class="ros-mobile-status-widget embedded" :class="{ open: statusPanelOpen }">
                <button class="ros-mobile-status-widget-toggle" type="button" @click="statusPanelOpen = !statusPanelOpen">
                  <span>{{ latestStatusTitle }}</span>
                  <strong>{{ statusPanelOpen ? "收起" : "展开" }}</strong>
                </button>
                <div v-if="statusPanelOpen" class="ros-mobile-status-widget-body">
                  <div class="ros-mobile-status-widget-message">{{ latestStatusMessage }}</div>
                </div>
              </aside>
            </section>

            <section v-if="currentPage === 'runtime'" class="ros-mobile-side-sheet runtime">
              <div class="ros-mobile-overlay-head compact">
                <div>
                  <div class="result-title">运行参数</div>
                  <div class="section-subtitle">参数窗口作为侧边层读取 Nav2 / NDT 运行时状态。</div>
                </div>
                <div class="ros-mobile-top-actions">
                  <button class="secondary-btn" type="button" :disabled="mobileRosAppState.inspectLoading" @click="inspectMobileRosConnection">
                    {{ mobileRosAppState.inspectLoading ? "检测中..." : "检测连接" }}
                  </button>
                  <button class="primary-btn" type="button" :disabled="mobileRosAppState.runtimeLoading" @click="refreshMobileRuntimeParams">
                    {{ mobileRosAppState.runtimeLoading ? "刷新中..." : "刷新参数" }}
                  </button>
                  <button class="ros-mobile-close-btn" type="button" @click="closeToMain">×</button>
                </div>
              </div>
              <div class="ros-mobile-side-sheet-scroll">
                <div class="section-subtitle nav-topic-feedback">{{ mobileRosAppState.runtimeMessage || "点击刷新后显示当前机器人运行时参数。" }}</div>
                <section v-for="group in mobileRosAppState.runtimeParams?.groups || []" :key="group.key" class="nav-runtime-group">
                  <div class="nav-runtime-group-head">
                    <button class="nav-runtime-group-toggle" type="button" @click="toggleRuntimeGroup(group.key)">
                      <span class="collapse-trigger-label">
                        <span class="collapse-caret" :class="{ expanded: !isRuntimeGroupCollapsed(group.key) }">▸</span>
                        <span class="result-title">{{ group.label }}</span>
                      </span>
                    </button>
                  </div>
                  <template v-if="!isRuntimeGroupCollapsed(group.key)">
                    <div v-for="section in group.sections" :key="`${group.key}-${section.title}`" class="nav-runtime-section">
                      <div class="nav-runtime-section-title">{{ section.title }}</div>
                      <div v-for="node in section.nodes" :key="node.node" class="nav-runtime-node">
                        <div class="nav-runtime-node-head">
                          <button class="nav-runtime-node-toggle" type="button" @click="toggleRuntimeNode(group.key, node.node)">
                            <span class="collapse-trigger-label">
                              <span class="collapse-caret" :class="{ expanded: !isRuntimeNodeCollapsed(group.key, node.node) }">▸</span>
                              <strong>{{ node.node }}</strong>
                            </span>
                          </button>
                          <span v-if="node.error" class="nav-runtime-node-error">{{ node.error }}</span>
                          <span v-else class="nav-runtime-node-count">{{ Object.keys(node.params || {}).length }} 个参数</span>
                        </div>
                        <div v-if="!isRuntimeNodeCollapsed(group.key, node.node) && !node.error && Object.keys(node.params || {}).length" class="nav-runtime-param-grid">
                          <div v-for="(value, key) in node.params" :key="`${node.node}-${key}`" class="nav-runtime-param-item">
                            <span class="kv-key">{{ key }}</span>
                            <span class="kv-value">{{ formatRuntimeValue(value) }}</span>
                          </div>
                        </div>
                      </div>
                    </div>
                  </template>
                </section>
                <article v-if="mobileRosAppState.runtimeParams?.failed_nodes?.length" class="panel">
                  <div class="result-title">失败节点</div>
                  <pre class="logs">{{ mobileRosAppState.runtimeParams.failed_nodes.join('\n') }}</pre>
                </article>
              </div>
              <aside class="ros-mobile-status-widget embedded" :class="{ open: statusPanelOpen }">
                <button class="ros-mobile-status-widget-toggle" type="button" @click="statusPanelOpen = !statusPanelOpen">
                  <span>{{ latestStatusTitle }}</span>
                  <strong>{{ statusPanelOpen ? "收起" : "展开" }}</strong>
                </button>
                <div v-if="statusPanelOpen" class="ros-mobile-status-widget-body">
                  <div class="ros-mobile-status-widget-message">{{ latestStatusMessage }}</div>
                </div>
              </aside>
            </section>

            <section ref="layerDrawerRef" class="ros-mobile-bottom-drawer" :class="{ open: layerDrawerOpen }" :style="layerDrawerStyle">
              <button
                class="ros-mobile-drawer-handle"
                type="button"
                @click="onLayerDrawerHandleClick"
                @pointerdown="onLayerDrawerPointerDown"
                @pointermove="onLayerDrawerPointerMove"
                @pointerup="onLayerDrawerPointerUp"
                @pointercancel="onLayerDrawerPointerCancel"
              >
                <span></span>
                <strong>图层管理</strong>
              </button>
              <div class="ros-mobile-bottom-drawer-body">
                <div v-if="mobileRosAppState.mainDisplays.length === 0" class="section-empty">当前没有主视图图层，请先从话题浏览添加。</div>
                <div v-else class="nav-display-strip ros-mobile-layer-strip">
                  <div v-for="display in mobileRosAppState.mainDisplays" :key="display.topic" class="nav-display-chip">
                    <div class="nav-display-chip-main">
                      <strong>{{ display.label }}</strong>
                      <span>{{ display.messageType }}</span>
                    </div>
                    <div class="nav-display-config-row">
                      <label class="nav-display-config-item">
                        <span class="kv-key">颜色</span>
                        <input class="nav-display-color-input" type="color" :value="display.color || '#ddd4c6'" @input="updateMainDisplayColor(display.topic, ($event.target as HTMLInputElement).value)" />
                      </label>
                      <label v-if="display.kind === 'pointcloud'" class="nav-display-config-item">
                        <span class="kv-key">点大小</span>
                        <input
                          class="field-input nav-pointcloud-input"
                          type="text"
                          inputmode="decimal"
                          :value="layerInputValue(display.topic, 'pointSize', String(display.pointSize || 0.08))"
                          @focus="updateLayerDraft(display.topic, 'pointSize', layerInputValue(display.topic, 'pointSize', String(display.pointSize || 0.08)))"
                          @input="updateLayerDraft(display.topic, 'pointSize', ($event.target as HTMLInputElement).value)"
                          @blur="commitLayerNumberInput(display.topic, 'pointSize', ($event.target as HTMLInputElement).value)"
                          @keydown="handleTextFieldConfirm"
                        />
                      </label>
                      <label v-if="display.kind === 'pointcloud'" class="nav-display-config-item">
                        <span class="kv-key">Hz 限制</span>
                        <input
                          class="field-input nav-pointcloud-input"
                          type="text"
                          inputmode="numeric"
                          :value="layerInputValue(display.topic, 'hzLimit', String(display.hzLimit || 0))"
                          @focus="updateLayerDraft(display.topic, 'hzLimit', layerInputValue(display.topic, 'hzLimit', String(display.hzLimit || 0)))"
                          @input="updateLayerDraft(display.topic, 'hzLimit', ($event.target as HTMLInputElement).value)"
                          @blur="commitLayerNumberInput(display.topic, 'hzLimit', ($event.target as HTMLInputElement).value)"
                          @keydown="handleTextFieldConfirm"
                        />
                      </label>
                      <label v-if="display.kind === 'map'" class="nav-display-config-item">
                        <span class="kv-key">透明度</span>
                        <input
                          class="field-input nav-pointcloud-input"
                          type="text"
                          inputmode="decimal"
                          :value="layerInputValue(display.topic, 'mapOpacity', String(display.mapOpacity || 0.55))"
                          @focus="updateLayerDraft(display.topic, 'mapOpacity', layerInputValue(display.topic, 'mapOpacity', String(display.mapOpacity || 0.55)))"
                          @input="updateLayerDraft(display.topic, 'mapOpacity', ($event.target as HTMLInputElement).value)"
                          @blur="commitLayerNumberInput(display.topic, 'mapOpacity', ($event.target as HTMLInputElement).value)"
                          @keydown="handleTextFieldConfirm"
                        />
                      </label>
                      <template v-if="display.kind === 'tf'">
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
                            class="field-input nav-pointcloud-input"
                            type="text"
                            inputmode="decimal"
                            :value="layerInputValue(display.topic, 'tfLabelSize', String(display.tfLabelSize ?? 0.5))"
                            @focus="updateLayerDraft(display.topic, 'tfLabelSize', layerInputValue(display.topic, 'tfLabelSize', String(display.tfLabelSize ?? 0.5)))"
                            @input="updateLayerDraft(display.topic, 'tfLabelSize', ($event.target as HTMLInputElement).value)"
                            @blur="commitLayerNumberInput(display.topic, 'tfLabelSize', ($event.target as HTMLInputElement).value)"
                            @keydown="handleTextFieldConfirm"
                          />
                        </label>
                      </template>
                    </div>
                    <div v-if="display.kind === 'tf'" class="nav-tf-frame-filter ros-mobile-tf-frame-filter">
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
                    <button class="section-card-action danger" type="button" @click="removeMainDisplay(display.topic)">移除</button>
                  </div>
                </div>
              </div>
            </section>

            <section v-if="exportSheetOpen" class="ros-mobile-export-modal panel">
              <div class="ros-mobile-overlay-head">
                <div>
                  <div class="result-title">快照导出</div>
                  <div class="section-subtitle">直接导出当前三维主视图画面，用于联调留档或现场记录。</div>
                </div>
                <button class="ros-mobile-close-btn" type="button" @click="exportSheetOpen = false">×</button>
              </div>
              <div class="ros-mobile-export-grid">
                <div class="stat-chip">
                  <span class="stat-chip-label">Bridge</span>
                  <strong>{{ mobileRosAppState.connection.url || "未配置" }}</strong>
                </div>
                <div class="stat-chip">
                  <span class="stat-chip-label">Fixed Frame</span>
                  <strong>{{ mobileRosAppState.connection.fixedFrame || "map" }}</strong>
                </div>
                <div class="stat-chip">
                  <span class="stat-chip-label">当前图层</span>
                  <strong>{{ mobileRosAppState.mainDisplays.length }}</strong>
                </div>
              </div>
              <div class="actions">
                <button class="secondary-btn" type="button" @click="exportSheetOpen = false">取消</button>
                <button class="primary-btn" type="button" @click="exportViewerSnapshot">导出 PNG</button>
              </div>
              <aside class="ros-mobile-status-widget embedded" :class="{ open: statusPanelOpen }">
                <button class="ros-mobile-status-widget-toggle" type="button" @click="statusPanelOpen = !statusPanelOpen">
                  <span>{{ latestStatusTitle }}</span>
                  <strong>{{ statusPanelOpen ? "收起" : "展开" }}</strong>
                </button>
                <div v-if="statusPanelOpen" class="ros-mobile-status-widget-body">
                  <div class="ros-mobile-status-widget-message">{{ latestStatusMessage }}</div>
                </div>
              </aside>
            </section>
      </article>
    </article>
  </div>
</template>
