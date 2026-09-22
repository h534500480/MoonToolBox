<!-- 功能说明：触屏端使用独立输入草稿，键盘上方确认后才写回原字段。 -->
<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import { interaction } from "../platform/interaction";
type Field = HTMLInputElement | HTMLTextAreaElement;
const active = ref(false),
  value = ref(""),
  label = ref(""),
  error = ref(""),
  multiline = ref(false);
const inputMode = ref("text"),
  inputType = ref("text"),
  bottom = ref(8),
  maxHeight = ref(300);
const editor = ref<HTMLInputElement | HTMLTextAreaElement>();
let target: Field | null = null,
  observer: MutationObserver | null = null;
let nativeIme: number | null = null,
  wasKeyboardVisible = false,
  opening = false;
/** 排除原生选择器和只读控件；标签保持与原字段一致。 */
function editable(element: EventTarget | null): element is Field {
  if (!(
    element instanceof HTMLInputElement ||
    element instanceof HTMLTextAreaElement
  ))
    return false;
  return (
    !element.disabled &&
    !element.readOnly &&
    !element.closest(".mobile-input-layer") &&
    ![
      "file",
      "range",
      "color",
      "date",
      "time",
      "datetime-local",
      "checkbox",
      "radio",
      "button",
      "submit",
      "hidden",
    ].includes(element.type)
  );
}
async function open(field: Field) {
  if (target === field && active.value) return;
  target = field;
  value.value = field.value;
  error.value = "";
  label.value =
    field.getAttribute("aria-label") ||
    field.labels?.[0]?.textContent?.trim() ||
    field
      .closest("label,.field,.nav-display-config-item")
      ?.querySelector("span,.field-label,.kv-key")
      ?.textContent?.trim() ||
    field.placeholder ||
    "输入";
  multiline.value = field instanceof HTMLTextAreaElement;
  inputMode.value =
    field.inputMode || (field.type === "number" ? "decimal" : "text");
  inputType.value = field.type === "password" ? "password" : "text";
  active.value = true;
  opening = true;
  wasKeyboardVisible = false;
  document.documentElement.dataset.editingInput = "true";
  field.blur();
  await nextTick();
  metrics();
  editor.value?.focus({ preventScroll: true });
  editor.value?.select();
  opening = false;
}
function intercept(event: Event) {
  if (!interaction.touch || !editable(event.target)) return;
  if (event.cancelable) event.preventDefault();
  event.stopPropagation();
  void open(event.target);
}
/** 取消不分发任何输入事件；不恢复原字段焦点，避免再次打开键盘。 */
function close() {
  editor.value?.blur();
  active.value = false;
  target = null;
  wasKeyboardVisible = false;
  delete document.documentElement.dataset.editingInput;
}
function commit() {
  const field = target;
  if (!field?.isConnected || field.disabled || field.readOnly) {
    close();
    return;
  }
  const probe = field.cloneNode() as Field;
  if (
    field.type === "number" &&
    value.value.trim() &&
    !Number.isFinite(Number(value.value))
  ) {
    error.value = "请输入有效数字。";
    return;
  }
  probe.value = value.value;
  if (!probe.checkValidity()) {
    error.value = probe.validationMessage || "请检查输入值。";
    return;
  }
  if (field.maxLength >= 0 && value.value.length > field.maxLength) {
    error.value = `最多输入 ${field.maxLength} 个字符。`;
    return;
  }
  const next = probe.value;
  close();
  field.value = next;
  field.dispatchEvent(new Event("input", { bubbles: true }));
  field.dispatchEvent(new Event("change", { bubbles: true }));
  field.dispatchEvent(new FocusEvent("blur"));
}
function key(event: KeyboardEvent) {
  if (event.isComposing || event.keyCode === 229) return;
  if (event.key === "Escape") {
    event.preventDefault();
    event.stopPropagation();
    close();
  }
  if (event.key === "Enter" && !multiline.value) {
    event.preventDefault();
    event.stopPropagation();
    commit();
  }
}
/** Android 上报物理覆盖高度；已缩小的视口只补剩余遮挡，避免重复抬升。 */
function metrics() {
  if (!active.value) return;
  const viewport = window.visualViewport;
  const visualInset = viewport
    ? Math.max(0, window.innerHeight - viewport.height - viewport.offsetTop)
    : 0;
  const inset = Math.max(visualInset, nativeIme ?? 0);
  bottom.value = inset + 8;
  maxHeight.value = Math.max(
    80,
    window.innerHeight - inset - (viewport?.offsetTop ?? 0) - 16,
  );
  if (inset > 80) wasKeyboardVisible = true;
  else if (wasKeyboardVisible && !opening) close();
}
function nativeInsets(event: Event) {
  nativeIme = Number((event as CustomEvent).detail?.imeOverlap) || 0;
  metrics();
}
onMounted(() => {
  document.addEventListener("pointerdown", intercept, true);
  document.addEventListener("click", intercept, true);
  document.addEventListener("focusin", intercept, true);
  window.addEventListener("ros-window-insets", nativeInsets);
  window.visualViewport?.addEventListener("resize", metrics);
  window.visualViewport?.addEventListener("scroll", metrics);
  window.addEventListener("resize", metrics);
  window.addEventListener("popstate", close);
  observer = new MutationObserver(() => {
    if (
      active.value &&
      target &&
      (!target.isConnected || target.getClientRects().length === 0)
    )
      close();
  });
  observer.observe(document.body, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ["style", "hidden"],
  });
});
onBeforeUnmount(() => {
  close();
  observer?.disconnect();
  document.removeEventListener("pointerdown", intercept, true);
  document.removeEventListener("click", intercept, true);
  document.removeEventListener("focusin", intercept, true);
  window.removeEventListener("ros-window-insets", nativeInsets);
  window.visualViewport?.removeEventListener("resize", metrics);
  window.visualViewport?.removeEventListener("scroll", metrics);
  window.removeEventListener("resize", metrics);
  window.removeEventListener("popstate", close);
});
</script>
<template>
  <Teleport to="body"
    ><Transition name="mobile-input">
      <div v-if="active" class="mobile-input-layer" @keydown="key">
        <div class="mobile-input-backdrop" @pointerdown.prevent="close" />
        <section
          role="dialog"
          aria-modal="true"
          :aria-label="`编辑：${label}`"
          class="mobile-input-panel"
          :style="{ bottom: `${bottom}px`, maxHeight: `${maxHeight}px` }"
        >
          <label class="mobile-input-field"
            ><span>{{ label }}</span>
            <textarea v-if="multiline" ref="editor" v-model="value" rows="2" />
            <input
              v-else
              ref="editor"
              v-model="value"
              :type="inputType"
              :inputmode="inputMode as any"
              enterkeyhint="done"
              autocomplete="off"
            />
          </label>
          <div class="mobile-input-buttons">
            <button
              v-if="inputMode === 'decimal' || inputMode === 'numeric'"
              type="button"
              @pointerdown.prevent
              @click="
                value = value.startsWith('-') ? value.slice(1) : '-' + value
              "
            >
              ±</button
            ><button type="button" @pointerdown.prevent @click="close">
              取消</button
            ><button
              class="confirm"
              type="button"
              @pointerdown.prevent
              @click="commit"
            >
              确定
            </button>
          </div>
          <p v-if="error" role="alert">{{ error }}</p>
        </section>
      </div>
    </Transition></Teleport
  >
</template>
<style scoped>
.mobile-input-layer {
  position: fixed;
  inset: 0;
  z-index: 10000;
}
.mobile-input-backdrop {
  position: absolute;
  inset: 0;
  background: rgb(50 44 35 / 10%);
}
.mobile-input-panel {
  position: absolute;
  left: max(8px, env(safe-area-inset-left));
  right: max(8px, env(safe-area-inset-right));
  max-width: 740px;
  margin: 0 auto;
  display: flex;
  align-items: end;
  flex-wrap: wrap;
  gap: 10px;
  padding: 12px;
  overflow: auto;
  background: #f3f0e8;
  border: 1px solid #ded8cc;
  border-radius: 12px;
  box-shadow: 0 5px 24px #39352b33;
  color: #34332f;
}
.mobile-input-field {
  flex: 1;
  min-width: 140px;
  display: grid;
  gap: 5px;
  font-size: 12px;
}
.mobile-input-field input,
.mobile-input-field textarea {
  width: 100%;
  box-sizing: border-box;
  min-height: 42px;
  border: 1px solid #d5cec1;
  border-radius: 7px;
  background: #fffdf8;
  padding: 8px 10px;
  font: inherit;
  font-size: 16px;
  color: #302e28;
}
.mobile-input-buttons {
  display: flex;
  gap: 6px;
}
button {
  min-width: 48px;
  min-height: 42px;
  border: 0;
  border-radius: 7px;
  background: #e6e1d6;
  color: #37352f;
}
button.confirm {
  background: #766952;
  color: white;
}
p {
  flex-basis: 100%;
  color: #a44237;
  margin: 0;
  font-size: 12px;
}
.mobile-input-enter-active,
.mobile-input-leave-active {
  transition: opacity 140ms ease;
}
.mobile-input-enter-from,
.mobile-input-leave-to {
  opacity: 0;
}
</style>
