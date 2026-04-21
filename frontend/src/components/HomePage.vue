<script setup lang="ts">
import { computed, ref } from "vue";

import type { ToolDefinition, ToolSection } from "../types";

const props = defineProps<{
  tools: ToolDefinition[];
  sections: ToolSection[];
  sectionAssignments: Record<string, string>;
  favoriteKeys: string[];
  expandedSections: string[];
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
  const nextLabel = window.prompt("Rename section", section.label);
  if (!nextLabel) {
    return;
  }
  emit("renameSection", { sectionKey: section.key, label: nextLabel });
}

function deleteSection(section: ToolSection) {
  if (section.key === "all" || section.key === "favorites") {
    return;
  }
  const confirmed = window.confirm(`Delete section "${section.label}"? Tools in this section will move to Other.`);
  if (!confirmed) {
    return;
  }
  emit("deleteSection", section.key);
}
</script>

<template>
  <div class="home-shell">
    <section class="home-hero panel">
      <div>
        <div class="home-eyebrow">Workspace</div>
        <h1>Tool Sections</h1>
        <p>按分区管理工具，支持搜索分区、拖拽归类、展开查看小功能并直接跳转。</p>
      </div>
      <div class="home-stats">
        <div class="home-stat-card">
          <span class="home-stat-value">{{ sections.length }}</span>
          <span class="home-stat-label">Sections</span>
        </div>
        <div class="home-stat-card">
          <span class="home-stat-value">{{ tools.length }}</span>
          <span class="home-stat-label">Tools</span>
        </div>
      </div>
    </section>

    <section class="panel home-toolbar">
      <div class="home-toolbar-left">
        <input
          v-model="sectionQuery"
          class="field-input"
          placeholder="Search section"
        />
      </div>
      <div class="home-toolbar-right">
        <input
          v-model="newSectionLabel"
          class="field-input"
          placeholder="New section name"
          @keydown.enter.prevent="submitSection"
        />
        <button class="primary-btn" @click="submitSection">Create Section</button>
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
              Rename
            </button>
            <button
              v-if="section.key !== 'all' && section.key !== 'favorites'"
              class="section-card-action danger"
              @click="deleteSection(section)"
            >
              Delete
            </button>
          </div>
        </div>

        <div class="section-card-drop">{{ section.key === "all" ? "All tools are shown here" : "Drop tool here" }}</div>

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
            No tools in this section
          </div>
        </div>
      </article>
    </section>
  </div>
</template>
