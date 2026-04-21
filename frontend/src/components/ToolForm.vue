<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, reactive, watch } from "vue";

import { browsePath, fetchMtslashCaptcha, fetchPcdTilePreview, loginMtslash, openLocalPath } from "../api/client";
import type { BrowseDialogPayload, ToolDefinition } from "../types";

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
let costmapTimer: number | undefined;

watch(
  () => props.tool,
  (tool) => {
    Object.keys(formValues).forEach((key) => delete formValues[key]);
    tool.fields.forEach((field) => {
      formValues[field.key] = field.value ?? "";
    });
    tilePreview.value = "";
    mtslashCaptchaImage.value = "";
    mtslashLoginMessage.value = "";
    mtslashLoggedIn.value = false;
    stopCostmapPlayback();
    costmapFrameIndex.value = 0;
  },
  { immediate: true }
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
  emit("run", { ...formValues });
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

function fieldKind(fieldKey: string) {
  if (fieldKey === "login_session_id") {
    return "hidden";
  }
  if (fieldKey === "login_password") {
    return "password";
  }
  if (props.tool.key === "pcd_tile" && fieldKey === "format") {
    return "select-format";
  }
  if (fieldKey === "zip_output" || fieldKey === "export_gif" || fieldKey === "export_png" || fieldKey === "show_lethal" || fieldKey === "show_footprint" || fieldKey === "only_thread_author") {
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
  } catch (error) {
    mtslashLoggedIn.value = false;
    mtslashLoginMessage.value = `登录失败: ${(error as Error).message}`;
  } finally {
    mtslashLoginLoading.value = false;
  }
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
          <template v-if="tool.key === 'pcd_tile'">
            <button class="secondary-btn" type="button" @click="previewTile">预扫描</button>
            <button class="secondary-btn" type="button" @click="openOutputDir">打开输出目录</button>
            <button class="secondary-btn" type="button" @click="emit('clearLogs')">清空日志</button>
          </template>
          <template v-else-if="tool.key === 'costmap'">
            <button class="secondary-btn" type="button" @click="openOutputDir">打开导出目录</button>
            <button class="secondary-btn" type="button" @click="emit('clearLogs')">清空日志</button>
          </template>
          <template v-else-if="tool.key === 'mtslash_export'">
            <button class="secondary-btn" type="button" :disabled="mtslashCaptchaLoading" @click="fetchCaptcha">
              {{ mtslashCaptchaLoading ? "获取中..." : "获取验证码" }}
            </button>
            <button class="secondary-btn" type="button" :disabled="mtslashLoginLoading" @click="loginMtslashSession">
              {{ mtslashLoginLoading ? "登录中..." : "登录" }}
            </button>
            <button class="secondary-btn" type="button" @click="openOutputDir">打开输出目录</button>
            <button class="secondary-btn" type="button" @click="emit('clearLogs')">清空日志</button>
          </template>
        </div>
      </section>

      <template v-if="tool.key === 'network_scan'">
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

      <template v-else-if="tool.key === 'mtslash_export'">
        <section class="panel">
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
