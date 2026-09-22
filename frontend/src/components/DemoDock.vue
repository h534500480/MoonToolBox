<!-- 功能说明：复刻 platform 演示监控卡的折叠、暂停、录制、详情及拖拽操作。 -->
<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, computed } from "vue";
import {
  ChevronDown,
  ChevronUp,
  Pause,
  Play,
  X,
  Circle,
  GripVertical,
  ChevronsLeft,
  ChevronsRight,
} from "@lucide/vue";
import GlassDrawer from "./GlassDrawer.vue";
import { demoData, demoTopics, tickDemo } from "../platform/demo";
import { saveNavRecording } from "../api/client";
interface Card {
  topic: string;
  id: string;
  collapsed: boolean;
  paused: boolean;
  recording: boolean;
  data: any;
  history: number[];
  entries: string[];
  started: number;
}
const cards = ref<Card[]>([]),
  open = ref(true),
  detail = ref<string | null>(null),
  message = ref("");
let timer: number | undefined,
  dragging = "";
const selected = computed(() => cards.value.find((c) => c.id === detail.value));
function add(topic: string) {
  if (cards.value.some((c) => c.topic === topic)) return;
  cards.value.push({
    topic,
    id: topic,
    collapsed: false,
    paused: false,
    recording: false,
    data: demoData.values[topic],
    history: [],
    entries: [],
    started: 0,
  });
}
["/ndt_pose", "/score", "/manual_relocalization_status"].forEach(add);
onMounted(() => {
  tickDemo();
  timer = window.setInterval(() => {
    tickDemo();
    cards.value.forEach((c) => {
      if (!c.paused) {
        c.data = demoData.values[c.topic];
        c.history = [...(demoData.history[c.topic] || [])];
      }
      if (c.recording)
        c.entries.push(JSON.stringify({ stamp: Date.now(), data: c.data }));
    });
  }, 500);
});
onBeforeUnmount(() => clearInterval(timer));
function drop(index: number) {
  const source = cards.value.findIndex((c) => c.id === dragging);
  if (source < 0) return;
  cards.value.splice(index, 0, cards.value.splice(source, 1)[0]);
  dragging = "";
}
function line(values: number[]) {
  const min = Math.min(...values),
    max = Math.max(...values);
  return values
    .map(
      (v, i) =>
        `${(i * 100) / Math.max(1, values.length - 1)},${36 - ((v - min) / Math.max(0.01, max - min)) * 26}`,
    )
    .join(" ");
}
/** 演示录制在文件名和正文中明确标识，不模拟后端成功状态。 */
async function record(c: Card) {
  if (!c.recording) {
    c.recording = true;
    c.entries = [];
    c.started = Date.now();
    return;
  }
  c.recording = false;
  try {
    await saveNavRecording({
      panel_id: `demo-${c.id}`,
      started_at_ms: c.started,
      title: `演示 ${c.topic}`,
      topic: c.topic,
      message_type: demoTopics.find((t) => t.key === c.topic)?.type || "",
      started_at: new Date(c.started).toISOString(),
      stopped_at: new Date().toISOString(),
      duration_ms: Date.now() - c.started,
      entries: c.entries,
      metric_series: [],
    });
    message.value = "演示录制已保存";
  } catch (e) {
    message.value = `录制保存失败：${(e as Error).message}`;
  }
}
defineExpose({ add });
</script>
<template>
  <div class="demo-dock glass-panel" :class="{ collapsed: !open }">
    <header>
      <strong>话题监控</strong><span class="glass-chip">{{ cards.length }}</span
      ><button
        class="icon-button"
        :aria-label="open ? '收起监控' : '展开监控'"
        @click="open = !open"
      >
        <component :is="open ? ChevronsLeft : ChevronsRight" :size="14" />
      </button>
    </header>
    <template v-if="open"
      ><TransitionGroup name="list"
        ><article
          v-for="(card, index) in cards"
          :key="card.id"
          class="demo-topic glass-inner"
          draggable="true"
          @dragstart="dragging = card.id"
          @dragover.prevent
          @drop.prevent.stop="drop(index)"
          @dblclick="detail = card.id"
        >
          <header>
            <GripVertical :size="12" /><strong :title="card.topic">{{
              card.topic
            }}</strong
            ><i class="dot dot-ok" /><span class="card-hover-actions"
              ><button
                class="icon-button"
                :class="{ recording: card.recording }"
                aria-label="录制"
                @click.stop="record(card)"
              >
                <Circle :size="11" /></button
              ><button
                class="icon-button"
                :aria-label="card.paused ? '继续' : '暂停'"
                @click.stop="card.paused = !card.paused"
              >
                <component
                  :is="card.paused ? Play : Pause"
                  :size="11"
                /></button
              ><button
                class="icon-button"
                aria-label="折叠话题"
                @click.stop="card.collapsed = !card.collapsed"
              >
                <component
                  :is="card.collapsed ? ChevronDown : ChevronUp"
                  :size="12"
                /></button
              ><button
                class="icon-button"
                aria-label="移除话题"
                @click.stop="cards = cards.filter((c) => c.id !== card.id)"
              >
                <X :size="11" /></button
            ></span>
          </header>
          <div v-if="!card.collapsed" class="demo-topic-body">
            <div v-if="card.topic === '/ndt_pose'" class="pose-values">
              <span v-for="axis in ['x', 'y', 'z', 'yaw']" :key="axis"
                ><small>{{ axis }}</small
                ><b>{{ Number(card.data?.[axis] || 0).toFixed(3) }}</b></span
              >
            </div>
            <strong
              v-else-if="typeof card.data === 'number'"
              class="score-value"
              >{{ card.data.toFixed(3) }}</strong
            ><code v-else>{{
              card.data ? JSON.stringify(card.data) : "等待消息…"
            }}</code
            ><svg
              v-if="card.history.length && card.data"
              viewBox="0 0 100 48"
              preserveAspectRatio="none"
            >
              <polyline
                :points="line(card.history)"
                fill="none"
                :stroke="card.topic === '/ndt_pose' ? '#d98e4a' : '#7e9271'"
                stroke-width="1.4"
                vector-effect="non-scaling-stroke"
              /></svg
            ><small v-if="card.paused || card.recording">{{
              card.paused ? "已暂停" : "录制中 · 演示数据"
            }}</small>
          </div>
        </article></TransitionGroup
      ><small v-if="message">{{ message }}</small></template
    >
  </div>
  <GlassDrawer
    :open="!!selected"
    :title="selected?.topic || '话题详情'"
    @close="detail = null"
    ><template v-if="selected"
      ><p class="feedback">演示数据 · 2 Hz</p>
      <div class="button-row">
        <button @click="selected.paused = !selected.paused">
          {{ selected.paused ? "继续" : "暂停" }}</button
        ><button @click="record(selected)">
          {{ selected.recording ? "停止录制" : "开始录制" }}
        </button>
      </div>
      <pre>{{ JSON.stringify(selected.data, null, 2) }}</pre>
      <svg viewBox="0 0 100 48" width="100%">
        <polyline
          :points="line(selected.history)"
          fill="none"
          stroke="#7e9271"
          stroke-width="1"
        /></svg></template
  ></GlassDrawer>
</template>
