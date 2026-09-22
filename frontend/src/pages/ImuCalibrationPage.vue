<!-- 功能说明：IMU 离线 Allan 标定页面，负责 db3 选择、topic 检查、曲线展示和导出预览。 -->
<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";
import PlatformLauncher from "../components/PlatformLauncher.vue";
import {
  analyzeImuCalibrationBag,
  browsePath,
  inspectImuCalibrationBag,
  type ImuCalibrationAnalyzeResponse,
  type ImuCalibrationInspectResponse,
  type ImuCalibrationTopicInfo,
} from "../api/client";
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

const values = reactive<Record<string, string>>({});
const inspecting = ref(false);
const analyzing = ref(false);
const inspectResult = ref<ImuCalibrationInspectResponse | null>(null);
const analyzeResult = ref<ImuCalibrationAnalyzeResponse | null>(null);
const message = ref("选择 rosbag2 db3 后先检查 topic，再运行 Allan 标定。");
const activeGroup = ref<"gyro" | "accel">("gyro");

watch(
  () => props.tool,
  (tool) => {
    Object.keys(values).forEach((key) => delete values[key]);
    tool.fields.forEach((field) => {
      values[field.key] = field.value ?? "";
    });
    inspectResult.value = null;
    analyzeResult.value = null;
    message.value = tool.description;
  },
  { immediate: true },
);

const supportedTopics = computed(() =>
  (inspectResult.value?.topics ?? []).filter((topic) => topic.supported),
);
const activeAllanGroup = computed(
  () => analyzeResult.value?.allan?.[activeGroup.value] ?? null,
);
const chartSeries = computed(() => {
  const group = activeAllanGroup.value;
  if (!group) return [];
  return [
    { axis: "x", color: "#2f8cff", points: group.series.x },
    { axis: "y", color: "#6fa86f", points: group.series.y },
    { axis: "z", color: "#df9144", points: group.series.z },
  ];
});
const chartBounds = computed(() => {
  const points = chartSeries.value.flatMap((series) => series.points);
  if (!points.length) {
    return { minTau: 0.01, maxTau: 1, minAdev: 0.001, maxAdev: 1 };
  }
  const taus = points.map((point) => point.tau).filter((value) => value > 0);
  const adevs = points.map((point) => point.adev).filter((value) => value > 0);
  return {
    minTau: Math.min(...taus),
    maxTau: Math.max(...taus),
    minAdev: Math.min(...adevs),
    maxAdev: Math.max(...adevs),
  };
});
const exportYaml = computed(() => {
  const result = analyzeResult.value;
  if (!result) return "等待标定结果。";
  return [
    "imu_calibration:",
    `  bag: "${result.bag_path}"`,
    `  topic: "${result.topic.name}"`,
    `  sample_hz: ${formatNumber(result.sample.sample_hz, 4)}`,
    "  gyro:",
    ...axisYaml(result.allan.gyro.estimates, "    "),
    "  accel:",
    ...axisYaml(result.allan.accel.estimates, "    "),
  ].join("\n");
});

function axisYaml(
  estimates: ImuCalibrationAnalyzeResponse["allan"]["gyro"]["estimates"],
  indent: string,
) {
  return (["x", "y", "z"] as const).flatMap((axis) => [
    `${indent}${axis}:`,
    `${indent}  noise_density: ${formatNumber(estimates[axis].noise_density, 8)}`,
    `${indent}  random_walk: ${formatNumber(estimates[axis].random_walk, 8)}`,
    `${indent}  bias_instability: ${formatNumber(estimates[axis].bias_instability, 8)}`,
  ]);
}

function formatNumber(value: number | undefined, digits = 3) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "-";
  if (Math.abs(value) >= 1000 || (Math.abs(value) > 0 && Math.abs(value) < 0.001)) {
    return value.toExponential(3);
  }
  return value.toFixed(digits);
}

function formatDuration(seconds: number) {
  if (!Number.isFinite(seconds)) return "-";
  if (seconds >= 3600) return `${formatNumber(seconds / 3600, 2)} h`;
  if (seconds >= 60) return `${formatNumber(seconds / 60, 2)} min`;
  return `${formatNumber(seconds, 2)} s`;
}

function chartPath(points: { tau: number; adev: number }[]) {
  const { minTau, maxTau, minAdev, maxAdev } = chartBounds.value;
  const logMinTau = Math.log10(Math.max(minTau, 1e-9));
  const logMaxTau = Math.log10(Math.max(maxTau, minTau * 1.01));
  const logMinAdev = Math.log10(Math.max(minAdev, 1e-12));
  const logMaxAdev = Math.log10(Math.max(maxAdev, minAdev * 1.01));
  return points
    .filter((point) => point.tau > 0 && point.adev > 0)
    .map((point) => {
      const x = ((Math.log10(point.tau) - logMinTau) / (logMaxTau - logMinTau)) * 100;
      const y = 44 - ((Math.log10(point.adev) - logMinAdev) / (logMaxAdev - logMinAdev)) * 40;
      return `${x.toFixed(2)},${Math.max(4, Math.min(44, y)).toFixed(2)}`;
    })
    .join(" ");
}

async function browseBag() {
  const path = await browsePath({
    mode: "open_file",
    title: "选择 rosbag2 db3",
    initial_path: values.bag_path || "",
  });
  if (path) values.bag_path = path;
}

async function inspectBag() {
  if (!values.bag_path?.trim()) {
    message.value = "请先选择 db3 文件。";
    return;
  }
  inspecting.value = true;
  try {
    inspectResult.value = await inspectImuCalibrationBag(values.bag_path.trim());
    const firstTopic = inspectResult.value.topics.find((topic) => topic.supported);
    if (firstTopic) values.topic = firstTopic.name;
    message.value = inspectResult.value.message;
  } catch (error) {
    inspectResult.value = null;
    message.value = (error as Error).message;
  } finally {
    inspecting.value = false;
  }
}

async function analyzeBag() {
  if (!values.bag_path?.trim()) {
    message.value = "请先选择 db3 文件。";
    return;
  }
  analyzing.value = true;
  try {
    analyzeResult.value = await analyzeImuCalibrationBag({ ...values });
    message.value = analyzeResult.value.message;
    emit("run", { ...values });
  } catch (error) {
    analyzeResult.value = null;
    message.value = (error as Error).message;
  } finally {
    analyzing.value = false;
  }
}

function chooseTopic(topic: ImuCalibrationTopicInfo) {
  if (topic.supported) values.topic = topic.name;
}
</script>

<template>
  <main class="imu-page">
    <header class="platform-topbar">
      <PlatformLauncher />
      <button class="icon-button" type="button" aria-label="清空日志" @click="emit('clearLogs')">⌫</button>
    </header>

    <section class="imu-hero">
      <div>
        <h1>IMU 标定</h1>
        <p>读取 rosbag2 db3，离线计算 Allan deviation、噪声密度、随机游走和 bias instability。</p>
      </div>
      <div class="imu-status glass-panel">
        <span>{{ analyzing || props.loading ? "分析中" : analyzeResult ? "已完成" : "待标定" }}</span>
        <strong>{{ analyzeResult ? formatNumber(analyzeResult.sample.sample_hz, 2) : "--" }} Hz</strong>
      </div>
    </section>

    <section class="imu-grid">
      <article class="glass-panel imu-config">
        <div class="section-title">输入数据</div>
        <label class="field wide">
          <span>rosbag2 db3</span>
          <div class="field-row">
            <input v-model="values.bag_path" class="field-input" placeholder="G:/path/imu_0.db3" />
            <button class="secondary-btn" type="button" @click="browseBag">选择</button>
          </div>
        </label>
        <label class="field">
          <span>IMU Topic</span>
          <input v-model="values.topic" class="field-input" placeholder="/livox/imu" />
        </label>
        <label class="field">
          <span>起始秒</span>
          <input v-model="values.start_s" class="field-input" />
        </label>
        <label class="field">
          <span>分析时长秒</span>
          <input v-model="values.duration_s" class="field-input" />
        </label>
        <label class="field">
          <span>抽样步长</span>
          <input v-model="values.stride" class="field-input" />
        </label>
        <label class="field">
          <span>最大样本数</span>
          <input v-model="values.max_samples" class="field-input" />
        </label>
        <label class="field">
          <span>最小 Tau 秒</span>
          <input v-model="values.min_tau_s" class="field-input" />
        </label>
        <label class="field">
          <span>最大 Tau 秒</span>
          <input v-model="values.max_tau_s" class="field-input" />
        </label>
        <div class="actions-row">
          <button class="secondary-btn" type="button" :disabled="inspecting" @click="inspectBag">{{ inspecting ? "检查中..." : "检查 DB3" }}</button>
          <button class="primary-btn" type="button" :disabled="analyzing" @click="analyzeBag">{{ analyzing ? "计算中..." : "开始标定" }}</button>
        </div>
        <p class="hint">{{ message }}</p>
      </article>

      <article class="glass-panel imu-topics">
        <div class="section-title">Topic 检查 <span>{{ supportedTopics.length }} 可用</span></div>
        <button
          v-for="topic in inspectResult?.topics || []"
          :key="topic.id"
          class="topic-card"
          :class="{ active: values.topic === topic.name, disabled: !topic.supported }"
          type="button"
          @click="chooseTopic(topic)"
        >
          <span><strong>{{ topic.name }}</strong><small>{{ topic.type }} · {{ topic.serialization_format }}</small></span>
          <span><strong>{{ topic.message_count.toLocaleString() }}</strong><small>{{ formatNumber(topic.frequency_hz, 2) }} Hz · {{ formatDuration(topic.duration_s) }}</small></span>
        </button>
        <div v-if="!inspectResult" class="empty-note">尚未检查 db3。</div>
      </article>

      <article class="glass-panel imu-chart">
        <div class="section-title">
          Allan Deviation
          <span class="segmented">
            <button :class="{ active: activeGroup === 'gyro' }" type="button" @click="activeGroup = 'gyro'">Gyro</button>
            <button :class="{ active: activeGroup === 'accel' }" type="button" @click="activeGroup = 'accel'">Accel</button>
          </span>
        </div>
        <svg viewBox="0 0 100 52" preserveAspectRatio="none">
          <line x1="0" y1="46" x2="100" y2="46" />
          <line x1="0" y1="4" x2="0" y2="46" />
          <polyline v-for="series in chartSeries" :key="series.axis" :points="chartPath(series.points)" fill="none" :stroke="series.color" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke" />
        </svg>
        <div class="legend"><span v-for="series in chartSeries" :key="series.axis"><i :style="{ backgroundColor: series.color }" />{{ series.axis.toUpperCase() }}</span></div>
        <div v-if="!analyzeResult" class="empty-note">运行标定后显示 Allan 曲线。</div>
      </article>

      <article class="glass-panel imu-result">
        <div class="section-title">标定结果</div>
        <template v-if="analyzeResult">
          <section v-for="groupKey in ['gyro', 'accel']" :key="groupKey" class="result-card">
            <strong>{{ groupKey === 'gyro' ? 'Gyro rad/s' : 'Accel 原单位' }}</strong>
            <div v-for="axis in ['x', 'y', 'z']" :key="`${groupKey}-${axis}`" class="axis-row">
              <b>{{ axis.toUpperCase() }}</b>
              <span>ND {{ formatNumber(analyzeResult.allan[groupKey as 'gyro' | 'accel'].estimates[axis as 'x' | 'y' | 'z'].noise_density, 6) }}</span>
              <span>RW {{ formatNumber(analyzeResult.allan[groupKey as 'gyro' | 'accel'].estimates[axis as 'x' | 'y' | 'z'].random_walk, 6) }}</span>
              <span>BI {{ formatNumber(analyzeResult.allan[groupKey as 'gyro' | 'accel'].estimates[axis as 'x' | 'y' | 'z'].bias_instability, 6) }}</span>
            </div>
          </section>
        </template>
        <div v-else class="empty-note">暂无标定结果。</div>
      </article>

      <article class="glass-panel imu-export">
        <div class="section-title">导出预览</div>
        <pre>{{ exportYaml }}</pre>
      </article>
    </section>
  </main>
</template>

<style scoped>
.imu-page {
  min-height: 100vh;
  padding: 24px;
  color: #2f2f2f;
  background:
    linear-gradient(rgba(160, 150, 128, 0.12) 1px, transparent 1px),
    linear-gradient(90deg, rgba(160, 150, 128, 0.12) 1px, transparent 1px),
    #e5dfd1;
  background-size: 28px 28px;
}

.platform-topbar,
.imu-hero,
.actions-row,
.section-title,
.legend,
.axis-row {
  display: flex;
  align-items: center;
}

.platform-topbar,
.imu-hero {
  justify-content: space-between;
  gap: 18px;
}

.icon-button {
  width: 42px;
  height: 42px;
  border: 1px solid rgba(255, 255, 255, 0.7);
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.48);
}

.imu-hero {
  margin: 36px 0 22px;
}

.imu-hero h1 {
  margin: 0;
  font-size: 34px;
}

.imu-hero p,
.hint,
.empty-note,
.topic-card small {
  color: rgba(55, 55, 55, 0.62);
}

.glass-panel {
  border: 1px solid rgba(255, 255, 255, 0.68);
  border-radius: 22px;
  background: rgba(245, 241, 232, 0.54);
  box-shadow: 0 20px 60px rgba(120, 106, 80, 0.16);
  backdrop-filter: blur(18px);
}

.imu-status {
  min-width: 170px;
  padding: 16px 18px;
  display: grid;
  gap: 6px;
}

.imu-status strong {
  font-size: 24px;
}

.imu-grid {
  display: grid;
  grid-template-columns: repeat(12, minmax(0, 1fr));
  gap: 16px;
}

.imu-config,
.imu-chart {
  grid-column: span 7;
}

.imu-topics,
.imu-result,
.imu-export {
  grid-column: span 5;
}

.imu-config,
.imu-topics,
.imu-chart,
.imu-result,
.imu-export {
  padding: 18px;
}

.section-title {
  justify-content: space-between;
  margin-bottom: 14px;
  font-weight: 800;
}

.field {
  display: grid;
  gap: 6px;
  margin-bottom: 12px;
}

.field.wide {
  grid-column: span 2;
}

.field span {
  font-size: 12px;
  color: rgba(55, 55, 55, 0.62);
}

.field-row {
  display: flex;
  gap: 8px;
}

.field-input {
  width: 100%;
  border: 1px solid rgba(255, 255, 255, 0.72);
  border-radius: 14px;
  padding: 11px 12px;
  color: #2f2f2f;
  background: rgba(255, 255, 255, 0.52);
}

.imu-config {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  column-gap: 12px;
  align-content: start;
}

.imu-config .section-title,
.imu-config .actions-row,
.imu-config .hint {
  grid-column: 1 / -1;
}

.primary-btn,
.secondary-btn {
  border: 0;
  border-radius: 14px;
  padding: 11px 16px;
  font-weight: 800;
}

.primary-btn {
  color: white;
  background: #5f7f55;
}

.secondary-btn {
  color: #3e4639;
  background: rgba(255, 255, 255, 0.58);
}

.actions-row {
  gap: 10px;
  margin-top: 4px;
}

.topic-card {
  width: 100%;
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
  padding: 12px;
  border: 1px solid rgba(255, 255, 255, 0.68);
  border-radius: 16px;
  color: #2f2f2f;
  background: rgba(255, 255, 255, 0.38);
  text-align: left;
}

.topic-card span {
  display: grid;
  gap: 4px;
}

.topic-card.active {
  border-color: #df9144;
  background: rgba(223, 145, 68, 0.18);
}

.topic-card.disabled {
  opacity: 0.5;
}

.segmented {
  display: inline-flex;
  padding: 3px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.45);
}

.segmented button {
  border: 0;
  border-radius: 11px;
  padding: 7px 12px;
  background: transparent;
}

.segmented button.active {
  color: white;
  background: #5f7f55;
}

.imu-chart svg {
  width: 100%;
  height: 330px;
  overflow: visible;
}

.imu-chart line {
  stroke: rgba(90, 82, 64, 0.28);
  stroke-width: 1;
}

.legend {
  gap: 14px;
  font-size: 12px;
}

.legend span {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.legend i {
  width: 9px;
  height: 9px;
  border-radius: 999px;
}

.result-card {
  padding: 12px;
  margin-bottom: 12px;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.36);
}

.axis-row {
  display: grid;
  grid-template-columns: 28px repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin-top: 8px;
  font-size: 12px;
}

.axis-row span {
  color: rgba(55, 55, 55, 0.68);
}

.imu-export pre {
  min-height: 220px;
  margin: 0;
  white-space: pre-wrap;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  color: #334;
}

@media (max-width: 1000px) {
  .imu-config,
  .imu-chart,
  .imu-topics,
  .imu-result,
  .imu-export {
    grid-column: span 12;
  }
}
</style>
