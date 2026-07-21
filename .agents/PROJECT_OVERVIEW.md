# ROS Tool Suite 项目地图

## 项目用途

这是一个以 ROS 相关辅助工具为核心的混合工程，目标是把原先偏脚本/桌面工具的能力整理成可扩展的工具箱，当前主线是：

- `frontend/`：Vue + Vite 前端界面
- `backend/`：FastAPI 后端 API 与任务编排
- `cpp/`：性能敏感工具的 C++ CLI

同时保留了历史桌面入口：

- `tool_suite_gui.py`
- `src/ros_tool_suite/ui/desktop/`

## 核心目录与职责

- `frontend/`
  Web UI 与 Android Capacitor 壳。开发模式使用 `npm run dev`，发布模式产物输出到 `frontend/dist/`。
- `backend/`
  FastAPI 服务。`backend/run.py` 为启动入口，`backend/app/main.py` 负责挂载 `/api` 路由，并在存在 `frontend/dist/` 时托管静态前端。
- `backend/app/api/routes.py`
  统一 API 入口，包含健康检查、工具列表、偏好设置、ROS 数据源、文件操作与各工具执行路由。
- `backend/app/services/`
  工具执行、浏览器桥接、ROS 数据读取、录制文件管理等后端服务。
- `src/ros_tool_suite/`
  旧桌面壳与 Python 工具实现。根目录 `tool_suite_gui.py` 会把 `src/` 注入路径后调用 `ros_tool_suite.app.main()`。
- `cpp/`
  CMake 工程，当前关注 `pcd_map_cli`、`pcd_tile_cli`、`network_scan_cli`、`costmap_cli` 等命令行工具。
- `scripts/`
  本地安装、启动、停止、打包、安装包构建脚本。Windows 使用最直接。
- `data/`、`backend/data/`
  模块开关、偏好设置、ROS 数据源等运行配置。

## 关键入口与运行链路

### Web / 本机主线

1. `scripts/install_local.ps1`
   创建 `.venv/`、安装 Python 依赖、必要时构建 `cpp/build/*.exe`、安装前端依赖并生成 `frontend/dist/`。
2. `scripts/start_local.ps1`
   优先使用 `runtime/python/python.exe`，否则使用 `.venv/Scripts/python.exe`。
   启动 `scripts/tray_launcher.py`，由托盘脚本拉起 `backend/run.py`。
3. `backend/run.py`
   启动 Uvicorn，默认监听 `0.0.0.0:8000`。
4. `backend/app/main.py`
   注册 `/api` 路由，并在存在 `frontend/dist/` 时直接托管 Web 页面。

### 开发态分离运行

- 后端：`python .\backend\run.py`
- 前端：`cd .\frontend && npm run dev`

### 旧桌面入口

- `python .\tool_suite_gui.py`

该入口仍可启动旧 Tkinter 桌面壳，但 README 已明确说明它不是当前主线。

## 依赖关系与数据流

- 前端通过 `/api` 调用后端。
- Android / 移动端 ROS 工作台优先直接连接 rosbridge WebSocket，不依赖本机 FastAPI 后端读取 ROS 数据；页面主视图、状态卡、话题浏览、运行参数读取和消息下发共用 `frontend/src/lib/ros/liveAdapter.ts` 的共享连接。
- `frontend/src/lib/ros/directRosClient.ts` 保留 rosapi 直连兜底能力；当传入共享 `RosLiveAdapter` 时，话题列表、轻量探测和参数读取复用现有 WebSocket。
- 后端根据工具类型调用：
  - `backend/app/services/*.py`
  - `cpp/build/*.exe`
  - 部分旧 Python 实现
- 配置开关由 `backend/data/tool_modules.json` 控制，影响 `/api/tools` 返回结果和工具执行可用性。
- 偏好与分组持久化在 `backend/data/tool_preferences.json`。

## 本机测试前提

- Windows 环境最直接，脚本大量使用 `.cmd` / PowerShell。
- 完整首次安装通常需要：
  - Python 3.10+
  - Node.js LTS
  - CMake
  - 可用的 C++ 编译工具链
- 如果仓库已带 `cpp/build/*.exe` 与 `frontend/dist/`，则本机测试门槛会明显降低。
- `scripts/start_local.ps1` 可绕开系统 Python 版本不足的问题，只要 `.venv/` 或 `runtime/python/` 可用。

## 已确认的当前仓库状态

- 已存在 `frontend/dist/`
- 已存在 `cpp/build/pcd_map_cli.exe`、`pcd_tile_cli.exe`、`network_scan_cli.exe`、`costmap_cli.exe`
- 已存在 `.venv/Scripts/python.exe`
- `backend/app/main.py` 确认会托管 `frontend/dist/`

## 易错点与阅读优先级

1. README 中同时存在旧桌面版、Web 版、Android 版三条线，判断“当前主线”时应优先以 `frontend + backend + cpp` 为准。
2. 系统 `python` 版本不一定满足要求，但项目自己的 `.venv` 或发行版运行时可能已经满足。
3. `.codexignore` 默认忽略构建产物与本机数据；只在确认运行条件时才有必要查看这些目录。
4. Android 目录位于 `frontend/android/`，但它依赖前端构建结果与局域网后端，不代表项目只能在 Android 上验证。
5. 移动端 rosbridge 不可达时，共享连接会有限自动重连并在达到上限后暂停；排查连接问题时优先查看 `RosNavAppPage.vue` 的共享连接配置和 `liveAdapter.ts` 的重连参数。
