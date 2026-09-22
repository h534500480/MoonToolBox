// 功能说明：平台状态栏读取真实 ROS 遥测；断线或消息超时显示未知，避免沿用演示数值。
import { computed, onBeforeUnmount, ref, watch, type Ref } from "vue";
import { createSharedRosLiveAdapter } from "../lib/ros/liveAdapter";

/** 与现有适配器共享连接；只订阅小消息，LiDAR 状态从主显示项获得。 */
export function usePlatformTelemetry(
  enabled: Ref<boolean>,
  values: Record<string, string>,
) {
  const battery = ref<number | null>(null),
    speed = ref<number | null>(null),
    now = ref(Date.now());
  let batteryAt = 0,
    speedAt = 0;
  const timer = window.setInterval(() => (now.value = Date.now()), 1000);
  const stop = watch(
    () => [enabled.value, values.ros_bridge_url, values.ros_provider],
    (_, __, cleanup) => {
      battery.value = null;
      speed.value = null;
      if (!enabled.value || !values.ros_bridge_url) return;
      let disposed = false;
      const adapter = createSharedRosLiveAdapter({
        provider: values.ros_provider || "rosbridge",
        url: values.ros_bridge_url,
        timeoutMs: Number(values.timeout_ms) || 8000,
        adapterName: "平台状态栏",
        sharedKey: `ros-nav-test:${values.ros_provider || "rosbridge"}:${values.ros_bridge_url}:${Math.max(8000, Number(values.timeout_ms) || 8000)}`,
        autoReconnect: true,
      });
      cleanup(() => {
        disposed = true;
        adapter.disconnect();
      });
      void adapter
        .connect()
        .then(() => {
          if (disposed) return;
          adapter.subscribe(
            "/battery",
            "sensor_msgs/BatteryState",
            (m) => {
              const value = Number(m.percentage);
              battery.value =
                Number.isFinite(value) && value >= 0
                  ? Math.min(100, value <= 1 ? value * 100 : value)
                  : null;
              batteryAt = Date.now();
            },
            { throttleRateMs: 1000, queueLength: 1 },
          );
          adapter.subscribe(
            "/odometry/filtered",
            "nav_msgs/Odometry",
            (m) => {
              const v = m.twist?.twist?.linear ?? m.twist?.linear;
              speed.value =
                v && Number.isFinite(v.x) && Number.isFinite(v.y)
                  ? Math.hypot(v.x, v.y)
                  : null;
              speedAt = Date.now();
            },
            { throttleRateMs: 200, queueLength: 1 },
          );
        })
        .catch(() => {
          battery.value = null;
          speed.value = null;
        });
    },
    { immediate: true },
  );
  onBeforeUnmount(() => {
    stop();
    clearInterval(timer);
  });
  return {
    batteryText: computed(() =>
      battery.value !== null && now.value - batteryAt < 5000
        ? Math.round(battery.value) + "%"
        : "—",
    ),
    speedText: computed(() =>
      speed.value !== null && now.value - speedAt < 3000
        ? speed.value.toFixed(2) + " m/s"
        : "—",
    ),
  };
}
