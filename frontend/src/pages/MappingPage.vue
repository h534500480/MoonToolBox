<!-- 功能说明：复刻 platform 地图工具页布局，接通参数、预扫描、执行和真实输出预览。 -->
<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";
import {
  ArrowLeft,
  Map,
  Layers,
  Play,
  RotateCcw,
  Terminal,
  FileText,
  FolderOpen,
} from "@lucide/vue";
import PlatformLauncher from "../components/PlatformLauncher.vue";
import {
  browsePath,
  fetchPcdTilePreview,
  openLocalPath,
  buildBackendImageUrl,
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
const values = reactive<Record<string, string>>({}),
  feedback = ref(""),
  preview = ref("");
const map = computed(() => props.tool.key === "pcd_map");
const groups = computed(() =>
  map.value
    ? [
        { title: "输入输出", keys: ["input_pcd", "output_dir", "base_name"] },
        { title: "高度截取", keys: ["clip_min_z", "clip_max_z"] },
        { title: "可行走层", keys: ["walkable_min_z", "walkable_max_z"] },
        {
          title: "障碍层",
          keys: ["obstacle_min_z", "obstacle_max_z", "obstacle_inflate_radius"],
        },
        {
          title: "地图生成参数",
          keys: [
            "resolution",
            "ground_tolerance",
            "min_points_per_cell",
            "hole_fill_neighbors",
            "overlay_smooth_radius",
          ],
        },
      ]
    : [
        { title: "输入输出", keys: ["input_pcd", "output_dir"] },
        {
          title: "切片参数",
          keys: ["tile_size", "overlap", "format", "zip_output"],
        },
      ],
);
function reset() {
  for (const field of props.tool.fields) values[field.key] = field.value || "";
  feedback.value = "";
  preview.value = "";
}
watch(() => props.tool.key, reset, { immediate: true });
const field = (key: string) => props.tool.fields.find((f) => f.key === key)!;
const pathField = (key: string) => key === "input_pcd" || key === "output_dir";
async function browse(key: string) {
  try {
    const result = await browsePath({
      mode: key === "output_dir" ? "open_dir" : "open_file",
      title: field(key).label,
      initial_path: values[key],
    });
    if (result) values[key] = result;
  } catch (e) {
    feedback.value = `文件选择失败：${(e as Error).message}`;
  }
}
async function openOutput() {
  try {
    await openLocalPath(values.output_dir || "output_tiles");
  } catch (e) {
    feedback.value = `打开目录失败：${(e as Error).message}`;
  }
}
async function scan() {
  try {
    const p = await fetchPcdTilePreview(values.input_pcd, values.tile_size);
    preview.value = `点数 ${p.point_count}\nX ${p.xmin} ~ ${p.xmax}\nY ${p.ymin} ~ ${p.ymax}\nZ ${p.zmin} ~ ${p.zmax}\n预计切片 ${p.estimated_tiles}`;
  } catch (e) {
    feedback.value = `预扫描失败：${(e as Error).message}`;
  }
}
function submit() {
  feedback.value = "";
  if (!values.input_pcd?.trim()) {
    feedback.value = "请选择输入 PCD";
    return;
  }
  const numeric = props.tool.fields.filter(
    (f) =>
      !pathField(f.key) &&
      !["base_name", "format", "zip_output"].includes(f.key),
  );
  for (const f of numeric)
    if (values[f.key]?.trim() && !Number.isFinite(Number(values[f.key]))) {
      feedback.value = `${f.label}必须为有效数值`;
      return;
    }
  emit("run", { ...values });
}
</script>
<template>
  <main class="tool-page-bg">
    <div class="tool-page-grid" />
    <div class="mapping-content">
      <header class="mapping-top">
        <RouterLink to="/" class="glass icon-button" aria-label="返回测试平台"
          ><ArrowLeft :size="16" /></RouterLink
        ><PlatformLauncher compact /><span>ROBOTICS TEST PLATFORM</span>
      </header>
      <section class="glass-strong mapping-title">
        <span class="mapping-icon"
          ><component :is="map ? Map : Layers" :size="22"
        /></span>
        <div>
          <h1>{{ tool.title }}</h1>
          <p>{{ tool.subtitle }}</p>
        </div>
        <button class="primary-btn" :disabled="loading" @click="submit">
          <Play :size="14" />{{ loading ? "执行中…" : tool.primary_action }}
        </button>
        <p class="description">{{ tool.description }}</p>
      </section>
      <form @submit.prevent="submit">
        <section
          v-for="group in groups"
          :key="group.title"
          class="glass-strong mapping-group"
        >
          <h2>{{ group.title }}<i /></h2>
          <div class="mapping-fields">
            <label
              v-for="key in group.keys"
              :key="key"
              class="field"
              :class="{ wide: pathField(key) }"
              ><span>{{ field(key).label }}</span>
              <div class="field-row">
                <select
                  v-if="key === 'format' || key === 'zip_output'"
                  v-model="values[key]"
                  class="text-field"
                >
                  <option
                    v-for="value in key === 'format'
                      ? ['ascii', 'binary']
                      : ['false', 'true']"
                    :key="value"
                  >
                    {{ value }}
                  </option></select
                ><input
                  v-else
                  v-model="values[key]"
                  class="text-field"
                  :type="
                    pathField(key) || key === 'base_name' ? 'text' : 'number'
                  "
                  step="any"
                  :placeholder="field(key).placeholder"
                /><button
                  v-if="pathField(key)"
                  type="button"
                  @click="browse(key)"
                >
                  选择
                </button>
              </div></label
            >
          </div>
        </section>
        <div class="mapping-actions">
          <button type="submit" class="primary-btn" :disabled="loading">
            <Play :size="14" />{{
              loading ? "执行中…" : tool.primary_action
            }}</button
          ><button type="button" :disabled="loading" @click="reset">
            <RotateCcw :size="13" />重置参数</button
          ><button v-if="!map" type="button" :disabled="loading" @click="scan">
            预扫描</button
          ><button type="button" @click="openOutput">
            <FolderOpen :size="13" />打开输出目录
          </button>
        </div>
      </form>
      <p v-if="feedback" class="feedback" role="alert">{{ feedback }}</p>
      <section v-if="preview" class="glass-strong mapping-group">
        <h2>预扫描结果</h2>
        <pre>{{ preview }}</pre>
      </section>
      <section class="glass-strong mapping-group">
        <h2>
          <Terminal :size="14" />运行输出<button
            class="small"
            @click="emit('clearLogs')"
          >
            清空日志
          </button>
        </h2>
        <p v-if="summary">{{ summary }}</p>
        <pre class="logs">{{
          logs.length ? logs.join("\n") : "等待执行任务。"
        }}</pre>
        <template v-if="map && resultData.pgm_path"
          ><div class="mapping-stats">
            <span
              v-for="key in [
                'width',
                'height',
                'point_count',
                'walkable_cells',
                'obstacle_cells',
                'unknown_cells',
              ]"
              :key="key"
              >{{ key }} <b>{{ resultData[key] }}</b></span
            >
          </div>
          <img
            class="map-preview"
            :src="
              buildBackendImageUrl(
                resultData.preview_path || resultData.color_path,
              )
            "
            alt="生成的地图预览"
          />
          <p
            v-for="key in ['pgm_path', 'yaml_path', 'color_path']"
            :key="key"
            class="output-file"
          >
            <FileText :size="14" />{{ resultData[key] }}
          </p></template
        >
      </section>
    </div>
  </main>
</template>
