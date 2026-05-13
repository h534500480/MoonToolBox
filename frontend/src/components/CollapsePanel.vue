<script setup lang="ts">
defineProps<{
  open: boolean;
}>();
</script>

<template>
  <div
    class="collapse-panel"
    :class="{ 'is-open': open }"
    :aria-hidden="open ? 'false' : 'true'"
    :inert="open ? undefined : ''"
  >
    <div class="collapse-panel-inner">
      <slot />
    </div>
  </div>
</template>
