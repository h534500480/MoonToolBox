// 功能说明：可折叠分组（details）展开状态的记忆与持久化；
// 抽屉 v-if 销毁或刷新页面后按上次操作恢复。
// 用法：:open="isDetailsOpen('key', true)" @toggle="onDetailsToggle('key', $event)"
import { reactive } from "vue";

const STORAGE_KEY = "ros-platform.details-open";

// 模块级单例：同一 key 的展开状态在所有组件实例间共享
const openStates = reactive<Record<string, boolean>>(loadPersistedStates());

function loadPersistedStates(): Record<string, boolean> {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      return {};
    }
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function persistStates() {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(openStates));
  } catch {
    // localStorage 不可用（隐私模式/已满）时仅保留内存状态，不阻断交互
  }
}

/**
 * 读取某分组的展开状态。
 * @param key 分组唯一标识，需在调用方保持稳定
 * @param defaultOpen 用户从未操作过该分组时的初始状态
 */
export function isDetailsOpen(key: string, defaultOpen: boolean): boolean {
  return openStates[key] ?? defaultOpen;
}

/** 用户点击 summary 触发原生 toggle 后，把最新状态写入记忆。 */
export function onDetailsToggle(key: string, event: Event) {
  const target = event.target as HTMLDetailsElement | null;
  if (!target || typeof target.open !== "boolean") {
    return;
  }
  openStates[key] = target.open;
  persistStates();
}
