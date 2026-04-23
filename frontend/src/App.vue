<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";

import { fetchPreferences, fetchSystemInfo, fetchTools, runTool, savePreferences } from "./api/client";
import HomePage from "./components/HomePage.vue";
import Sidebar from "./components/Sidebar.vue";
import ToolForm from "./components/ToolForm.vue";
import type { ToolDefinition, ToolSection } from "./types";

const defaultSections: ToolSection[] = [
  { key: "all", label: "全部工具" },
  { key: "favorites", label: "收藏夹" },
  { key: "mapping", label: "地图处理" },
  { key: "network", label: "网络工具" },
  { key: "perception", label: "感知工具" },
  { key: "entertainment", label: "娱乐分区" },
  { key: "other", label: "其他工具" }
];

const tools = ref<ToolDefinition[]>([]);
const selectedKey = ref("home");
const loading = ref(false);
const logs = ref<string[]>(["[INFO] 前端界面已就绪"]);
const summary = ref("正在加载工具...");
const sections = ref<ToolSection[]>(defaultSections);
const sectionAssignments = ref<Record<string, string>>({});
const favoriteKeys = ref<string[]>([]);
const expandedSections = ref<string[]>(["all", "favorites", "mapping", "network", "perception", "entertainment", "other"]);
const preferencesLoaded = ref(false);
const themeKey = ref("blue");
const localIp = ref("127.0.0.1");
const resultData = ref<Record<string, any>>({});
let saveTimer: number | undefined;

const selectedTool = computed(() => tools.value.find((tool) => tool.key === selectedKey.value) ?? null);

function normalizeSectionKey(label: string) {
  return (
    label
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9\u4e00-\u9fa5]+/g, "-")
      .replace(/^-+|-+$/g, "") || `section-${Date.now()}`
  );
}

function defaultSectionForTool(tool: ToolDefinition) {
  if (tool.key.includes("network")) {
    return "network";
  }
  if (tool.key.includes("costmap")) {
    return "perception";
  }
  if (tool.key.includes("pcd")) {
    return "mapping";
  }
  if (tool.key.includes("mtslash")) {
    return "entertainment";
  }
  return "other";
}

async function loadPreferences() {
  try {
    const payload = await fetchPreferences();
    sections.value = payload.sections.length > 0 ? payload.sections : defaultSections;
    sectionAssignments.value = payload.section_assignments;
    favoriteKeys.value = payload.favorite_keys;
    expandedSections.value = payload.sections.map((section) => section.key);
  } catch {
    sections.value = defaultSections;
    sectionAssignments.value = {};
    favoriteKeys.value = [];
    expandedSections.value = defaultSections.map((section) => section.key);
  } finally {
    preferencesLoaded.value = true;
  }
}

async function loadTools() {
  tools.value = await fetchTools();
  const mergedAssignments = { ...sectionAssignments.value };
  tools.value.forEach((tool) => {
    if (tool.key === "network_scan" && localIp.value) {
      const field = tool.fields.find((item) => item.key === "prefix");
      if (field) {
        field.value = localIp.value.split(".").slice(0, 3).join(".");
      }
    }
    if (!mergedAssignments[tool.key]) {
      mergedAssignments[tool.key] = defaultSectionForTool(tool);
    }
  });
  sectionAssignments.value = mergedAssignments;
  summary.value = "可在首页选择分区，或从左侧导航打开具体功能。";
}

async function handleRun(values: Record<string, string>) {
  if (!selectedTool.value) {
    return;
  }
  loading.value = true;
  try {
    const result = await runTool(selectedTool.value.key, values);
    summary.value = result.summary;
    logs.value = result.logs;
    resultData.value = result.data ?? {};
  } catch (error) {
    summary.value = "后端调用失败。";
    logs.value = [`[ERROR] ${(error as Error).message}`];
    resultData.value = {};
  } finally {
    loading.value = false;
  }
}

function handleAssignSection(payload: { toolKey: string; sectionKey: string }) {
  sectionAssignments.value = {
    ...sectionAssignments.value,
    [payload.toolKey]: payload.sectionKey
  };
}

function handleToggleFavorite(toolKey: string) {
  if (favoriteKeys.value.includes(toolKey)) {
    favoriteKeys.value = favoriteKeys.value.filter((key) => key !== toolKey);
    return;
  }
  favoriteKeys.value = [...favoriteKeys.value, toolKey];
}

function handleCreateSection(label: string) {
  const trimmed = label.trim();
  const sectionKey = normalizeSectionKey(trimmed);
  if (!trimmed || sections.value.some((section) => section.key === sectionKey)) {
    return;
  }
  sections.value = [...sections.value, { key: sectionKey, label: trimmed }];
  expandedSections.value = [...expandedSections.value, sectionKey];
}

function handleRenameSection(payload: { sectionKey: string; label: string }) {
  const trimmed = payload.label.trim();
  if (!trimmed) {
    return;
  }
  sections.value = sections.value.map((section) =>
    section.key === payload.sectionKey ? { ...section, label: trimmed } : section
  );
}

function handleDeleteSection(sectionKey: string) {
  if (sectionKey === "all" || sectionKey === "favorites") {
    return;
  }
  sections.value = sections.value.filter((section) => section.key !== sectionKey);
  expandedSections.value = expandedSections.value.filter((key) => key !== sectionKey);

  const reassigned = { ...sectionAssignments.value };
  Object.keys(reassigned).forEach((toolKey) => {
    if (reassigned[toolKey] === sectionKey) {
      reassigned[toolKey] = "other";
    }
  });
  sectionAssignments.value = reassigned;
}

function handleToggleSection(sectionKey: string) {
  if (expandedSections.value.includes(sectionKey)) {
    expandedSections.value = expandedSections.value.filter((key) => key !== sectionKey);
    return;
  }
  expandedSections.value = [...expandedSections.value, sectionKey];
}

function handleSelectTool(toolKey: string) {
  selectedKey.value = toolKey;
  const tool = tools.value.find((item) => item.key === toolKey);
  if (tool) {
    summary.value = tool.description;
  }
  resultData.value = {};
}

function handleClearLogs() {
  logs.value = [];
}

watch(
  themeKey,
  (value) => {
    document.documentElement.setAttribute("data-theme", value);
  },
  { immediate: true }
);

watch(
  [sections, sectionAssignments, favoriteKeys],
  () => {
    if (!preferencesLoaded.value) {
      return;
    }
    if (saveTimer) {
      window.clearTimeout(saveTimer);
    }
    saveTimer = window.setTimeout(async () => {
      try {
        await savePreferences({
          sections: sections.value,
          section_assignments: sectionAssignments.value,
          favorite_keys: favoriteKeys.value
        });
      } catch (error) {
        logs.value = [...logs.value, `[WARN] failed to save preferences: ${(error as Error).message}`];
      }
    }, 250);
  },
  { deep: true }
);

onMounted(async () => {
  await loadPreferences();
  try {
    const systemInfo = await fetchSystemInfo();
    localIp.value = systemInfo.local_ip || localIp.value;
    if (systemInfo.app_root) {
      localStorage.setItem("moontoolbox.appRoot", systemInfo.app_root);
    }
    await loadTools();
  } catch (error) {
    summary.value = "加载后端工具失败。";
    logs.value = [`[ERROR] ${(error as Error).message}`];
  }
});
</script>

<template>
  <div class="app-shell">
    <Sidebar
      :tools="tools"
      :selected-key="selectedKey"
      :sections="sections"
      :section-assignments="sectionAssignments"
      :favorite-keys="favoriteKeys"
      :expanded-sections="expandedSections"
      @select="handleSelectTool"
      @select-home="selectedKey = 'home'"
      @assign-section="handleAssignSection"
      @toggle-favorite="handleToggleFavorite"
      @toggle-section="handleToggleSection"
    />

    <main class="workspace">
      <div class="topbar">
        <div class="topbar-path">{{ selectedTool ? `/tools/${selectedTool.key}` : "/home" }}</div>
        <div class="topbar-actions">
          <div class="topbar-ip">本机 IP: {{ localIp }}</div>
          <label class="theme-switcher">
            <span>主题</span>
            <select v-model="themeKey" class="theme-select">
              <option value="blue">深蓝黑</option>
              <option value="emerald">墨绿白</option>
              <option value="platinum">白金</option>
            </select>
          </label>
          <div class="topbar-status">{{ selectedTool ? "功能页" : "总览页" }}</div>
        </div>
      </div>

      <HomePage
        v-if="!selectedTool"
        :tools="tools"
        :sections="sections"
        :section-assignments="sectionAssignments"
        :favorite-keys="favoriteKeys"
        :expanded-sections="expandedSections"
        :logs="logs"
        :summary="summary"
        :local-ip="localIp"
        @select-tool="handleSelectTool"
        @assign-section="handleAssignSection"
        @create-section="handleCreateSection"
        @rename-section="handleRenameSection"
        @delete-section="handleDeleteSection"
        @toggle-section="handleToggleSection"
        @toggle-favorite="handleToggleFavorite"
      />

      <template v-else>
        <ToolForm
          :tool="selectedTool"
          :loading="loading"
          :summary="summary"
          :logs="logs"
          :result-data="resultData"
          @run="handleRun"
          @clear-logs="handleClearLogs"
        />
      </template>
    </main>
  </div>
</template>
