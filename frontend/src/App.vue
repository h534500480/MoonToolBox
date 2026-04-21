<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";

import { fetchPreferences, fetchTools, runTool, savePreferences } from "./api/client";
import HomePage from "./components/HomePage.vue";
import Sidebar from "./components/Sidebar.vue";
import ToolForm from "./components/ToolForm.vue";
import type { ToolDefinition, ToolSection } from "./types";

const defaultSections: ToolSection[] = [
  { key: "all", label: "All Tools" },
  { key: "favorites", label: "Favorites" },
  { key: "mapping", label: "Mapping" },
  { key: "network", label: "Network" },
  { key: "perception", label: "Perception" },
  { key: "other", label: "Other" }
];

const tools = ref<ToolDefinition[]>([]);
const selectedKey = ref("home");
const loading = ref(false);
const logs = ref<string[]>(["[INFO] frontend shell ready"]);
const summary = ref("Loading tools...");
const sections = ref<ToolSection[]>(defaultSections);
const sectionAssignments = ref<Record<string, string>>({});
const favoriteKeys = ref<string[]>([]);
const expandedSections = ref<string[]>(["all", "favorites", "mapping", "network", "perception", "other"]);
const preferencesLoaded = ref(false);
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
    if (!mergedAssignments[tool.key]) {
      mergedAssignments[tool.key] = defaultSectionForTool(tool);
    }
  });
  sectionAssignments.value = mergedAssignments;
  summary.value = "Select a section on the home page or open a tool from the left navigation.";
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
  } catch (error) {
    summary.value = "Backend call failed.";
    logs.value = [`[ERROR] ${(error as Error).message}`];
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
}

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
    await loadTools();
  } catch (error) {
    summary.value = "Failed to load backend tools.";
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
        <div class="topbar-status">{{ selectedTool ? "Tool Page" : "Overview" }}</div>
      </div>

      <HomePage
        v-if="!selectedTool"
        :tools="tools"
        :sections="sections"
        :section-assignments="sectionAssignments"
        :favorite-keys="favoriteKeys"
        :expanded-sections="expandedSections"
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
          @run="handleRun"
        />

        <section class="result-panel">
          <div class="result-title">Output</div>
          <p class="summary">{{ summary }}</p>
        </section>

        <section class="log-panel">
          <div class="result-title">Logs</div>
          <pre class="logs">{{ logs.join("\n") }}</pre>
        </section>
      </template>
    </main>
  </div>
</template>
