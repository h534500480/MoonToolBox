// 功能说明：平台视觉选项与演示状态；业务连接数据不写入演示状态。
import { reactive, watch } from "vue";

const defaults = {
  hudOpacity: 0.32,
  showGrid: true,
  showTrail: true,
  showCone: true,
  showShadows: true,
  robotAnim: "walk" as "idle" | "walk" | "run",
};
let saved = {};
try {
  saved = JSON.parse(localStorage.getItem("ros-platform.visual") || "{}");
} catch {
  /* 损坏的本地视觉配置使用默认值。 */
}
export const visual = reactive({ ...defaults, ...saved });
watch(
  visual,
  (value) => localStorage.setItem("ros-platform.visual", JSON.stringify(value)),
  { deep: true },
);
export const platformState = reactive({
  demo: true,
  connected: false,
  pose: "等待位姿数据",
  speed: 0,
  lidarAt: 0,
  lidarActive: false,
  cameraReset: 0,
});
