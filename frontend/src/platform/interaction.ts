// 功能说明：集中管理运行容器、触摸能力与紧凑布局，业务模块不依赖设备名称。
import { reactive, readonly } from "vue";
import { Capacitor } from "@capacitor/core";
export type LayoutPreset = "auto" | "wide-3200" | "phone" | "desktop";
const presetKey = "ros-platform.layout-preset.v1";
const presets: LayoutPreset[] = ["auto", "wide-3200", "phone", "desktop"];
function savedPreset(): LayoutPreset {
  try {
    const value = localStorage.getItem(presetKey) as LayoutPreset;
    return presets.includes(value) ? value : "auto";
  } catch {
    return "auto";
  }
}

const state = reactive({
  android:
    Capacitor.isNativePlatform() && Capacitor.getPlatform() === "android",
  touch: false,
  compact: false,
  preset: savedPreset(),
  layout: "desktop" as Exclude<LayoutPreset, "auto">,
  width: window.innerWidth,
  height: window.innerHeight,
  pixelRatio: window.devicePixelRatio || 1,
  preferenceError: "",
});
export const interaction = readonly(state);
let refreshLayout = () => {};
/** 预设只调整覆盖层布局，不改变三维相机、渲染分辨率或 ROS 会话。 */
export function setLayoutPreset(value: string) {
  if (!presets.includes(value as LayoutPreset)) return;
  state.preset = value as LayoutPreset;
  state.preferenceError = "";
  try {
    localStorage.setItem(presetKey, value);
  } catch {
    state.preferenceError = "布局已切换，但当前环境无法保存偏好。";
  }
  refreshLayout();
}
/** 原生能力按容器判断，触屏交互按主指针能力判断，避免窄桌面窗口被当成安卓。 */
export function installInteractionCapabilities() {
  const media = window.matchMedia("(pointer: coarse)");
  const update = () => {
    state.touch = state.android || media.matches;
    state.width = window.innerWidth;
    state.height = window.innerHeight;
    state.pixelRatio = window.devicePixelRatio || 1;
    const wideScreen =
      Math.max(screen.width, screen.height) * state.pixelRatio >= 2800 &&
      state.width / state.height >= 1.9;
    state.layout =
      state.preset !== "auto"
        ? state.preset
        : !state.touch
          ? "desktop"
          : wideScreen
            ? "wide-3200"
            : "phone";
    state.compact = state.layout !== "desktop";
    document.documentElement.dataset.interaction = state.touch
      ? "touch"
      : "desktop";
    document.documentElement.dataset.container = state.android
      ? "android"
      : "browser";
    document.documentElement.dataset.compact = String(state.compact);
    document.documentElement.dataset.layout = state.layout;
  };
  refreshLayout = update;
  update();
  media.addEventListener("change", update);
  window.addEventListener("resize", update);
  return () => {
    media.removeEventListener("change", update);
    window.removeEventListener("resize", update);
  };
}
