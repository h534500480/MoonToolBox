<script setup lang="ts">
import { computed, ref } from "vue";

import type { ToolDefinition, ToolSection } from "../types";

const props = defineProps<{
  tools: ToolDefinition[];
  selectedKey: string;
  sections: ToolSection[];
  sectionAssignments: Record<string, string>;
  favoriteKeys: string[];
  expandedSections: string[];
}>();

const emit = defineEmits<{
  select: [key: string];
  selectHome: [];
  assignSection: [payload: { toolKey: string; sectionKey: string }];
  toggleFavorite: [toolKey: string];
  toggleSection: [sectionKey: string];
}>();

const toolQuery = ref("");
const draggingToolKey = ref("");

const groupedSections = computed(() => {
  const query = toolQuery.value.trim().toLowerCase();
  return props.sections
    .map((section) => {
      const tools =
        section.key === "all"
          ? props.tools
          : section.key === "favorites"
            ? props.tools.filter((tool) => props.favoriteKeys.includes(tool.key))
            : props.tools.filter((tool) => (props.sectionAssignments[tool.key] ?? "other") === section.key);
      const filtered = query
        ? tools.filter(
            (tool) =>
              tool.title.toLowerCase().includes(query) ||
              tool.subtitle.toLowerCase().includes(query) ||
              tool.key.toLowerCase().includes(query)
          )
        : tools;
      return { ...section, tools: filtered };
    })
    .filter((section) => section.tools.length > 0 || section.key !== "favorites");
});

function startDrag(toolKey: string, event: DragEvent) {
  draggingToolKey.value = toolKey;
  event.dataTransfer?.setData("text/tool-key", toolKey);
  event.dataTransfer?.setData("text/plain", toolKey);
  if (event.dataTransfer) {
    event.dataTransfer.effectAllowed = "move";
  }
}

function clearDrag() {
  draggingToolKey.value = "";
}

function resolveDraggedToolKey(event: DragEvent) {
  return event.dataTransfer?.getData("text/tool-key") || draggingToolKey.value;
}

function dropToSection(sectionKey: string, event: DragEvent) {
  const toolKey = resolveDraggedToolKey(event);
  if (!toolKey) {
    return;
  }
  if (sectionKey === "all") {
    clearDrag();
    return;
  }
  if (sectionKey === "favorites") {
    if (!props.favoriteKeys.includes(toolKey)) {
      emit("toggleFavorite", toolKey);
    }
    clearDrag();
    return;
  }
  emit("assignSection", { toolKey, sectionKey });
  clearDrag();
}
</script>

<template>
  <aside class="sidebar">
    <div class="brand">ROS Tool Suite</div>

    <button class="home-button" :class="{ active: selectedKey === 'home' }" @click="emit('selectHome')">
      Overview Home
    </button>

    <div class="section-label">TOOLS</div>

    <input
      v-model="toolQuery"
      class="sidebar-search"
      placeholder="Search tool"
    />

    <div v-for="section in groupedSections" :key="section.key" class="nav-group">
      <div
        class="nav-group-title"
        :class="{ droppable: true, dragging: !!draggingToolKey }"
        @click="emit('toggleSection', section.key)"
        @dragover.prevent
        @drop.prevent="dropToSection(section.key, $event)"
      >
        <span>{{ props.expandedSections.includes(section.key) ? "▾" : "▸" }} {{ section.label }}</span>
        <span class="nav-group-count">{{ section.tools.length }}</span>
      </div>

      <div v-if="props.expandedSections.includes(section.key)" class="nav-items">
        <div
          v-for="tool in section.tools"
          :key="tool.key"
          class="nav-button"
          :class="{ active: tool.key === selectedKey }"
          role="button"
          tabindex="0"
          draggable="true"
          @click="emit('select', tool.key)"
          @keydown.enter.prevent="emit('select', tool.key)"
          @dragstart="startDrag(tool.key, $event)"
          @dragend="clearDrag"
        >
          <span class="nav-header-row">
            <span class="nav-title">{{ tool.title }}</span>
            <button
              class="favorite-btn"
              :class="{ active: favoriteKeys.includes(tool.key) }"
              @click.stop="emit('toggleFavorite', tool.key)"
            >
              ★
            </button>
          </span>
          <span class="nav-subtitle">{{ tool.subtitle }}</span>
        </div>
      </div>
    </div>
  </aside>
</template>
