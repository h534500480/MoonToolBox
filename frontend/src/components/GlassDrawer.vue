<!-- 功能说明：可关闭的玻璃抽屉；挂载到根层以避免祖先透明度切断背景采样。persistent 模式为非模态：无遮罩、点击穿透到底层场景，供配合三维场景操作的抽屉使用。 -->
<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref, watch, nextTick } from "vue";
import { X } from "@lucide/vue";
const props = defineProps<{
  open: boolean;
  title: string;
  wide?: boolean;
  persistent?: boolean;
}>();
const emit = defineEmits<{ close: [] }>();
const panel = ref<HTMLElement>();
let previous: HTMLElement | null = null;
function key(event: KeyboardEvent) {
  if (!props.open) return;
  const dialogs = document.querySelectorAll('[role="dialog"]');
  if (dialogs[dialogs.length - 1] !== panel.value) return;
  if (event.key === "Escape") emit("close");
  // 非模态模式下不锁定焦点：用户可能需要用键盘或点击操作三维场景
  if (event.key === "Tab" && !props.persistent) {
    const items = Array.from(
      panel.value?.querySelectorAll<HTMLElement>(
        "button:not(:disabled),input:not(:disabled),select,textarea,a[href],summary",
      ) ?? [],
    ).filter((item) => item.getClientRects().length > 0);
    if (!items?.length) return;
    const first = items[0],
      last = items[items.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (
      !event.shiftKey &&
      (document.activeElement === last ||
        document.activeElement === panel.value)
    ) {
      event.preventDefault();
      first.focus();
    }
  }
}
watch(
  () => props.open,
  async (value) => {
    if (value) {
      previous = document.activeElement as HTMLElement;
      await nextTick();
      panel.value?.focus();
    } else previous?.focus();
  },
);
onMounted(() => document.addEventListener("keydown", key));
onBeforeUnmount(() => document.removeEventListener("keydown", key));
</script>
<template>
  <Teleport to="body"
    ><Transition name="drawer"
      ><div v-if="open" class="drawer-layer" :class="{ persistent }">
        <div v-if="!persistent" class="drawer-dismiss" @click="emit('close')" />
        <aside
          ref="panel"
          class="glass-strong glass-drawer"
          :class="{ wide }"
          tabindex="-1"
          role="dialog"
          :aria-modal="persistent ? 'false' : 'true'"
          :aria-label="title"
        >
          <header>
            <h2>{{ title }}</h2>
            <button
              class="icon-button"
              aria-label="关闭面板"
              @click="emit('close')"
            >
              <X :size="16" />
            </button>
          </header>
          <div class="drawer-content"><slot /></div>
        </aside></div></Transition
  ></Teleport>
</template>
