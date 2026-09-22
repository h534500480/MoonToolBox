<!-- 功能说明：复刻 platform 的工具启动器，支持外部点击、Escape 和键盘导航。 -->
<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount } from "vue";
import { useRoute } from "vue-router";
import { Map, Layers, Crosshair, Compass, ChevronDown, Activity } from "@lucide/vue";
const props = defineProps<{ compact?: boolean }>();
const route = useRoute();
const open = ref(false);
const host = ref<HTMLElement>();
const tools = [
  {
    path: "/tools/pcd-map",
    name: "PCD 转 PGM",
    description: "PCD 生成 SLAM 地图",
    icon: Map,
  },
  {
    path: "/tools/pcd-tile",
    name: "PCD 切片",
    description: "点云切片与 metadata",
    icon: Layers,
  },
  {
    path: "/tools/global-relocalization",
    name: "全局重定位候选点",
    description: "候选点生成与审核",
    icon: Crosshair,
  },
  {
    path: "/",
    name: "ROS 定位导航测试",
    description: "定位导航可视化工作台",
    icon: Compass,
  },
  {
    path: "/tools/imu-calibration",
    name: "IMU 标定",
    description: "Allan 方差与噪声参数",
    icon: Activity,
  },
];
function close(event: Event) {
  if (
    event instanceof KeyboardEvent
      ? event.key === "Escape"
      : !host.value?.contains(event.target as Node)
  )
    open.value = false;
}
onMounted(() => {
  document.addEventListener("pointerdown", close);
  document.addEventListener("keydown", close);
});
onBeforeUnmount(() => {
  document.removeEventListener("pointerdown", close);
  document.removeEventListener("keydown", close);
});
</script>
<template>
  <div ref="host" class="platform-launcher">
    <button
      class="launcher-button"
      :aria-expanded="open"
      aria-label="工具箱"
      @click="open = !open"
    >
      <span class="launcher-grid"><i v-for="i in 9" :key="i" /></span>
      <span
        ><strong>ROS测试平台</strong
        ><small v-if="!props.compact">ROBOTICS TEST PLATFORM</small></span
      ><ChevronDown :size="14" :class="{ rotated: open }" />
    </button>
    <Transition name="popover"
      ><nav
        v-if="open"
        class="glass-strong launcher-menu"
        aria-label="工具导航"
      >
        <div class="menu-title">工具箱 <span>05 TOOLS</span></div>
        <RouterLink
          v-for="tool in tools"
          :key="tool.path"
          :to="tool.path"
          :class="{ selected: route.path === tool.path }"
          @click="open = false"
          ><span class="tool-icon"
            ><component :is="tool.icon" :size="17" /></span
          ><span
            ><strong>{{ tool.name }}</strong
            ><small>{{ tool.description }}</small></span
          ></RouterLink
        >
      </nav></Transition
    >
  </div>
</template>
