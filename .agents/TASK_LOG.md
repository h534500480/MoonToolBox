# 任务日志

## 2026-08-19

- 任务目标：把 `main` 分支最近的 ROS 导航优化项和新增数据类型同步到安卓分支。
- 修改文件：
  - `frontend/src/App.vue`
  - `frontend/src/components/Nav3DViewer.vue`
  - `frontend/src/components/NavTopicPanelList.vue`
  - `frontend/src/components/ToolForm.vue`
  - `frontend/src/lib/ros/liveAdapter.ts`
  - `.agents/PROJECT_OVERVIEW.md`
  - `.agents/TASK_LOG.md`
- 主要变更：
  - 合并 `main` 到安卓开发分支时，保留路由化 Android 入口和共享连接架构，同时吸收主线的有限次自动重连、订阅限流参数支持与服务调用超时能力。
  - 同步导航测试页对 `visualization_msgs/msg/Marker`、`scan_planner_msgs/msg/Bspline`、`geometry_msgs/msg/Twist` 等新增显示类型的接入能力，以及对应主视图优化。
  - 保留安卓端 `buildSharedRosKey()` 统一 shared key 逻辑，并让主视图与话题小窗都沿用主线的重连参数。
  - 更新项目地图，补充 Android 主线和导航调试能力说明。
- 风险、限制或尚未验证项：
  - 前端构建验证结果需以本次任务结束时的实际执行结果为准。
  - 尚未在真实 Android 设备和真实 rosbridge 环境下做在线联调。

## 2026-08-12

- 任务目标：接入 SCAN-Planner 推荐测试话题到 `ros_nav_test`，让新的消息类型可以直接添加到三维主视图进行可视化调试。
- 修改文件：
  - `frontend/src/lib/ros/displayRegistry.ts`
  - `frontend/src/components/ToolForm.vue`
  - `frontend/src/components/Nav3DViewer.vue`
  - `.agents/PROJECT_OVERVIEW.md`
  - `.agents/TASK_LOG.md`
- 主要变更：
  - 扩展主视图显示类型识别，新增 `visualization_msgs/msg/Marker`、`scan_planner_msgs/msg/Bspline`、`geometry_msgs/msg/Twist`；同时把 `nav_msgs/msg/Odometry` 归入现有位姿显示通道。
  - 在导航测试页默认可选话题清单中加入 SCAN-Planner 推荐的关键话题。
  - 三维主视图新增 SCAN 相关渲染能力，包括 `Marker`、`Bspline` 和 `Twist`。
- 风险、限制或尚未验证项：
  - `scan_planner_msgs/msg/Bspline` 当前采用前端近似采样，仅用于调试轨迹形态。

## 2026-07-21

- 任务目标：收敛移动端 ROS APP 的多连接设计，并修复 rosbridge 不可达时持续自动重连的问题。
- 修改文件：
  - `frontend/src/lib/ros/liveAdapter.ts`
  - `frontend/src/lib/ros/directRosClient.ts`
  - `frontend/src/lib/ros/mobileAppState.ts`
  - `frontend/src/components/RosNavAppPage.vue`
  - `frontend/src/components/Nav3DViewer.vue`
  - `frontend/src/components/NavTopicPanelList.vue`
- 主要变更：
  - 为 `RosLiveAdapter` 增加统一的 `callService()` 能力，让 rosapi / 参数服务调用可以复用现有 websocket 连接。
  - 把移动端状态卡、话题浏览、运行参数读取和消息发布统一到共享 rosbridge 连接。
  - 增加连接序号校验、失败 socket 主动关闭和有限次数自动重连，避免弱网时继续堆积连接。
- 风险、限制或尚未验证项：
  - 尚未在真实安卓设备和真实 rosbridge 环境下验证底层连接数量与 `CLOSE-WAIT` 变化。

## 2026-06-28

- 任务目标：评估当前项目是否可以直接在电脑上进行本机测试。
- 修改文件：
  - `.agents/PROJECT_OVERVIEW.md`
  - `.agents/TASK_LOG.md`
- 主要变更：
  - 新建项目地图，记录当前主线架构、关键入口、运行链路与本机测试前提。
- 已确认：
  - `frontend/dist/` 已存在，可由后端直接托管。
  - `cpp/build/` 已存在关键 CLI 可执行文件。
- 风险、限制或尚未验证项：
  - 未逐项验证每个工具功能是否都能成功执行。
