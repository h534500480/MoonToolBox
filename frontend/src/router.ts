/**
 * 功能说明：
 * 为桌面工作台和 ROS Android 工作台提供统一路由入口。
 */
import { createRouter, createWebHashHistory } from "vue-router";

import DesktopWorkbench from "./components/DesktopWorkbench.vue";
import RosNavAppPage from "./components/RosNavAppPage.vue";

const rosAppPages = ["home", "config", "main", "topics", "runtime"] as const;

export const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    {
      path: "/",
      redirect: "/ros-app/main",
    },
    {
      path: "/desktop",
      name: "desktop-home",
      component: DesktopWorkbench,
    },
    {
      path: "/ros-app/:page?",
      name: "ros-nav-app",
      component: RosNavAppPage,
      props: (route) => {
        const page = typeof route.params.page === "string" ? route.params.page : "main";
        return {
          initialPage: rosAppPages.includes(page as typeof rosAppPages[number]) ? page : "main",
        };
      },
    },
  ],
});
