# 任务记录

## 2026-06-28

- 任务目标：评估当前项目是否可以直接在电脑上进行本机测试。
- 修改文件：
  - `.agents/PROJECT_OVERVIEW.md`
  - `.agents/TASK_LOG.md`
- 主要变更：
  - 新建项目地图，记录当前主线架构、关键入口、运行链路与本机测试前提。
  - 记录本次本机可测性检查结论与已确认事实。
- 已确认：
  - `frontend/dist/` 已存在，可由后端直接托管。
  - `cpp/build/` 已存在 `pcd_map_cli.exe`、`pcd_tile_cli.exe`、`network_scan_cli.exe`、`costmap_cli.exe`。
  - `.venv/Scripts/python.exe` 可用，版本为 `Python 3.13.4`。
  - 使用 `.venv` 临时启动 `backend/run.py` 后，`http://127.0.0.1:8000/api/health` 和 `http://127.0.0.1:8000/` 均返回 `200`。
- 风险、限制或尚未验证项：
  - 系统 `python` 仅为 `3.8.4`，不满足 README 中的 `3.10+` 要求；若绕开 `.venv` 直接使用系统 Python，可能失败。
  - 未实际验证旧 Tkinter 桌面壳 `python .\\tool_suite_gui.py` 是否仍可完整使用。
  - 未逐项验证每个工具功能是否都能成功执行；当前仅确认后端与首页可启动、静态页面可访问、关键构建产物已存在。

## 2026-07-21

- 任务目标：修复移动端 rosbridge 不可达时持续自动重连可能堆积连接、导致 rosbridge 后续难以恢复连接的问题。
- 修改文件：
  - `frontend/src/lib/ros/liveAdapter.ts`
  - `frontend/src/components/RosNavAppPage.vue`
- 主要变更：
  - 为 rosbridge 实时连接增加连接序号校验，忽略已经被替换或关闭的旧 WebSocket 回调，避免过期事件反向污染当前状态。
  - 在首次连接错误和握手超时时主动关闭当前 `ROSLIB.Ros` socket，减少目标不可达时遗留半关闭连接的概率。
  - 增加 `reconnectMaxAttempts` 配置；移动端共享连接设置为最多自动重试 5 次、2 秒起步、最长 30 秒退避，失败后暂停自动重连，等待用户主动重新测试或刷新连接。
- 已确认：
  - `cd frontend && npm run build` 构建通过。
- 风险、限制或尚未验证项：
  - 尚未在真实安卓设备和真实 rosbridge 上复现并观察 `ss/netstat` 中 `CLOSE-WAIT` 数量变化。
  - 浏览器或 WebView 的底层 TCP 关闭仍受系统网络栈影响，本次修复重点是避免前端继续叠加新连接和旧回调。

- 任务目标：收敛移动端 ROS APP 的多连接设计，把状态卡、话题浏览、参数读取、消息发布统一到共享 rosbridge 连接。
- 修改文件：
  - `frontend/src/lib/ros/liveAdapter.ts`
  - `frontend/src/lib/ros/directRosClient.ts`
  - `frontend/src/lib/ros/mobileAppState.ts`
  - `frontend/src/components/RosNavAppPage.vue`
  - `frontend/src/components/Nav3DViewer.vue`
  - `frontend/src/components/NavTopicPanelList.vue`
- 主要变更：
  - 为 `RosLiveAdapter` 增加统一的 `callService()` 能力，让 rosapi / 参数服务调用可以直接复用现有 websocket 连接。
  - 把移动端状态卡从独立 `createRosLiveAdapter()` 改为复用共享连接，不再额外建立单独 websocket。
  - 把移动端的话题浏览、连接检测、运行参数读取改为优先复用页面共享连接，不再每次通过 `directRosClient` 新建短连接。
  - 把移动端消息发布从“每次下发单独建连再断开”改为复用页面共享连接。
  - 统一主视图、小窗、移动端页面的共享 key 生成逻辑，避免不同模块未来拼接不一致。
  - 调整移动端底部交互布局，把初始化定位 / 导航目标按钮栏上移到图层抽屉上方的自适应间距位置。
  - 把图层管理中的数值输入改成“编辑态字符串缓存，失焦或回车后再提交并做范围收敛”，避免手机键盘输入 `0.06`、清空重输等场景被原生 `number` 输入限制打断。
  - 收紧移动端键盘联动逻辑，只滚动最近的配置面板或图层抽屉内容区，避免整页 UI 被 `scrollIntoView()` 一起推走，并在键盘收回时由容器自行恢复可见区域。
  - 修正移动端连接状态文案，把 `inspectResult.status === "error"` 从“未检测”区分为“检测失败”，并让“测试连接”优先使用配置窗当前草稿值，而不是强制依赖已应用配置。
  - 把“测试连接”从全量话题枚举改成 `/rosapi/get_time` 轻量探测，避免在手机链路下因为全量 topic 列表过大而误报失败。
  - 保留“话题浏览”全量读取，但单独把 rosapi 读取超时放宽到 `15000ms`，降低大 ROS 图场景下的超时概率。
- 已确认：
  - `cd frontend && npm run build` 构建通过。
- 风险、限制或尚未验证项：
  - 尚未连接真实 rosbridge 在线验证“手机 APP 打开后是否只剩单一底层 websocket、`CLOSE-WAIT` 是否明显减少”。
  - `directRosClient` 仍保留独立建连兜底能力；当前只是让移动端主路径优先复用共享连接，未删除全部直连分支。
  - 连接配置窗当前改成草稿态输入，只有点“应用并返回”才会真正写回连接配置；该行为已更稳，但尚未在真实手机输入法下逐项走完交互验证。
