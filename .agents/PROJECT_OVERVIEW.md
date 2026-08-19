# 项目地图

## 项目用途

ROS Tool Suite 是一个面向 ROS 地图处理、定位导航调试、网络扫描和离线数据处理的个人工具箱。当前主线是 `frontend/ + backend/ + cpp/`：Vue 前端负责工具页面和交互，FastAPI 后端负责统一 API 和本地能力封装，C++ CLI 承担地图与感知相关的重计算任务。

## 核心目录

- `frontend/`：Vue + Vite 前端。`src/App.vue` 作为路由出口，当前同时承载桌面工作台和 Android ROS 工作台入口；`src/components/ToolForm.vue` 根据工具 key 渲染具体工具页面；`src/components/Nav3DViewer.vue` 是 ROS 定位导航三维主视图；`src/components/GlobalRelocalizationCandidateTool.vue` 是全局重定位候选点审核工具页。
- `frontend/android/`：Capacitor Android 工程。依赖前端构建产物同步到 `app/src/main/assets/public/`，用于安卓端打包和联调。
- `backend/`：FastAPI 后端。`app/catalog.py` 定义工具清单；`app/api/routes.py` 暴露工具执行、偏好、文件、ROS 数据源等 API；`app/services/` 封装具体本地服务，其中 `global_relocalization.py` 负责全局重定位候选点 PCD 预览、候选点读取和人工编辑文件导出。
- `cpp/`：C++ 核心和 CLI，包括 PCD 地图生成、切片、全局重定位候选点生成、costmap 回放、网络扫描等性能敏感逻辑。
- `src/ros_tool_suite/`：早期 Python 桌面工具和兼容入口。
- `scripts/`：本地启动、安装、构建和发行脚本。
- `backend/data/tool_modules.json`：运行时工具模块启用开关，影响 `/api/tools` 返回结果；该文件属于本地状态并被 `.gitignore` 忽略。`data/tool_modules.json` 是仓库内保留的模块开关样例/旧路径文件。

## 关键入口

- Web 后端：`python .\backend\run.py`
- Web 前端：`cd .\frontend && npm run dev`
- Android 构建前同步：`cd .\frontend && npm run build`
- 桌面兼容入口：`python .\tool_suite_gui.py`

## 当前工具接入方式

1. 在 `backend/app/catalog.py` 增加 `ToolDefinition`。
2. 在运行环境的 `backend/data/tool_modules.json` 打开对应 key；若该文件不存在，`catalog.py` 会按工具定义生成默认启用配置。
3. 如需专用页面，在 `frontend/src/components/ToolForm.vue` 中按 `tool.key` 分支挂载组件。
4. 如需真实后端执行，在 `backend/app/api/routes.py` 的 `/tools/{tool_key}/run` 分支接入服务或 CLI。

## ROS 实时连接与 Android 主线

- `frontend/src/lib/ros/liveAdapter.ts` 是前端 rosbridge 实时连接的统一封装，支持 mock、rosbridge、共享连接、topic 订阅限流、topic 发布和 rosapi 服务调用。
- Android / 移动端 ROS 工作台优先直接连接 rosbridge WebSocket，不依赖本机 FastAPI 后端去代读 ROS 数据；页面主视图、状态卡、话题浏览、参数读取和消息下发共用同一 shared key，避免同页重复建连。
- `frontend/src/lib/ros/directRosClient.ts` 保留 rosapi 直连兜底能力；当调用方传入共享 `RosLiveAdapter` 时，话题列表、轻量探测和参数读取优先复用现有 WebSocket。
- 弱网或 rosbridge 不可达时，共享连接会主动关闭失败 socket，并使用有限次数的慢退避自动重连；达到上限后暂停，等待用户手动重连，避免持续重试拖垮机器人侧网络和 SSH 会话。

## 导航测试可视化能力

- `frontend/src/lib/ros/displayRegistry.ts` 负责把 topic 类型映射到主视图显示类型。
- 当前三维主视图除 `PointCloud2 / OccupancyGrid / Path / TF / Pose / PoseArray / LaserScan` 外，还支持 `visualization_msgs/msg/Marker`、`scan_planner_msgs/msg/Bspline`、`geometry_msgs/msg/Twist`，便于直接调试 SCAN-Planner 一类带自定义轨迹与 Marker 可视化的话题。
- `frontend/src/components/Nav3DViewer.vue` 中的 Marker 当前已覆盖 SCAN-Planner 调试常用形状：`ARROW / SPHERE / CYLINDER / LINE_STRIP / LINE_LIST / SPHERE_LIST`；`scan_planner_msgs/msg/Bspline` 当前按前端近似采样成折线显示，用于快速判断局部轨迹走势，不追求与规划器内部求值完全一致。

## 全局重定位候选点工具

工具 key 为 `global_relocalization_candidates`，属于地图处理分区。当前实现范围是离线数据库生成前的审核工作台：

- 后端接口：
  - `/api/tools/global_relocalization_candidates/pcd-preview`
  - `/api/tools/global_relocalization_candidates/candidates`
  - `/api/tools/global_relocalization_candidates/manual-export`
- 前端页面：`frontend/src/components/GlobalRelocalizationCandidateTool.vue`
- C++ CLI：`cpp/build/global_relocalization_cli.exe`，源码在 `cpp/src/mapping/global_relocalization.cpp` 和 `cpp/src/global_relocalization_cli/main.cpp`

## 注意事项

- `.codexignore` 已排除依赖、构建产物、后端本地数据和输出目录，扫描前必须先遵守该过滤范围。
- `frontend/dist/`、`build/`、`output*/`、`logs/` 等为产物或本地状态，不作为常规阅读对象。
- 新增代码注释按根目录 `AGENTS.md` 要求使用中文，重要入口要说明用途和边界。
