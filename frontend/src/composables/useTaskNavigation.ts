// 功能说明：让导航适配器随平台 ROS 连接建立和释放，模式切换不重建执行器。
import { onBeforeUnmount, ref, watch, type Ref } from "vue";
import { createSharedRosLiveAdapter } from "../lib/ros/liveAdapter";
import {
  RosNavigationTransport,
  type NavigationConnectionState,
} from "../lib/rosNavigationTransport";
import { createNavigationOwnership } from "../lib/navigationOwnership";

export function useTaskNavigation(
  enabled: Ref<boolean>,
  values: Record<string, string>,
) {
  const status = ref<NavigationConnectionState>({
    connected: false,
    ready: false,
    contextFresh: false,
    localizationFresh: false,
    localization: null,
    stage: "状态未知",
    scanState: "—",
    requestId: "",
    message: "请连接 ROS，任务未下发。",
  });
  const transport = new RosNavigationTransport(
    (value) => {
      status.value = value;
    },
    Date.now,
    undefined,
    createNavigationOwnership(),
  );
  const stop = watch(
    () => [
      enabled.value,
      values.ros_bridge_url,
      values.ros_provider,
      values.timeout_ms,
    ],
    (_, __, cleanup) => {
      const source = `${values.ros_provider || "rosbridge"}:${values.ros_bridge_url || ""}`;
      if (
        !enabled.value ||
        !values.ros_bridge_url ||
        values.ros_provider === "mock"
      ) {
        transport.bind(null, source);
        return;
      }
      const timeoutMs = Math.max(8000, Number(values.timeout_ms) || 8000);
      let disposed = false;
      const adapter = createSharedRosLiveAdapter({
        provider: values.ros_provider || "rosbridge",
        url: values.ros_bridge_url,
        timeoutMs,
        sharedKey: `ros-nav-test:${source}:${timeoutMs}`,
        adapterName: "导航任务",
        autoReconnect: true,
        onStatusChange: (snapshot) => {
          if (!disposed) transport.connectionChanged(snapshot.connected);
        },
      });
      transport.bind(adapter, source);
      void adapter.connect().catch(() => {
        if (!disposed) transport.connectionChanged(false);
      });
      cleanup(() => {
        disposed = true;
        transport.bind(null, source);
        adapter.disconnect();
      });
    },
    { immediate: true },
  );
  onBeforeUnmount(() => {
    stop();
    transport.dispose();
  });
  return { transport, status };
}
