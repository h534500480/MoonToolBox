/**
 * 功能说明：
 * 为 ROS Android APP 提供 Capacitor 基础配置，便于后续同步 Android 工程并打包 APK。
 */
import type { CapacitorConfig } from "@capacitor/cli";

const config: CapacitorConfig = {
  appId: "com.moontoolbox.rosnav",
  appName: "MoonToolBox ROS Nav",
  webDir: "dist",
  bundledWebRuntime: false,
  server: {
    // Android 端通过 http 本地源加载页面，避免 WebView 把局域网 ws://rosbridge 视为混合内容拦截。
    androidScheme: "http",
    cleartext: true,
  },
};

export default config;
