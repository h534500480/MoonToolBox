<script setup lang="ts">
import { reactive, watch } from "vue";

import type { ToolDefinition } from "../types";

const props = defineProps<{
  tool: ToolDefinition;
  loading: boolean;
}>();

const emit = defineEmits<{
  run: [values: Record<string, string>];
}>();

const formValues = reactive<Record<string, string>>({});

watch(
  () => props.tool,
  (tool) => {
    Object.keys(formValues).forEach((key) => delete formValues[key]);
    tool.fields.forEach((field) => {
      formValues[field.key] = field.value ?? "";
    });
  },
  { immediate: true }
);

function submit() {
  emit("run", { ...formValues });
}
</script>

<template>
  <div class="tool-shell">
    <header class="panel-header">
      <div>
        <h1>{{ tool.title }}</h1>
        <p>{{ tool.description }}</p>
      </div>
      <div class="status-pill">Ready</div>
    </header>

    <section class="panel">
      <div class="grid-form">
        <label v-for="field in tool.fields" :key="field.key" class="field">
          <span class="field-label">{{ field.label }}</span>
          <input
            v-model="formValues[field.key]"
            class="field-input"
            :placeholder="field.placeholder"
          />
        </label>
      </div>

      <div class="actions">
        <button class="primary-btn" :disabled="loading" @click="submit">
          {{ loading ? "Running..." : tool.primary_action }}
        </button>
        <button class="secondary-btn" type="button">
          {{ tool.secondary_action }}
        </button>
      </div>
    </section>
  </div>
</template>
