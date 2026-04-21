# 项目结构

当前目录按“源码包 / 文档 / 扩展预留 / 构建产物”拆分，后续继续长大时不用再推倒重来。

## 推荐分层

- `src/ros_tool_suite/`
  Python 主源码。桌面壳、共享 UI、各工具页面都放这里。
- `src/ros_tool_suite/tools/`
  现有各个工具模块，后面继续加新工具时优先放这里。
- `docs/`
  结构说明、功能设计、后续迁移记录。
- `cpp/`
  预留给高性能核心模块。建议后面只放算法和引擎，不放 UI。
- `web/`
  预留给 Web 前端和服务端壳。建议后面放前端、API、静态资源。
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

建议保留一套单独前端壳，不要和 Python 桌面 UI 混写：

- `web/frontend/`
  页面、组件、静态资源。
- `web/backend/`
  本地 API 服务、任务调度、文件管理。

## 迁移原则

- 先保证“功能逻辑”和“界面”分离。
- 重计算部分再逐步下沉到 C++。
- 桌面版和 Web 版共用同一套核心处理逻辑。
