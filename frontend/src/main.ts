// 功能说明：先恢复发行版跨端口偏好，再加载业务模块，避免初始化读到空任务。
import { restoreDesktopProfile } from "./platform/desktopProfile";

restoreDesktopProfile().finally(() => import("./bootstrap"));
