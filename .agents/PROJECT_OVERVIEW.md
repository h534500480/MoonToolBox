# 项目地图：ROS_PLATFROM

仅包含 PCD 转 PGM、PCD 切片、全局重定位候选点、ROS 定位导航测试、IMU 标定。默认首页是 platform 风格三维工作台。

## 优先入口

- frontend/src/App.vue：工具定义、异步页面、分模块任务结果；main.ts：路由。
- frontend/src/pages：页面组件覆盖五个模块，`ImuCalibrationPage.vue` 负责 rosbag2 db3 IMU Allan 标定。
- composables/useNavigationController.ts：原导航控制、初始位姿、目标下发、诊断、录制；connectionEnabled 控制显式接入。
- composables/useRelocalizationController.ts：候选点编辑、拖动、历史、参数及真实导出。
- components/Nav3DViewer.vue：ROS 显示对象、TF、体素、初始位姿和演示/真实接管；机器狗姿态帧由 ROS 接入设置的 `robot_tf_frame` 控制，默认 `body`；离线地图可在加载区选择占据网格、点云或渲染，并即时设置点云大小、点云颜色和占据网格颜色；lib/scene/platformArena.ts 负责默认场地与机器狗锚点；lib/ros/voxelGrowth.ts 负责离线 voxel GPU 生长动画。
- components/NavTopicPanelList.vue：真实话题生命周期、暂停/详情/排序/录制。
- lib/scene：参考 platform 的模型、动作、场地和候选演示；platform：演示与视觉状态。
- backend/app/catalog.py：五模块 allowlist；api/routes.py：API；services/cpp_runner.py：真实 C++ 调用；services/imu_calibration.py：Windows 本地读取 rosbag2 SQLite3 并计算 Allan 统计。
- cpp/CMakeLists.txt：四 CLI；tests/test_platform.py：独立 HTTP/C++ 回归。

## 运行与约定

开发前端 5180，后端/生产静态页面 8100。Python 用工作区 .venv，CLI 位于 cpp/build。配置、录制、测试输出受 ignore 管理。

本分支 worktree 与原工作区分离，原项目未跟踪文件未覆盖。旧首页、收藏、Python GUI、网络扫描、回放及其他导出已移除。当前保留 frontend/android 原生工程和本地文件/点云预览能力；网页构建资源须经 Capacitor sync 更新，Android 交互适配进度见 docs/ANDROID_ADAPTATION_PLAN.md。首轮容器/触屏能力分流、悬浮输入与导航文件/手势已接入，真机验收尚未完成。

IMU 标定工具 key 为 `imu_calibration`，路由 `/tools/imu-calibration`，左上角标题按钮可切换进入。当前支持 `sensor_msgs/msg/Imu` 或 `sensor_msgs/Imu` 且 `serialization_format=cdr` 的 rosbag2 SQLite3 `.db3`，不依赖 Windows 本机 ROS2；输出 gyro/accel 三轴 Allan deviation、noise density、random walk、bias instability 和 YAML 预览。部分驱动可能把 `linear_acceleration` 按 g 发布，页面当前按消息原单位展示。

演示点禁止导出；真实加载清除演示历史；断线不得静默恢复演示。狗 Y-up 模型转换为 ROS Z-up，真实姿态保留完整四元数。候选点拖动保持高度。

真实硬件、服务版本、长时录制和超大地图性能尚未验证。详细边界见 docs/WEB_ARCHITECTURE.md。

## 导航任务侧栏（2026-09-18）

- `pages/NavigationWorkspace.vue` 顶部定位/导航/建图仅切换 UI；共用 `Nav3DViewer`、ROS 会话及右下角位姿信息。`components/MappingWorkspace.vue` 提供 Super-LIO 建图工作台的前端流程骨架：实时采集或录包处理、LiDAR/IMU/TF/外参/时间连续性预检入口、话题绑定和 PCD/PLY、轨迹、配置快照产物说明；尚未接入真实 Super-LIO 启动、rosbag 解析、录制或导出。
- `components/NavigationTasks.vue` 管理任务、点位草稿、JSON 导入导出；本地存储键 `ros-platform.navigation-tasks.v1`。任务记录坐标系，不匹配当前场景时禁止编辑并隐藏连线。
- `lib/navigationTasks.ts` 定义 version 1 文件、TaskScene 和兼容局域网 HTTP 的编号生成；`lib/navigationRunner.ts` 管理执行快照、单点下发、反馈和暂停/继续/取消。NavigationTransport 提供 sendGoal/control/subscribe；`lib/rosNavigationTransport.ts` 已接默认 SCAN 的 /nav2_goal_request、/nav2_goal_context、/nav2_goal_control 和 /nav_ndt_status；useTaskNavigation 共享连接，navigationOwnership 提供同来源浏览器控制租约。仅同编号 reached+request_completed 推进；断流/定位失效停止队列推进并保留任务锁。无生产模拟模式。虚线仅表示点位顺序。
- Viewer 的 waypoint 模式复用初始化地面选点和变换控件，通过 taskPosePlaced 回调连续新增并自动保存，taskPoseChange 仅更新选中点；点击编号只切换控件目标。先选择取点方式，机器狗取点保留草稿确认；地图模式调整实时保存。机器狗当前位置要求真实连接及可解析位姿。
- `lib/scene/combinedPoseControls.ts` 统一平移与旋转指针仲裁：初始化与任务均同时显示平移和三轴旋转，拖动时锁定相机和阻尼。任务保存 XYZ 欧拉角 roll/pitch/yaw（rad），旧 version 1 文件缺失 roll/pitch 时补零。回归页面 `frontend/tests/combined-pose-controls.html`，浏览器脚本 `combined-pose-controls.test.cjs`。
- 回归：frontend 下运行 `node tests/navigation-tasks.test.mjs`、`node tests/navigation-runner.test.mjs`、`npm run typecheck`、`npm run build`。使用与接入约定见 `docs/NAVIGATION_TASKS.md`；刷新只恢复任务定义，不自动恢复执行。

- 导航点位编辑：NavigationTasks 支持列表拖放重排；Nav3DViewer 以屏幕距离拾取顺序线段，通过 TaskRouteInsertion 相邻编号校验插入位置。插点立即持久化，视角拖动和坐标轴操作不插点，运行任务仍锁定。

- 2026-09-22 位姿编辑：poseVisualScale.ts 统一距离平方根缩放并封顶，编号拾取和显示优先于组合坐标轴；选点后仅列表内平滑居中。插点朝向取前后路径切线角平分线。模型/HUD/任务取狗位姿共用 resolveRobotTfPose：配置 body 无任何样本时允许 base_link 完整链降级并明确提示，自定义坐标系不降级。

- 平台交互：platform/interaction.ts 集中识别 Android 原生容器、主指针触摸能力与紧凑布局，main.ts 安装；MobileInputOverlay.vue 在根层管理独立草稿和确认提交。Android MainActivity 发送 ros-window-insets，RosFilePickerPlugin 新增 readTaskText/saveTaskText。NavigationTasks 复用数据校验，桌面 HTML 拖放、触屏编号 Pointer 手柄；Viewer 触屏只对单指轻点执行选点，拖动/双指保留相机。App 工具目录加载结束仍缺失工具时显示能力不足入口，不无限等待。
- 布局预设：平台设置提供自动、3200×1440 横屏、常规手机、桌面布局；interaction.ts 保存 ros-platform.layout-preset.v1，mobile.css 按实际 CSS 视口统一三个模式的面板安全区和滚动。预设不改变三维渲染或 ROS 会话；常规手机建图在输入/产物面板间切换，窄屏话题抽屉打开时暂时隐藏监控面板以避免重叠。

## Windows 独立发行包

- `backend/desktop.py` 是 Nuitka standalone 编译入口，托盘与 Uvicorn 同进程。发行版仅监听 127.0.0.1，保留已绑定套接字并在首选端口占用时回退到系统端口；用户目录文件锁与随机实例标识避免误认其他服务。源码开发仍使用 backend/run.py。
- `backend/app/paths.py` 统一资源/用户数据路径；发行数据在 `%LOCALAPPDATA%/ROSPlatform/UserData`，静态资源与四个 CLI 在安装目录 runtime 下。`desktop_api.py` 仅发行版启用，持久化界面偏好和任务，排除控制租约；`frontend/src/main.ts` 先恢复偏好，再动态加载 bootstrap.ts 的 Vue 启动逻辑。
- `scripts/build_dist.ps1` 使用独立 Python 3.12 x64 构建环境、固定 requirements-package.txt、CMake Release 静态 MSVC、Nuitka（含 Tk/NumPy 依赖），按白名单汇集运行文件并审计源码与调试产物。`build_installer.ps1` / installer.iss 生成 ROSPlatformSetup.exe；便携 ZIP 同时保留。构建缓存与发行产物继续位于已忽略 build/、release/，不提交。
- 使用与验证见 docs/WINDOWS_DISTRIBUTION.md、tests/test_distribution.py、frontend/tests/desktop-distribution.test.cjs。C++/Python 编译不构成防逆向保证，浏览器端 JS 仍可访问。
