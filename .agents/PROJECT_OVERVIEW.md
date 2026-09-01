# 项目地图

## 项目用途

ROS Tool Suite 是一个面向 ROS 地图处理、定位导航调试、网络扫描和离线数据处理的个人工具箱。当前主线是 `frontend/ + backend/ + cpp/`：Vue 前端负责工具页面和交互，FastAPI 后端负责统一 API 和本地能力封装，C++ CLI 承担地图与感知相关的重计算任务。

## 核心目录

- `frontend/`：Vue + Vite 前端。`src/App.vue` 管理工具列表、分区、收藏和主题；`src/components/ToolForm.vue` 根据工具 key 渲染具体工具页面；`src/components/Nav3DViewer.vue` 是 ROS 定位导航三维主视图；`src/components/GlobalRelocalizationCandidateTool.vue` 是全局重定位候选点审核工具页框架。
- `backend/`：FastAPI 后端。`app/catalog.py` 定义工具清单；`app/api/routes.py` 暴露工具执行、偏好、文件、ROS 数据源等 API；`app/services/` 封装具体本地服务，其中 `global_relocalization.py` 负责全局重定位候选点 PCD 预览、候选点读取和人工编辑文件导出。
- `cpp/`：C++ 核心和 CLI，包括 PCD 地图生成、切片、全局重定位候选点生成、costmap 回放、网络扫描等性能敏感逻辑。
- `src/ros_tool_suite/`：早期 Python 桌面工具和兼容入口。
- `scripts/`：本地启动、安装、构建和发行脚本。
- `backend/data/tool_modules.json`：运行时工具模块启用开关，影响 `/api/tools` 返回结果；该文件属于本地状态并被 `.gitignore` 忽略。`data/tool_modules.json` 是仓库内保留的模块开关样例/旧路径文件。

## 关键入口

- Web 后端：`python .\backend\run.py`
- Web 前端：`cd .\frontend && npm run dev`
- 桌面兼容入口：`python .\tool_suite_gui.py`
- 生产构建：`cd .\frontend && npm run build`

## 工具分区与偏好

前端默认分区包含 `全部工具 / 收藏夹 / 地图处理 / 网络工具 / 感知工具 / 娱乐分区 / 其他工具`。工具实际分区可通过偏好持久化到 `backend/data/tool_preferences.json`；默认归类逻辑在 `frontend/src/App.vue` 的 `defaultSectionForTool` 中。

## 当前工具接入方式

1. 在 `backend/app/catalog.py` 增加 `ToolDefinition`。
2. 在运行环境的 `backend/data/tool_modules.json` 打开对应 key；若该文件不存在，`catalog.py` 会按工具定义生成默认启用配置。
3. 如需专用页面，在 `frontend/src/components/ToolForm.vue` 中按 `tool.key` 分支挂载组件。
4. 如需真实后端执行，在 `backend/app/api/routes.py` 的 `/tools/{tool_key}/run` 分支接入服务或 CLI。

## 网络扫描工具

- 工具 key 为 `network_scan`，Web 主线走 `backend/app/services/network_scan.py`，不是 `cpp_runner.py` 中的 C++ 备用封装。
- 当前扫描分两阶段：先按 IP 范围并发执行系统 ping 获取连通性，再一次性读取 ARP 表并只对在线/ARP 发现的设备补全主机名、MAC、ARP 类型和 SSH(22) 状态。
- 主机名解析优先使用反向 DNS，其次用 `zeroconf` 浏览 mDNS/Avahi/Bonjour 常见服务补全 Ubuntu 等 `.local` 名称，Windows 下最后用 `nbtstat -A` 做 NetBIOS 兜底；因此能看到的名称取决于 DNS/PTR、mDNS、NetBIOS、设备自身和网络策略，不保证所有在线设备都有名字。

## ROS 实时连接

- `frontend/src/lib/ros/liveAdapter.ts` 是前端 rosbridge 实时连接的统一封装，支持 mock、rosbridge、共享连接、topic 订阅、topic 发布和 rosapi 服务调用。
- `ros_nav_test` 页面中的三维主视图、话题小窗和链路延迟窗口共用同一个 rosbridge shared key，避免同一页面重复建立 WebSocket。
- 弱网或 rosbridge 不可达时，共享连接会主动关闭失败 socket，并使用有限次数的慢退避自动重连；达到上限后暂停，等待用户手动重连，避免持续重试影响机器人侧网络和 SSH 会话。
- `frontend/src/lib/ros/displayRegistry.ts` 负责把 topic 类型映射到主视图显示类型；当前三维主视图除 `PointCloud2 / OccupancyGrid / Path / TF / Pose / PoseArray / LaserScan` 外，还支持 `visualization_msgs/msg/Marker`、`scan_planner_msgs/msg/Bspline` 和 `geometry_msgs/msg/Twist`，便于直接调试 SCAN-Planner 一类带自定义轨迹与 Marker 可视化的话题。Pose 和 PoseArray 在 `Nav3DViewer.vue` 中按消息的 position.z 和完整 quaternion 渲染三维位姿；右下角“机器狗位置”HUD 默认从 `/display/tf` 解析 `base_link` 到 fixed frame 的链路，聚焦/障碍区锚点继续使用 x/y/z/yaw 摘要。
- `frontend/src/components/Nav3DViewer.vue` 中的 Marker 支持当前已覆盖 SCAN-Planner 调试常用形状：`ARROW / SPHERE / CYLINDER / LINE_STRIP / LINE_LIST / SPHERE_LIST`；`scan_planner_msgs/msg/Bspline` 当前按前端近似采样成折线显示，用于快速判断局部轨迹走势，不追求与规划器内部求值完全一致。
- `ros_nav_test` 的初始化定位已从松手即发布的平面流程改为 3D 候选预览流程：在 `Nav3DViewer.vue` 中拖拽生成候选箭头，`ToolForm.vue` 可临时订阅点云 topic 抓取下一帧并绑定到候选位姿，主视图用 Three.js `TransformControls` 支持平移/旋转微调，确认后再发布 `/initialpose` 并清理箭头、控件和点云资源。点云绑定会优先借助 TF 转成 `base_link` 局部快照，TF 不足时退回原始局部坐标并提示。
- `ros_nav_test` 支持离线地图 PCD 预览和初始化地面吸附：前端在导航页选择 `offline_map_pcd`、`offline_map_yaml`、点云下采样、占据 voxel 尺寸和最大点数，后端 `/api/tools/ros_nav_test/offline-map-preview` 调用 C++ `nav_pcd_preview_cli.exe` 读取并体素下采样 PCD，同时解析 `map.yaml` 中的 `image/resolution/origin` 和 PGM 宽高，并用下采样点云按独立的 `offline_map_occupancy_voxel_m` 构建稀疏三维占据缓存；预览响应会返回占据 voxel 中心点，`Nav3DViewer.vue` 默认用 Three.js `InstancedMesh` 显示占据网格，也可在左上角切回下采样点云显示。`/api/tools/ros_nav_test/offline-map-raycast` 根据前端相机射线查找可靠地面命中点和法线。初始化拖拽时 yaw 仍由用户拖拽方向决定，z 使用命中地面高度加 `initial_pose_base_height_offset_m`，roll/pitch 由地面法线决定；射线无可靠命中时回退旧平面逻辑。`/api/files/pgm-image` 会把 PGM 转成 PNG 供 Three.js 贴到 map 坐标平面。`Nav3DViewer.vue` 按 map 坐标渲染离线地图和 PGM 参考底图，并在画布左上角提供六面裁剪按钮，移动包围盒上下、左右、前后边界以隐藏局部地图。

## 全局重定位候选点工具

工具 key 为 `global_relocalization_candidates`，属于地图处理分区。当前实现范围是离线数据库生成前的审核工作台：

- 后端接口：
  - `/api/tools/global_relocalization_candidates/pcd-preview`：读取 ASCII/binary PCD 的 `x/y/z` 采样点。
  - `/api/tools/global_relocalization_candidates/candidates`：读取 `candidates.csv` 或 `candidates.npy [N,16]`。
  - `/api/tools/global_relocalization_candidates/manual-export`：导出 `manual_candidates.yaml` 和 `reviewed_candidates.csv`。
  - `/api/tools/global_relocalization_candidates/final-export`：旧的 Python 占位导出入口已停用，避免误生成全 0 descriptor。
- 前端页面：`frontend/src/components/GlobalRelocalizationCandidateTool.vue`，支持三维预览、点击/框选、删除到回收站、锁定点、人工加点、删除区域和 MD 参数草案。
- 确认候选点行为：若页面已加载候选点，则前端通过 `/run` 提交当前最终候选列表，后端写临时 reviewed CSV 并调用 C++ CLI 的 `--candidates` 模式，基于输入 PCD 重新计算 v2 `candidates.npy/descriptors.npy/ring_keys.npy/sector_keys.npy`；若尚未加载候选点，则调用 C++ CLI 从 PCD 自动采样并计算描述子。
- C++ CLI：`cpp/build/global_relocalization_cli.exe`，源码在 `cpp/src/mapping/global_relocalization.cpp` 和 `cpp/src/global_relocalization_cli/main.cpp`。当前已实现 PCD 读取、体素/占据栅格、ground 支撑、clearance 检查、候选 base 采样、manual additions/deletions、reviewed CSV 候选输入、virtual LiDAR first-return ray casting、高度版 Scan Context descriptor、ring key、sector key、观测质量指标、`candidates.csv/candidates.npy/descriptors.npy/ring_keys.npy/sector_keys.npy` 和 `debug/preview_candidates.pcd` 输出。
- 离线数据库 v2 格式：`candidates.npy` 为 `float32 [P,16]`，每个可站立位置只占一行，不再按 yaw 展开；第 0 列为 `place_id`，第 6 列为 `canonical_yaw_deg` 且当前统一为 `0.0`。`descriptors.npy` 为 `float32 [P,num_rings,num_sectors]`，`ring_keys.npy` 为 `float32 [P,num_rings]`，`sector_keys.npy` 为 `float32 [P,num_sectors]`；ring key 和 sector key 分别由 descriptor 按 sector/ring 最大值生成。默认离线 synthetic LiDAR 参数对齐当前在线 query：`min_range_m=0.30`、`vertical_fov_deg=59.0`、`horizontal_step_deg=2.0`、`vertical_step_deg=2.0`、`lidar_to_base_translation_xyz=[0,0,0]`、`lidar_to_base_rpy_deg=[0,0,0]`、`occupancy_inflate_radius_m=0.15`，metadata 记录 `format: v2_scan_context_places`、`synthetic_lidar` 和 `scan_context` 合约字段。descriptor 只使用每条射线的 first-return，`ray_cast` 命中第一个占据体素后立即返回，不写入同条射线后方墙、柱子或边界。自动候选会用 `base_link_height_offset_m` 将 ground z 转成候选 `base_link` z，默认偏移为 `0.35m`；前端新打的人工点在 reviewed CSV 中标记 `z_frame=ground`，C++ 写库前同样按该偏移转换到 `base_link` 高度，从已有最终库加载的候选默认视为 `z_frame=base_link`。
- 尚未实现/限制：当前 C++ descriptor 为单线程基础版，尚未做 OpenMP/std::thread 并行优化；真实大地图和高分辨率虚拟 LiDAR 下可能需要继续提速。

## 注意事项

- `.codexignore` 已排除依赖、构建产物、后端本地数据和输出目录，扫描前必须先遵守该过滤范围。
- `frontend/dist/`、`build/`、`output*/`、`logs/` 等为产物或本地状态，不作为常规阅读对象。
- 新增代码注释按根目录 `AGENTS.md` 要求使用中文，重要入口要说明用途和边界。
