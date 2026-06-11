import { createApp } from "vue";
import { Capacitor } from "@capacitor/core";
import { StatusBar } from "@capacitor/status-bar";

import App from "./App.vue";
import { router } from "./router";
import "./styles.css";

async function initNativeUiChrome() {
  // Android 端默认进入沉浸式工作区，避免系统状态栏占用横屏主视图空间。
  if (!Capacitor.isNativePlatform() || Capacitor.getPlatform() !== "android") {
    return;
  }
  try {
    await StatusBar.setOverlaysWebView({ overlay: true });
    await StatusBar.hide();
  } catch (error) {
    console.warn("failed to hide status bar", error);
  }
}

void initNativeUiChrome();

createApp(App).use(router).mount("#app");
