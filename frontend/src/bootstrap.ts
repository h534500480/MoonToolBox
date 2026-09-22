// 功能说明：启动平台 Vue 应用与历史路由。
import { createApp } from "vue";
import { createRouter, createWebHistory } from "vue-router";
import App from "./App.vue";
import "./styles.css";
import { installInteractionCapabilities } from "./platform/interaction";
import "./platform/mobile.css";
installInteractionCapabilities();
const router = createRouter({
  history: createWebHistory(),
  routes: [
    "/",
    "/tools/pcd-map",
    "/tools/pcd-tile",
    "/tools/global-relocalization",
    "/tools/imu-calibration",
  ].map((path) => ({ path, component: { render: () => null } })),
});
createApp(App).use(router).mount("#app");
