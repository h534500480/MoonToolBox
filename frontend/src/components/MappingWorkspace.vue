<!-- 功能说明：Super-LIO 建图工作台覆盖层，组织实时采集、离线录包、输入校验和地图产物的操作顺序。 -->
<script setup lang="ts">
import { computed, ref } from "vue";
import {
  CheckCircle2,
  CircleDot,
  FileArchive,
  FileOutput,
  FolderOpen,
  Gauge,
  Layers3,
  Pause,
  Play,
  Save,
  Settings2,
  Square,
  Upload,
} from "@lucide/vue";

defineProps<{ active: boolean }>();

type BuildSource = "live" | "bag";
type BuildStage = "ready" | "recording" | "paused" | "finished";
const source = ref<BuildSource>("live");
const stage = ref<BuildStage>("ready");
const selectedBag = ref("");
const outputName = ref("untitled_map");
const advancedOpen = ref(false);
const topicBindings = ref({
  lidar: "/livox/lidar",
  imu: "/livox/imu",
  tf: "/tf",
  staticTf: "/tf_static",
});
const stageText = computed(
  () =>
    ({
      ready: "等待开始",
      recording: source.value === "live" ? "正在采集" : "正在离线处理",
      paused: "已暂停",
      finished: "已结束，待导出",
    })[stage.value],
);
const actionText = computed(() => {
  if (stage.value === "recording") return "暂停";
  if (stage.value === "paused") return "继续";
  if (stage.value === "finished") return "开始新任务";
  return source.value === "live" ? "开始采集" : "开始处理";
});
function handlePrimaryAction() {
  if (stage.value === "recording") stage.value = "paused";
  else if (stage.value === "paused") stage.value = "recording";
  else stage.value = "recording";
}
function stopBuild() {
  if (stage.value === "recording" || stage.value === "paused") stage.value = "finished";
}
function chooseBag() {
  // 文件选择与后端 rosbag 解析尚未接入；保留明确入口避免把路径填写误当成已校验。
  selectedBag.value = "请选择 rosbag2 目录或 .db3 文件";
}
</script>

<template>
  <Transition name="workspace-fade">
    <section v-show="active" class="mapping-workspace" aria-label="建图工作台">
      <aside class="mapping-source-panel glass-strong">
        <header class="mapping-panel-header">
          <div><span>建图输入</span><strong>Super-LIO</strong></div>
          <span class="mapping-stage" :class="stage"><CircleDot :size="12" />{{ stageText }}</span>
        </header>

        <div class="mapping-source-switch" role="group" aria-label="建图来源">
          <button :class="{ active: source === 'live' }" @click="source = 'live'; stage = 'ready'">实时建图</button>
          <button :class="{ active: source === 'bag' }" @click="source = 'bag'; stage = 'ready'">录包建图</button>
        </div>

        <template v-if="source === 'live'">
          <div class="mapping-section-title"><span>数据流校验</span><small>开始前逐项确认</small></div>
          <div class="mapping-checks">
            <div><CheckCircle2 :size="15" /><span>LiDAR 点云</span><b>待验证</b></div>
            <div><CheckCircle2 :size="15" /><span>IMU 原始数据</span><b>待验证</b></div>
            <div><CheckCircle2 :size="15" /><span>LiDAR–IMU 外参</span><b>待验证</b></div>
            <div><CheckCircle2 :size="15" /><span>时间戳连续性</span><b>待验证</b></div>
          </div>
          <p class="mapping-helper">接入后将检查消息类型、频率、时间倒退和 TF 静态外参；任何一项异常都不应开始采集。</p>
        </template>
        <template v-else>
          <button class="mapping-bag-picker" type="button" @click="chooseBag"><Upload :size="16" /><span>{{ selectedBag || "选择 rosbag2 目录 / .db3" }}</span></button>
          <p class="mapping-helper">先解析 metadata.yaml，再选择 LiDAR、IMU、/tf 与 /tf_static。不要把仅有点云的录包直接送入 LIO。</p>
          <div class="mapping-bag-requirements"><FileArchive :size="15" /><span>需保留录包元数据、传感器外参与运行配置快照</span></div>
        </template>

        <details class="mapping-advanced" :open="advancedOpen" @toggle="advancedOpen = ($event.target as HTMLDetailsElement).open">
          <summary><Settings2 :size="14" />输入与运行参数</summary>
          <label>LiDAR Topic<input v-model="topicBindings.lidar" /></label>
          <label>IMU Topic<input v-model="topicBindings.imu" /></label>
          <label>动态 TF<input v-model="topicBindings.tf" /></label>
          <label>静态 TF<input v-model="topicBindings.staticTf" /></label>
          <label>输出地图名<input v-model="outputName" /></label>
        </details>
      </aside>

      <aside class="mapping-output-panel glass-strong">
        <header class="mapping-panel-header"><div><span>地图产物</span><strong>{{ outputName || "untitled_map" }}</strong></div><Layers3 :size="18" /></header>
        <div class="mapping-map-summary"><div class="mapping-map-orbit"><span /></div><p>三维主视图实时显示建图点云与轨迹</p><small>地图闭合后再执行裁剪、降采样或生成导航栅格</small></div>
        <div class="mapping-output-list">
          <div><FileOutput :size="15" /><span>全局点云</span><b>PCD / PLY</b></div>
          <div><Gauge :size="15" /><span>轨迹与关键帧</span><b>TUM / CSV</b></div>
          <div><Save :size="15" /><span>可复现配置</span><b>YAML + 元数据</b></div>
        </div>
        <div class="mapping-export-note"><FolderOpen :size="14" /><span>导出前将写入地图版本、传感器外参与录制来源。</span></div>
      </aside>

      <div class="mapping-control-bar glass-strong">
        <div><span>建图任务</span><strong>{{ source === 'live' ? '实时采集' : '离线录包处理' }}</strong></div>
        <button class="mapping-primary-action" type="button" @click="handlePrimaryAction"><Pause v-if="stage === 'recording'" :size="15" /><Play v-else :size="15" />{{ actionText }}</button>
        <button v-if="stage === 'recording' || stage === 'paused'" class="mapping-stop-action" type="button" @click="stopBuild"><Square :size="14" />结束并生成产物</button>
      </div>
    </section>
  </Transition>
</template>

<style scoped>
.mapping-workspace { position:absolute; inset:0; z-index:12; pointer-events:none; }
.mapping-source-panel,.mapping-output-panel,.mapping-control-bar { pointer-events:auto; }
.mapping-source-panel { position:absolute; left:16px; top:152px; bottom:88px; width:292px; padding:14px; overflow-y:auto; overscroll-behavior:contain; }
.mapping-output-panel { position:absolute; right:66px; top:76px; width:268px; padding:14px; }
.mapping-panel-header { display:flex; justify-content:space-between; align-items:flex-start; border-bottom:1px solid rgba(102,93,75,.13); padding-bottom:11px; }
.mapping-panel-header div { display:grid; gap:3px; }.mapping-panel-header span,.mapping-section-title small,.mapping-helper,.mapping-map-summary small { font-size:10px; color:#888179; }.mapping-panel-header strong { font-size:14px; color:#3f403e; }.mapping-stage { display:flex; align-items:center; gap:4px; font-size:10px; color:#8a796c; }.mapping-stage.recording { color:#c45846; }.mapping-stage.recording svg { fill:currentColor; }
.mapping-source-switch { display:grid; grid-template-columns:1fr 1fr; gap:4px; padding:12px 0; }.mapping-source-switch button { border:0; background:rgba(255,255,255,.34); padding:8px 5px; font-size:11px; }.mapping-source-switch button.active { background:#de9a66; color:#fff; box-shadow:0 3px 10px rgba(190,111,55,.24); }
.mapping-section-title { display:flex; justify-content:space-between; align-items:baseline; margin:4px 0 7px; }.mapping-section-title span { font-size:12px; font-weight:700; }.mapping-checks,.mapping-output-list { display:grid; gap:6px; }.mapping-checks div,.mapping-output-list div { display:flex; align-items:center; gap:7px; padding:7px; background:rgba(255,255,255,.27); border:1px solid rgba(255,255,255,.38); border-radius:8px; }.mapping-checks svg { color:#b5a99a; }.mapping-checks span,.mapping-output-list span { flex:1; font-size:10.5px; }.mapping-checks b,.mapping-output-list b { font-size:9px; font-weight:600; color:#8a7e72; }.mapping-helper { margin:10px 1px 0; line-height:1.55; }.mapping-bag-picker { display:flex; width:100%; align-items:center; gap:8px; margin-top:4px; padding:12px 9px; border:1px dashed rgba(170,125,81,.52); background:rgba(255,255,255,.24); text-align:left; }.mapping-bag-picker span { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:10.5px; }.mapping-bag-requirements,.mapping-export-note { display:flex; gap:7px; padding:9px 2px 0; color:#77716b; font-size:10px; line-height:1.45; }.mapping-advanced { margin-top:13px; border-top:1px solid rgba(102,93,75,.13); padding-top:9px; }.mapping-advanced summary { cursor:pointer; display:flex; align-items:center; gap:6px; font-size:11px; font-weight:700; }.mapping-advanced label { display:grid; gap:4px; margin-top:8px; font-size:9px; color:#7d766e; }.mapping-advanced input { border:1px solid rgba(130,116,96,.2); background:rgba(255,255,255,.42); padding:6px; font:10px Consolas,monospace; }
.mapping-map-summary { padding:13px 0 11px; text-align:center; }.mapping-map-summary p { margin:7px 0 3px; font-size:11px; font-weight:700; }.mapping-map-orbit { width:70px; height:48px; margin:auto; position:relative; border:1px solid rgba(173,121,76,.42); border-radius:50%; transform:rotate(-20deg); }.mapping-map-orbit:before,.mapping-map-orbit:after { content:""; position:absolute; border:1px solid rgba(173,121,76,.25); border-radius:50%; inset:12px -10px; }.mapping-map-orbit:after { transform:rotate(72deg); }.mapping-map-orbit span { position:absolute; width:7px; height:7px; left:30px; top:20px; background:#d77b52; border-radius:50%; box-shadow:0 0 0 5px rgba(215,123,82,.14); }.mapping-control-bar { position:absolute; bottom:24px; left:50%; transform:translateX(-50%); display:flex; align-items:center; gap:8px; padding:7px 8px 7px 13px; }.mapping-control-bar>div { display:grid; gap:2px; min-width:92px; }.mapping-control-bar span { font-size:9px; color:#888179; }.mapping-control-bar strong { font-size:11px; }.mapping-control-bar button { display:flex; align-items:center; gap:5px; border:0; padding:8px 10px; font-size:10.5px; }.mapping-primary-action { color:white; background:#d87951; }.mapping-stop-action { background:rgba(255,255,255,.5); }
@media (max-width:850px) { .mapping-source-panel { top:135px; bottom:78px; left:10px; width:250px; }.mapping-output-panel { display:none; }.mapping-control-bar { bottom:14px; max-width:calc(100vw - 24px); }.mapping-stop-action { display:none !important; } }
</style>
