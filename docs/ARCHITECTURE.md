# 项目结构

当前目录按“源码包 / 文档 / 扩展预留 / 构建产物”拆分，后续继续长大时不用再推倒重来。

## 推荐分层

- `src/ros_tool_suite/`
  旧 Python 桌面源码。当前主要作为兼容层保留，Web 主线不再从这里扩展新功能。
- `src/ros_tool_suite/tools/`
  早期 Tkinter 工具模块。后续只做维护或迁移参考，新增 Web 工具优先放到 `frontend/`、`backend/` 和 `cpp/`。
- `docs/`
  结构说明、功能设计、后续迁移记录。
- `cpp/`
  预留给高性能核心模块。建议后面只放算法和引擎，不放 UI。
- `frontend/`
  当前 Web 主线前端，负责页面、参数、状态、日志和工具交互。
- `backend/`
  当前 Web 主线后端，负责 API、偏好设置、任务入口和本地资源访问。
- `web/`
  早期预留目录，当前不作为主线开发目录。
- `scripts/`
  构建、打包、开发辅助脚本。
- `build/`, `dist/`
  PyInstaller 构建产物。
- `output/`
  当前工具默认输出目录。

## 后续扩展建议

### Python

- `src/ros_tool_suite/app.py`
  桌面主入口和页面路由。
- `src/ros_tool_suite/shared_ui.py`
  统一主题、控件样式、日志样式。
- `src/ros_tool_suite/tools/*.py`
  单个功能页。

### C++

建议以后按能力拆，而不是按页面拆：

- `cpp/pointcloud/`
  点云解析、下采样、切片、栅格化。
- `cpp/mapping/`
  地图生成、障碍物膨胀、可行走区域提取。
- `cpp/common/`
  公共数据结构、日志、配置。

Python 或 Web 后面都可以调用这些模块。

### Web

当前 Web 主线已经固定为根目录下的前后端分离结构，不再放到 `web/` 子目录：

- `frontend/`
  页面、组件、静态资源。
- `backend/`
  本地 API 服务、任务调度、文件管理。

## 迁移原则

- 先保证“功能逻辑”和“界面”分离。
- 重计算部分再逐步下沉到 C++。
- 桌面版和 Web 版共用同一套核心处理逻辑。
- 旧桌面文件体量较大，迁移前不直接搬目录；若拆分文件，必须同步更新 `src/ros_tool_suite/tools/registry.py`、打包脚本和 README。
