<script setup lang="ts">
import { computed, ref } from "vue";

import type { ToolDefinition, ToolSection } from "../types";

const props = defineProps<{
  tools: ToolDefinition[];
  sections: ToolSection[];
  sectionAssignments: Record<string, string>;
  favoriteKeys: string[];
  expandedSections: string[];
  logs: string[];
  summary: string;
  localIp: string;
}>();

const emit = defineEmits<{
  selectTool: [toolKey: string];
  assignSection: [payload: { toolKey: string; sectionKey: string }];
  createSection: [label: string];
  renameSection: [payload: { sectionKey: string; label: string }];
  deleteSection: [sectionKey: string];
  toggleSection: [sectionKey: string];
  toggleFavorite: [toolKey: string];
}>();

const sectionQuery = ref("");
const newSectionLabel = ref("");
const previewToolKey = ref("");

const visibleSections = computed(() => {
  const query = sectionQuery.value.trim().toLowerCase();
  return props.sections.filter((section) => {
    if (section.key === "favorites") {
      return true;
    }
    if (!query) {
      return true;
    }
    return section.label.toLowerCase().includes(query) || section.key.toLowerCase().includes(query);
  });
});

const previewTools = computed(() => {
  const preferredKeys = ["pcd_map", "pcd_tile", "mtslash_export", "network_scan", "costmap"];
  const preferred = preferredKeys
    .map((key) => props.tools.find((tool) => tool.key === key))
    .filter((tool): tool is ToolDefinition => Boolean(tool));
  const merged = [...preferred, ...props.tools].filter((tool, index, list) => list.findIndex((item) => item.key === tool.key) === index);
  return merged.slice(0, 4);
});

const activePreviewTool = computed(() => {
  return previewTools.value.find((tool) => tool.key === previewToolKey.value) ?? previewTools.value[0] ?? null;
});

const recentLogs = computed(() => {
  const lines = props.logs.length > 0 ? props.logs : ["[INFO] 系统启动成功", "[INFO] 等待任务..."];
  return lines.slice(-6);
});

function selectPreview(tool: ToolDefinition) {
  previewToolKey.value = tool.key;
}

function toolsForSection(sectionKey: string) {
  if (sectionKey === "all") {
    return props.tools;
  }
  if (sectionKey === "favorites") {
    return props.tools.filter((tool) => props.favoriteKeys.includes(tool.key));
  }
  return props.tools.filter((tool) => (props.sectionAssignments[tool.key] ?? "other") === sectionKey);
}

function submitSection() {
  const label = newSectionLabel.value.trim();
  if (!label) {
    return;
  }
  emit("createSection", label);
  newSectionLabel.value = "";
}

function resolveDraggedToolKey(event: DragEvent) {
  return event.dataTransfer?.getData("text/tool-key") || "";
}

function dropToSection(sectionKey: string, event: DragEvent) {
  const toolKey = resolveDraggedToolKey(event);
  if (!toolKey) {
    return;
  }
  if (sectionKey === "all") {
    return;
  }
  if (sectionKey === "favorites") {
    if (!props.favoriteKeys.includes(toolKey)) {
      emit("toggleFavorite", toolKey);
    }
    return;
  }
  emit("assignSection", { toolKey, sectionKey });
}

function renameSection(section: ToolSection) {
  if (section.key === "all" || section.key === "favorites") {
    return;
  }
  const nextLabel = window.prompt("重命名分区", section.label);
  if (!nextLabel) {
    return;
  }
  emit("renameSection", { sectionKey: section.key, label: nextLabel });
}

function deleteSection(section: ToolSection) {
  if (section.key === "all" || section.key === "favorites") {
    return;
  }
  const confirmed = window.confirm(`删除分区“${section.label}”后，其中的小功能会移动到“其他工具”，是否继续？`);
  if (!confirmed) {
    return;
  }
  emit("deleteSection", section.key);
}
</script>

<template>
  <div class="home-shell">
    <div class="home-dashboard">
      <div class="home-main-column">
        <section class="home-hero panel">
          <div>
            <div class="home-eyebrow">工作台</div>
            <h1>工具分区</h1>
            <p>按大分区管理工具，支持搜索分区、拖拽归类、展开查看小功能并直接跳转。</p>
          </div>
          <div class="home-stats">
            <div class="home-stat-card">
              <span class="home-stat-value">{{ sections.length }}</span>
              <span class="home-stat-label">分区数量</span>
            </div>
            <div class="home-stat-card">
              <span class="home-stat-value">{{ tools.length }}</span>
              <span class="home-stat-label">工具数量</span>
            </div>
          </div>
        </section>

        <section class="panel home-toolbar">
          <div class="home-toolbar-left">
            <input
              v-model="sectionQuery"
              class="field-input"
              placeholder="搜索分区 / 小功能"
            />
          </div>
          <div class="home-toolbar-right">
            <input
              v-model="newSectionLabel"
              class="field-input"
              placeholder="输入新分区名称"
              @keydown.enter.prevent="submitSection"
            />
            <button class="primary-btn" @click="submitSection">新建分区</button>
          </div>
        </section>

        <section class="section-grid">
          <article
            v-for="section in visibleSections"
            :key="section.key"
            class="section-card"
            @dragover.prevent
            @drop.prevent="dropToSection(section.key, $event)"
          >
            <div class="section-card-header">
              <button class="section-card-toggle" @click="emit('toggleSection', section.key)">
                <span>{{ section.label }}</span>
                <span class="section-card-meta">{{ toolsForSection(section.key).length }}</span>
              </button>
              <div class="section-card-actions">
                <button
                  v-if="section.key !== 'all' && section.key !== 'favorites'"
                  class="section-card-action"
                  @click="renameSection(section)"
                >
                  重命名
                </button>
                <button
                  v-if="section.key !== 'all' && section.key !== 'favorites'"
                  class="section-card-action danger"
                  @click="deleteSection(section)"
                >
                  删除
                </button>
              </div>
            </div>

            <div class="section-card-drop">{{ section.key === "all" ? "这里展示全部工具" : "可将左侧小功能拖到这里" }}</div>

            <div v-if="expandedSections.includes(section.key)" class="section-card-tools">
              <button
                v-for="tool in toolsForSection(section.key)"
                :key="tool.key"
                class="section-tool-chip"
                @click="emit('selectTool', tool.key)"
              >
                <span class="section-tool-title">{{ tool.title }}</span>
                <span class="section-tool-subtitle">{{ tool.subtitle }}</span>
              </button>
              <div v-if="toolsForSection(section.key).length === 0" class="section-empty">
                当前分区下还没有小功能
              </div>
            </div>
          </article>
        </section>

        <section class="panel home-workbench">
          <div class="home-tabs">
            <button class="home-tab active" type="button">首页</button>
            <button
              v-for="tool in previewTools"
              :key="tool.key"
              class="home-tab"
              :class="{ active: activePreviewTool?.key === tool.key }"
              type="button"
              @click="selectPreview(tool)"
            >
              {{ tool.title }}
            </button>
          </div>
          <div class="home-preview-grid">
            <div class="home-preview-main">
              <div class="result-title">{{ activePreviewTool?.title || "工具预览" }}</div>
              <p class="summary">{{ activePreviewTool?.description || summary }}</p>
              <button
                v-if="activePreviewTool"
                class="primary-btn"
                type="button"
                @click="emit('selectTool', activePreviewTool.key)"
              >
                打开工具
              </button>
            </div>
            <div class="home-preview-side">
              <div class="section-subtitle">当前摘要</div>
              <p class="summary">{{ summary }}</p>
            </div>
          </div>
        </section>
      </div>

      <aside class="home-side-rail">
        <section class="panel side-card">
          <div class="result-title">系统状态</div>
          <div class="side-status-row"><span>运行状态</span><strong class="ok-dot">正常运行</strong></div>
          <div class="side-meter"><span>CPU</span><div><i style="width: 23%"></i></div><em>23%</em></div>
          <div class="side-meter"><span>内存</span><div><i style="width: 48%"></i></div><em>48%</em></div>
          <div class="side-meter"><span>磁盘</span><div><i style="width: 61%"></i></div><em>61%</em></div>
          <div class="side-status-row"><span>本机 IP</span><strong>{{ localIp }}</strong></div>
        </section>

        <section class="panel side-card">
          <div class="result-title">快捷操作</div>
          <button class="secondary-btn side-action" type="button" @click="emit('selectTool', 'pcd_map')">打开地图工具</button>
          <button class="secondary-btn side-action" type="button" @click="emit('selectTool', 'network_scan')">网络扫描</button>
          <button class="secondary-btn side-action" type="button" @click="emit('selectTool', 'mtslash_export')">MTSlash 导出</button>
        </section>

        <section class="panel side-card side-log-card">
          <div class="section-head">
            <div class="result-title">运行日志</div>
          </div>
          <div class="side-log-list">
            <div v-for="line in recentLogs" :key="line" class="side-log-line">{{ line }}</div>
          </div>
        </section>
      </aside>
    </div>
  </div>
</template>
