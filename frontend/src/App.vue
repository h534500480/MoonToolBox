<!-- 功能说明：四模块平台入口，默认直接进入 ROS 三维工作台。 -->
<script setup lang="ts">
import { computed, defineAsyncComponent, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { fetchTools, runTool } from "./api/client";
import type { ToolDefinition } from "./types";
import MobileInputOverlay from "./components/MobileInputOverlay.vue";
const NavigationWorkspace = defineAsyncComponent(
  () => import("./pages/NavigationWorkspace.vue"),
);
const MappingPage = defineAsyncComponent(
  () => import("./pages/MappingPage.vue"),
);
const RelocalizationWorkspace = defineAsyncComponent(
  () => import("./pages/RelocalizationWorkspace.vue"),
);
const ImuCalibrationPage = defineAsyncComponent(
  () => import("./pages/ImuCalibrationPage.vue"),
);
const route = useRoute();
const fallbackRosNavTool: ToolDefinition = {
  key: "ros_nav_test",
  title: "ROS测试平台",
  subtitle: "手机直连机器狗 rosbridge",
  description: "无需电脑后端时，直接在前端连接机器狗 IP 并解析 ROS 话题。",
  primary_action: "连接",
  secondary_action: "刷新",
  fields: [
    {
      key: "ros_provider",
      label: "接入方式",
      value: "rosbridge",
      placeholder: "rosbridge",
    },
    {
      key: "ros_bridge_url",
      label: "Bridge 地址",
      value: "",
      placeholder: "ws://192.168.1.100:9090",
    },
    {
      key: "ros_api_service",
      label: "rosapi 服务",
      value: "/rosapi/topics_and_raw_types",
      placeholder: "/rosapi/topics_and_raw_types",
    },
    {
      key: "timeout_ms",
      label: "超时 ms",
      value: "8000",
      placeholder: "8000",
    },
    {
      key: "fixed_frame",
      label: "固定坐标系",
      value: "map",
      placeholder: "map",
    },
    {
      key: "robot_tf_frame",
      label: "机器人 TF 坐标系",
      value: "body",
      placeholder: "body",
    },
    {
      key: "map_topic",
      label: "地图 Topic",
      value: "/map",
      placeholder: "/map",
    },
    {
      key: "pose_topic",
      label: "定位 Topic",
      value: "/ndt_pose",
      placeholder: "/ndt_pose",
    },
    {
      key: "path_topic",
      label: "路径 Topic",
      value: "/plan",
      placeholder: "/plan",
    },
    {
      key: "offline_map_pcd",
      label: "离线地图 PCD",
      value: "",
      placeholder: "选择本机 PCD",
    },
    {
      key: "offline_map_yaml",
      label: "map.yaml",
      value: "",
      placeholder: "选择 map.yaml",
    },
    {
      key: "offline_map_pgm",
      label: "map.pgm",
      value: "",
      placeholder: "选择 map.pgm",
    },
    {
      key: "offline_map_voxel_leaf_m",
      label: "离线点云下采样 m",
      value: "0.20",
      placeholder: "0.20",
    },
    {
      key: "offline_map_occupancy_voxel_m",
      label: "占据 voxel m",
      value: "0.30",
      placeholder: "0.30",
    },
    {
      key: "offline_map_max_points",
      label: "离线点云最大点数",
      value: "60000",
      placeholder: "60000",
    },
    {
      key: "offline_map_max_voxels",
      label: "占据最大 voxel",
      value: "60000",
      placeholder: "60000",
    },
    {
      key: "offline_map_display_mode",
      label: "离线地图显示方式",
      value: "voxel",
      placeholder: "voxel",
    },
    {
      key: "offline_map_point_size",
      label: "离线点云大小",
      value: "0.06",
      placeholder: "0.06",
    },
    {
      key: "offline_map_point_color",
      label: "离线点云颜色",
      value: "#d7dee8",
      placeholder: "#d7dee8",
    },
    {
      key: "offline_map_voxel_color",
      label: "占据网格颜色",
      value: "#a79d86",
      placeholder: "#a79d86",
    },
    {
      key: "initial_pose_base_height_offset_m",
      label: "初始化 base 高度偏移 m",
      value: "0.35",
      placeholder: "0.35",
    },
    {
      key: "initial_pose_ground_normal_radius_m",
      label: "初始化地面法线半径 m",
      value: "0.80",
      placeholder: "0.80",
    },
    {
      key: "initial_pose_ground_max_slope_deg",
      label: "初始化最大地面坡度 °",
      value: "30",
      placeholder: "30",
    },
  ],
};
const tools = ref<ToolDefinition[]>([]),
  error = ref("");
const catalogLoaded = ref(false);
const jobs = ref<
  Record<
    string,
    {
      loading: boolean;
      summary: string;
      logs: string[];
      resultData: Record<string, any>;
    }
  >
>({});
const key = computed(() =>
  route.path === "/tools/pcd-map"
    ? "pcd_map"
    : route.path === "/tools/pcd-tile"
      ? "pcd_tile"
      : route.path === "/tools/global-relocalization"
        ? "global_relocalization_candidates"
        : route.path === "/tools/imu-calibration"
          ? "imu_calibration"
          : "ros_nav_test",
);
const tool = computed(() => tools.value.find((t) => t.key === key.value));
const job = computed(
  () =>
    jobs.value[key.value] || {
      loading: false,
      summary: "",
      logs: [],
      resultData: {},
    },
);
async function load() {
  error.value = "";
  catalogLoaded.value = false;
  try {
    tools.value = await fetchTools();
  } catch (e) {
    tools.value = [fallbackRosNavTool];
    if (key.value !== "ros_nav_test") {
      error.value = `后端连接失败：${(e as Error).message}`;
    }
  } finally {
    catalogLoaded.value = true;
  }
}
/** 按启动时的模块保存结果，切页不会把异步结果写入另一模块。 */
async function execute(values: Record<string, string>) {
  const id = key.value;
  if (jobs.value[id]?.loading) return;
  jobs.value[id] = {
    loading: true,
    summary: "正在执行…",
    logs: [],
    resultData: {},
  };
  const state = jobs.value[id];
  try {
    const result = await runTool(id, values);
    Object.assign(state, {
      summary: result.summary,
      logs: result.logs,
      resultData: result.data || {},
    });
  } catch (e) {
    state.summary = (e as Error).message;
    state.logs = [state.summary];
  } finally {
    state.loading = false;
  }
}
onMounted(load);
</script>
<template>
  <MobileInputOverlay />
  <div v-if="catalogLoaded && !tool" class="startup-error glass-strong">
    <h1>ROS 测试平台</h1>
    <p>
      {{
        error ||
        "当前环境未提供此工具所需的计算服务。PCD 转换、切片、重定位计算和 IMU 标定需要连接后端，不能仅在 Android 本机运行。"
      }}
    </p>
    <button class="primary-btn" @click="load">重新连接后端</button>
    <RouterLink to="/">返回定位与导航</RouterLink>
  </div>
  <component
    v-else-if="tool"
    :is="
      key === 'ros_nav_test'
        ? NavigationWorkspace
        : key === 'global_relocalization_candidates'
          ? RelocalizationWorkspace
          : key === 'imu_calibration'
            ? ImuCalibrationPage
            : MappingPage
    "
    :key="key"
    :tool="tool"
    v-bind="job"
    @run="execute"
    @clear-logs="job.logs.splice(0)"
  />
  <div v-else class="startup-error">正在载入平台…</div>
</template>
