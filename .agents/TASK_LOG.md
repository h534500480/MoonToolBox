# 任务日志

## 2026-09-21：取消初始化定位点云历史帧回退

- 目标：避免 ROS 节点停止发布后，初始化定位仍使用主视图最后收到的旧点云帧。
- 修改文件：`frontend/src/composables/useNavigationController.ts`、`frontend/src/components/Nav3DViewer.vue`、`.agents/TASK_LOG.md`。
- 主要变更：删除 `attachInitialPoseLatestPointCloud` 及其调用；点击“刷新点云帧”后仅订阅并接受操作开始后的下一帧。15 秒内未收到新帧会明确提示确认 ROS 节点仍在发布。
- 验证：`frontend` 下 `npm run typecheck`、`npm run build` 通过；构建保留既有大于 500 kB 的分包警告。

## 2026-09-21：离线地图点云显示外观配置

- 目标：让离线地图加载区可明确设置占据网格/点云显示方式，以及点云大小、点云颜色和占据网格颜色。
- 修改文件：`frontend/src/App.vue`、`backend/app/catalog.py`、`frontend/src/pages/NavigationWorkspace.vue`、`frontend/src/composables/useNavigationController.ts`、`frontend/src/components/Nav3DViewer.vue`、`frontend/src/lib/ros/offlineVoxelRender.ts`、`frontend/src/styles.css`、`.agents/PROJECT_OVERVIEW.md`、`.agents/TASK_LOG.md`。
- 主要变更：新增四个持久化 ROS 接入选项 `offline_map_display_mode`、`offline_map_point_size`、`offline_map_point_color`、`offline_map_voxel_color`；加载区增加“显示外观”配置组。已加载地图变更大小或颜色时直接更新 Three.js 几何/材质，无需重新读取 PCD；占据网格配色改为从用户所选主色生成稳定明暗变化。
- 验证：`frontend` 下 `npm run typecheck`、`npm run build` 通过；构建保留既有大于 500 kB 的分包警告。
- 限制：未使用现场 PCD 进行视觉验收；显示方式和外观设置随“保存配置”写入 ROS 数据源配置，离线 PCD 文件本身仍需用户手动加载。

## 2026-09-21：机器人 TF 坐标系改为 ROS 接入配置

- 目标：解决现场 `/display/tf` 发布 `base_link` 而前端固定查询 `body`，导致机器狗位姿不可用的问题。
- 修改文件：`frontend/src/App.vue`、`frontend/src/pages/NavigationWorkspace.vue`、`frontend/src/composables/useNavigationController.ts`、`frontend/src/components/Nav3DViewer.vue`、`backend/app/catalog.py`、`.agents/PROJECT_OVERVIEW.md`、`.agents/TASK_LOG.md`。
- 主要变更：ROS 接入设置新增“机器人 TF 坐标系”，默认 `body`；配置会同时保存到本地缓存和后端 ROS 数据源配置。三维 HUD、场景机器狗和导航任务“机器狗取点”统一读取该字段；空值及旧配置均兼容回退到 `body`，并清除输入的前导 `/`。
- 补充：该输入框改为前端 ROS 接入面板固定渲染，不再依赖后端工具目录热重载；后端尚未重启时也会显示，重启后不会重复出现。
- 补充：`/display/tf` 的历史节点筛选不会再隐藏当前“机器人 TF 坐标系”；三维主视图始终渲染该选中帧。现场只读订阅已确认其中持续包含 `base_link`。
- 补充：已发现历史主视图布局可能完全没有 TF 显示项；加载与刷新话题时会自动补入 `/display/tf`，避免三维场景没有 TF 渲染入口。
- 根因修复：现场 `/display/tf` 的 ROS 时间与浏览器系统时间相差约 76 天，旧代码用两者比较并在 30 秒后删除刚收到的 TF。现在新增 `receivedAtMs`，缓存淘汰按浏览器实际接收时间计算；ROS 时间戳仍只用于同一 ROS 时间线内的变换匹配。
- 验证：`frontend` 下 `npm run typecheck` 与 `npm run build` 已通过；现场 rosbridge 已只读确认 `/display/tf` 包含 `base_link`。构建保留既有大包提示。

## 2026-09-09：ROS_PLATFROM 四模块重构

- 用户确认后创建 ROS_PLATFROM 分支及 G:/ros_proj/ros_platform 工作树，原工作区及未跟踪文件保持。
- 新增 frontend/src/pages、composables、lib/scene、platform，以 Vue/Three.js 移植参考页面、模型、动作和轨迹；新增玻璃抽屉、平台导航和监控交互。
- 对接原导航、候选点、地图和切片；补齐候选点拖动/多选/锁定/回收站/姿态编辑/历史及话题暂停/排序/详情/录制。
- 修改 catalog、routes、cpp_runner、main、CMake 和启动脚本：仅保留四模块，默认输出随工作区，独立使用 5180/8100，支持静态页面刷新。
- 移除旧首页/收藏配置、Python GUI、无关网络/回放/导出代码和 Android 产物；必要 ROS/文件服务与算法保留。旧历史可在原分支查阅。
- 更新 README、架构和项目地图；新增四项集成回归与本地 rosbridge 替身。
- 已验证：类型检查、生产构建、四 CLI 编译、HTTP/C++ 回归；浏览器页面对照、地图生成、候选点导入/拖动/撤销/锁定/导出和本地 ROS 接管。
- 限制：真实机器人、现场服务/网络、长时录制、超大地图和安装包发布尚未验证。未提交或推送。
- 收尾修正：真实轨迹使用固定容量 GPU 缓冲区；补齐状态栏真实遥测和消息超时状态；更新依赖补丁后 npm audit 为 0 项漏洞。
- 生产版 ROS 替身复测确认完整运动轨迹，浏览器无 error/warn；联调服务已停止，默认地址恢复为 ws://127.0.0.1:9090。

## 2026-09-09：ROS 测试页交互与样式修正

- 任务目标：修复 ROS 测试平台 HUD 溢出、列表滚动条样式、话题拖拽新增、主视图显示项样式和地图默认显示问题。
- 修改文件：frontend/src/pages/NavigationWorkspace.vue、frontend/src/components/NavTopicPanelList.vue、frontend/src/composables/useNavigationController.ts、frontend/src/components/Nav3DViewer.vue、frontend/src/styles.css、frontend/src/monitor.css。
- 主要变更：话题拖拽同时写入 text/ros-topic 与 text/plain，真实监控卡片 drop 优先识别外部话题新增，避免满列表时被卡片排序事件截断；HUD 改为内容自适应并限制长文本；全局滚动条隐藏箭头和轨道背景，仅保留滑块；真实监控卡、右侧话题卡和主视图显示项统一为 platform 玻璃卡片风格；默认主视图补入 /map 栅格地图，离线地图加载后强制同步体素渲染模式。
- 已验证：frontend 下 npm run build 通过；本机 127.0.0.1:5180 页面可打开，程序化检查 status-hud 无横向溢出，三维 canvas 为 1280x720 且非零尺寸。
- 限制：未连接真实 ROS 环境复测 /map OccupancyGrid 实时消息渲染，拖拽新增在真实连接后的完整鼠标路径仍需现场确认。

## 2026-09-09：离线点云渲染模式迁移

- 任务目标：把 ros_tool main 中残留但未接入的非透明 voxel 渲染模式恢复，并迁移到 ros_platform。
- 修改文件：frontend/src/lib/ros/offlineVoxelRender.ts、frontend/src/components/Nav3DViewer.vue、frontend/src/composables/useNavigationController.ts、frontend/src/pages/NavigationWorkspace.vue、.agents/TASK_LOG.md。
- 主要变更：新增暮光光照/阴影渲染工具，离线地图显示模式扩展为“占据网格 / 点云 / 渲染”；加载离线地图后默认切到“渲染”；切换模式或清空地图时恢复原 Three.js 材质、背景、tone mapping 和阴影配置。
- 已验证：frontend 下 `npm run typecheck` 通过；`npm run build` 通过，仍有 NavigationWorkspace/OrbitControls 大 chunk 常规警告。
- 限制：尚未用真实离线 PCD 与用户截图做现场目视对照。

## 2026-09-09：离线点云渲染光照校正

- 任务目标：修正 ros_tool main 与 ros_platform 当前分支中离线地图渲染模式过暗、材质不接近参考图的问题。
- 修改文件：frontend/src/lib/ros/offlineVoxelRender.ts、.agents/TASK_LOG.md。
- 主要变更：提高 voxel 实例色明度/饱和度，改为偏米黄与灰绿的实体表面；增加暖色环境光和冷色补光；保留投影但关闭 voxel 自接收阴影，减少密集体素黑块。
- 已验证：ros_tool frontend `npm run build` 通过；ros_platform frontend `npm run typecheck` 与 `npm run build` 通过，仍有大 chunk 常规警告。
- 限制：尚未用真实离线 PCD 在浏览器中目视微调最终光照观感。

## 2026-09-09：离线点云渲染亮度二次校正

- 任务目标：继续修正离线地图渲染模式整体仍然发黑的问题。
- 修改文件：frontend/src/lib/ros/offlineVoxelRender.ts、.agents/TASK_LOG.md。
- 主要变更：进一步抬高 voxel 实例色亮度；为标准材质加入暖色 emissive 基底；提高 tone mapping 曝光、环境光、半球光、主光和补光强度，使体素不再完全依赖场景光照才可读。
- 已验证：ros_tool frontend `npm run build` 通过；ros_platform frontend `npm run typecheck` 与 `npm run build` 通过，仍有大 chunk 常规警告。
- 限制：尚未通过浏览器截图进行最终观感验收。

## 2026-09-09：离线点云渲染自发光回退与光照排查

- 任务目标：去掉自发光方案，确认离线地图渲染过暗是否来自后处理、tone mapping 或光照链路。
- 修改文件：frontend/src/lib/ros/offlineVoxelRender.ts、.agents/TASK_LOG.md。
- 主要变更：搜索确认前端未使用 EffectComposer、Bloom、ShaderPass 等后处理；撤销材质 emissive；将渲染模式从 MeshStandardMaterial 改为 MeshLambertMaterial；将 ACESFilmicToneMapping 改为 LinearToneMapping；阴影改为 PCFSoftShadowMap 且保持 autoUpdate。
- 已验证：ros_tool frontend `npm run build` 通过；ros_platform frontend `npm run typecheck` 与 `npm run build` 通过，仍有大 chunk 常规警告。
- 限制：尚未通过浏览器截图进行最终光照验收。

## 2026-09-09：离线点云渲染纯黑修复

- 任务目标：修复撤销自发光后离线地图渲染模式变成纯黑的问题。
- 修改文件：frontend/src/lib/ros/offlineVoxelRender.ts、frontend/src/components/Nav3DViewer.vue、.agents/TASK_LOG.md。
- 主要变更：渲染模式材质不再启用 vertexColors；停止写入 instanceColor，让 InstancedMesh 只承载 voxel 位置；使用固定米黄色 MeshLambertMaterial 配合真实灯光，排除实例色属性异常导致颜色被乘黑的问题。
- 已验证：ros_tool frontend `npm run build` 通过；ros_platform frontend `npm run typecheck` 与 `npm run build` 通过，仍有大 chunk 常规警告。
- 限制：尚未通过浏览器截图确认最终观感。

## 2026-09-09：离线点云渲染实验回退

- 任务目标：按用户要求回退后续光照/材质实验，恢复到“main 分支和当前分支光照模式不太对”之前的渲染状态。
- 修改文件：frontend/src/lib/ros/offlineVoxelRender.ts、frontend/src/components/Nav3DViewer.vue、.agents/TASK_LOG.md。
- 主要变更：恢复 MeshStandardMaterial、vertexColors、voxelSurfaceColor、ACESFilmicToneMapping、原始三灯布光、PCF 阴影和静态阴影贴图策略；重新接回 voxel 实例色写入；保留“渲染”显示模式入口、默认加载渲染和模式切换能力。
- 已验证：ros_tool frontend `npm run build` 通过；ros_platform frontend `npm run typecheck` 与 `npm run build` 通过，仍有大 chunk 常规警告。
- 限制：尚未继续调整光照问题，当前仅回退到用户指定的修改前状态。

## 2026-09-09：离线体素颜色通道与平台灯光组修复

- 任务目标：定位离线渲染体素近黑、与旧版暮光效果不一致的原因。
- 修改文件：frontend/src/lib/ros/offlineVoxelRender.ts、frontend/tests/offline-voxel-render.html、.agents/TASK_LOG.md。
- 已确认根因：BoxGeometry 没有顶点 color 属性，却启用了 vertexColors；Three.js 将缺失的顶点色与已有 instanceColor 相乘，导致底色近黑。现在根据几何属性启用顶点色，保留 voxelSurfaceColor 实例配色、Standard 材质、ACES、原有曝光与三灯参数。
- 主要变更：递归记录并关闭场景内已有灯光，覆盖 platformArena 的嵌套灯光组；退出离线渲染时恢复原可见状态，避免两套照明叠加。
- 已验证：浏览器真实 WebGL 对照测试通过，相同照明下样本中心 RGB 从 [2,1,0] 恢复到 [151,134,94]；嵌套灯光隔离、原隐藏灯光状态、材质及渲染器状态恢复通过；npm run typecheck、npm run build 通过（仍有大 chunk 提示）。测试入口为 Vite 开发服务 /tests/offline-voxel-render.html，不进入生产入口。
- 限制：使用单体素回归样本验证根因，用户截图中的完整地图最终观感尚未验证；未更改后台功能，未启动或停止服务。

## 2026-09-09：主视图地图显示项自动补齐

- 任务目标：修复连接 rosbridge 后 `/map` 没有出现在主视图显示项、主界面看不到地图的问题。
- 修改文件：frontend/src/composables/useNavigationController.ts、frontend/src/components/Nav3DViewer.vue、.agents/TASK_LOG.md。
- 主要变更：加载保存布局后不再完全信任旧 `nav_layout_json`，若主视图缺少 `map` 类型显示项，会自动补入 `/map`；刷新 ROS 话题成功或失败后也会执行同样补齐，避免历史保存布局导致地图长期缺失；OccupancyGrid 渲染支持普通数组和 TypedArray 数据。
- 已验证：frontend 下 `npm run typecheck` 与 `npm run build` 通过，仍有大 chunk 常规警告。
- 限制：尚未连接现场 rosbridge 目视确认 `/map` 消息是否按预期渲染；若现场 `/map` 本身未发布或 frame 无法转换，仍需看三维主视图状态/日志。

## 2026-09-09：真实话题监控卡片样式对齐

- 任务目标：修复连接 ROS 前后的左侧话题监控标题和小卡片操作按钮样式不一致的问题。
- 修改文件：frontend/src/components/NavTopicPanelList.vue、frontend/src/monitor.css、.agents/TASK_LOG.md。
- 主要变更：确认连接前使用 DemoDock、连接后使用 NavTopicPanelList；为真实监控 compact 模式补齐“话题监控”标题栏和整体收起按钮；真实小卡片头部改为与演示卡一致的拖拽手柄、topic 标题、状态点、hover 图标按钮组；保留真实订阅、暂停、折叠、录制保存、删除和详情抽屉逻辑。
- 已验证：frontend 下 `npm run typecheck` 与 `npm run build` 通过，仍有大 chunk 常规警告。
- 限制：右侧 ROS 话题列表仍是 NavigationWorkspace 内的独立模板，仅保留连接后的多选、刷新、批量监控和批量 3D 交互，未在本次改成独立复用组件。

## 2026-09-09：离线 voxel 生长动画与地图淡入淡出

- 任务目标：复刻 G:\test\ros-test-platform 中 VoxelMap.tsx 的点云加载扩散生长效果，并接入 ros_platform 的离线点云加载、体素/渲染切换和 ROS map 替换。
- 修改文件：frontend/src/lib/ros/voxelGrowth.ts、frontend/src/lib/ros/offlineVoxelRender.ts、frontend/src/components/Nav3DViewer.vue、.agents/PROJECT_OVERVIEW.md、.agents/TASK_LOG.md。
- 主要变更：新增 GPU shader 生长材质，按水平距离、层号和随机扰动生成实例延迟，voxel 底面固定并沿 ROS Z-up 方向向上生长；离线占据网格和渲染模式共用该动画，切换模式时重新播放且不改 camera/controls；重复加载离线点云时旧地图 0.45s 淡出，新地图同步生长；ROS OccupancyGrid 更新时旧 map 淡出、新 map 淡入。
- 已验证：frontend 下 `npm run typecheck` 与 `npm run build` 通过，仍有 NavigationWorkspace/OrbitControls 大 chunk 常规警告。
- 限制：尚未连接真实 rosbridge 或加载现场 PCD 做浏览器目视验收；ROS `/map` 是 2D OccupancyGrid，没有离线 voxel 高度数据，本次只做新旧地图淡入淡出，不伪造三维生长体素。

## 2026-09-09：离线 voxel 过渡细节修正

- 任务目标：修正离线 voxel 生长过渡中背景/光照硬切、渲染终态材质变化、裁剪重复触发动画的问题。
- 修改文件：frontend/src/lib/ros/offlineVoxelRender.ts、frontend/src/components/Nav3DViewer.vue、.agents/TASK_LOG.md。
- 主要变更：渲染模式进入时按生长进度渐变背景、曝光、平台灯光和暮光灯光；shader 只作为过渡材质，动画结束后切回上一版 MeshStandardMaterial 暮光渲染效果；恢复 voxel 实例缩放和实例色写入；裁剪只更新可见实例并直接进入完成态，不再重播生长动画，只有加载新离线点云和切换 voxel/render 模式会触发过渡。
- 已验证：frontend 下 `npm run typecheck` 与 `npm run build` 通过，仍有 NavigationWorkspace/OrbitControls 大 chunk 常规警告。
- 限制：尚未在浏览器中用用户现场 PCD 截图确认渐变观感是否完全贴近 G:\test\ros-test-platform 的 1-4 帧效果。

## 2026-09-09：离线 voxel 过渡锚点与正反渐变

- 任务目标：按用户反馈消除渲染模式终态材质闪变、默认场景切点云跳变，以及 render 与非 render 模式之间反向缺少环境渐变的问题。
- 修改文件：frontend/src/lib/scene/platformArena.ts、frontend/src/lib/ros/voxelGrowth.ts、frontend/src/lib/ros/offlineVoxelRender.ts、frontend/src/components/Nav3DViewer.vue、.agents/PROJECT_OVERVIEW.md、.agents/TASK_LOG.md。
- 主要变更：渲染模式改为 MeshStandardMaterial 单材质体系，通过 onBeforeCompile 注入底部锚定生长逻辑，动画结束不再切换材质；默认场地和离线点云仍在同一 scene 中，加载过渡期间锁定 demo controls 约束并保留机器狗视觉锚点，演示场地逐步淡出；voxel 延迟中心改为当前机器狗/controls target；render 环境渐变抽为独立 0-1 状态，进入和退出都用同一套 clamp/lerp，退出 render 不再瞬间恢复背景和灯光。
- 已验证：frontend 下 `npm run typecheck` 与 `npm run build` 通过，仍有 NavigationWorkspace/OrbitControls 大 chunk 常规警告。
- 限制：尚未通过浏览器录屏逐帧对照 G:\test\ros-test-platform 的 1-4 帧效果；默认机器狗作为离线地图视觉锚点是过渡表现层逻辑，不代表真实 ROS 位姿。

## 2026-09-09：机器狗相机跟随与三模式互切过渡

- 任务目标：修正真实位姿到来时机器狗瞬移、相机相对位置跳变，以及点云/体素/渲染三种模式互切时展示场景被错误拉回的问题。
- 修改文件：frontend/src/lib/scene/platformArena.ts、frontend/src/components/Nav3DViewer.vue、.agents/TASK_LOG.md。
- 主要变更：机器狗从默认展示位姿到真实 pose 时使用 position lerp 与 quaternion slerp，避免收到位姿后直接刷新；离线地图加载过渡期间 camera position 与 controls target 同步平移，保持相机和机器狗相对静止；展示场地淡出只在从默认展示态首次加载地图时启用，点云/体素/渲染互切不会再显示展示场地；三模式互切增加当前对象淡出、目标对象淡入，只在两种目标显示之间过渡。
- 已验证：frontend 下 `npm run typecheck` 与 `npm run build` 通过，仍有 NavigationWorkspace/OrbitControls 大 chunk 常规警告。
- 限制：尚未用真实 rosbridge 位姿流与离线 PCD 在浏览器中目视确认相机跟随速度是否需要继续调参。

## 2026-09-10：占据网格模式恢复

- 任务目标：修复从渲染模式切到占据网格时先出现渲染过渡、随后占据网格消失的问题。
- 修改文件：frontend/src/lib/ros/offlineVoxelRender.ts、frontend/src/components/Nav3DViewer.vue、.agents/TASK_LOG.md。
- 主要变更：offlineVoxelRender 新增 restoreMeshMaterial，退出渲染模式时立即恢复 voxel shader 材质，只保留背景/光照做反向渐变；恢复占据网格材质后主动重置 uFade 和 uTime，避免之前点云/体素互切淡出把 shader 透明度留在 0。
- 已验证：frontend 下 `npm run typecheck` 与 `npm run build` 通过，仍有 NavigationWorkspace/OrbitControls 大 chunk 常规警告。
- 限制：尚未在浏览器中用真实离线地图目视确认占据网格切换观感。

## 2026-09-10：主视图显示项卡片化

- 任务目标：修复主视图显示项抽屉中条目和配置散落、摘要并列显示过多导致难以识别的问题。
- 修改文件：frontend/src/pages/NavigationWorkspace.vue、frontend/src/styles.css、.agents/TASK_LOG.md。
- 主要变更：移除“当前主视图显示 N 项”的长文本摘要 chips；每个显示项改为紧凑卡片，主行整合类型、名称、topic 和消息类型，移除按钮改为 hover 显示；颜色、点大小、Hz、透明度、TF 等配置默认收起，鼠标悬停或键盘聚焦时展开。
- 已验证：frontend 下 `npm run typecheck` 与 `npm run build` 通过，仍有 NavigationWorkspace/OrbitControls 大 chunk 常规警告。
- 限制：尚未在浏览器中目视微调抽屉宽度下的最长 topic 截断效果。

## 2026-09-10：诊断与离线地图面板卡片化

- 任务目标：按主视图显示项的整理方向，修复诊断界面接入检测、录制文件、链路延迟，以及平台设置离线地图中的样式和排版松散问题。
- 修改文件：frontend/src/pages/NavigationWorkspace.vue、frontend/src/styles.css、.agents/TASK_LOG.md。
- 主要变更：为离线地图设置区增加专用样式作用域；离线地图字段、加载动作和显示模式改为统一卡片分组；链路延迟的话题编辑、图例、录制入口和图表区域收束为紧凑条目；录制文件列表、预览和图表改为左右卡片化浏览布局；接入检测的配置键值、检测结果、能力和提示统一为卡片/标签样式。
- 已验证：frontend 下 `npm run typecheck` 与 `npm run build` 通过，仍有 NavigationWorkspace/OrbitControls 大 chunk 常规警告。
- 限制：尚未在浏览器中逐项目视确认四个抽屉在真实数据量下的 hover、截断和滚动表现。

## 2026-09-11：机器狗腿部关节方向修正

- 任务目标：修正默认机器狗动画中腿部关节反向折叠的问题。
- 修改文件：frontend/src/lib/scene/platformRobot.ts、.agents/TASK_LOG.md。
- 主要变更：腿部定义增加前后腿折叠方向，保留原对角步态相位；前腿与后腿的小腿/大腿旋转方向改为镜像折叠，避免四条腿都按同一方向形成反关节观感。
- 已验证：frontend 下 `npm run typecheck` 与 `npm run build` 通过，仍有 NavigationWorkspace/OrbitControls 大 chunk 常规警告。
- 限制：尚未在浏览器中逐帧目视确认不同视角下的腿部动态观感。

## 2026-09-11：ROS 话题点云发光配置

- 任务目标：为主视图中通过 ROS 话题接入的点云显示项增加自发光效果，并把强度配置放到显示项小卡片上。
- 修改文件：frontend/src/lib/ros/displayRegistry.ts、frontend/src/composables/useNavigationController.ts、frontend/src/pages/NavigationWorkspace.vue、frontend/src/components/Nav3DViewer.vue、.agents/TASK_LOG.md。
- 主要变更：NavViewerDisplay 新增 pointEmissiveIntensity；点云显示项小卡片新增“发光”强度输入；保存布局读取、默认显示项和配置更新链路保留该字段；实时 PointCloud2 渲染按强度提亮颜色并在强度大于 0 时启用 additive blending，分层配色会同步重算颜色 buffer。
- 已验证：frontend 下 `npm run typecheck` 与 `npm run build` 通过，仍有 NavigationWorkspace/OrbitControls 大 chunk 常规警告。
- 限制：Three.js PointsMaterial 没有 emissive 字段，本次以点材质颜色增强和叠加混合实现视觉自发光；尚未连接真实 rosbridge 目视确认不同强度下的现场观感。

## 2026-09-16：三维机器狗位姿改用 body TF

- 任务目标：将三维主场景机器狗位置从 `/display/tf` 的 `base_link` 改为读取 `body`。
- 修改文件：frontend/src/components/Nav3DViewer.vue、frontend/src/lib/ros/liveAdapter.ts、.agents/TASK_LOG.md。
- 主要变更：新增统一的 robotPoseFrame=`body`，机器狗姿态解析和底部 HUD 均使用 `body`；本地模拟适配器的 TF child_frame_id 同步改为 `body`，保持模拟链路和真实链路一致。
- 已验证：frontend 下 `npm run typecheck` 与 `npm run build` 通过，仍有 NavigationWorkspace/OrbitControls 大 chunk 常规警告。
- 限制：初始化点云局部转换仍保留 `base_link` 语义，未随本次机器狗显示位姿变更一起修改。

## 2026-09-11：三面板样式统一与离线裁剪坐标轴人性化

- 任务目标：统一「离线地图裁剪」「离线地图点云」「主视图显示项」三个面板的玻璃卡片风格与布局，并把裁剪坐标轴做得更易识别、可精调。
- 修改文件：frontend/src/components/Nav3DViewer.vue、frontend/src/pages/NavigationWorkspace.vue、frontend/src/styles.css、frontend/src/monitor.css、.agents/TASK_LOG.md。
- 主要变更：裁剪面板改为标题+分段控件+等轴测立方体线框+六个带轴向标签的胶囊手柄（X 橙/Y 绿/Z 蓝）+三行实时范围读数+重置按钮；新增 offlineClipBoundsView 响应式镜像在加载/清除/重置/设置边界四处同步读数；手柄由 span 改为 button 并接入方向键微调（复用原空置的 moveOfflineClipFace），pointerdown 后自动聚焦；离线点云表单拆分“文件来源/采样与占据参数”分组，数字参数改两列网格（label 在上、输入框全宽）；操作区改纵向排列并补上此前缺失的 .segmented-control 分段控件样式，状态消息允许换行不再截断；主视图显示项把支持类型标签与“当前显示 N 项”计数合并为一行，管理按钮移至标题右上，显示项卡片头部简化为 类型/名称/删除 三列，话题移入悬停展开行。
- 已验证：frontend 下 `npm run typecheck` 与 `npm run build` 通过；本机 5180 开发页实测：真实 PCD 加载成功，裁剪面板六手柄渲染与 X+ 拖拽读数变化、重置恢复均生效，显示项面板布局正常，console 无报错。
- 限制：方向键微调与 Y/Z 手柄拖拽未逐项实测；700px 以下窄屏断点仅静态检查未目视确认。

## 2026-09-11：右侧工具栏互斥展开与控制抽屉分组重排

- 任务目标：按用户反馈修复主视图多余箭头、离线裁剪面板改为放射状箭头并可缩起挂靠、与话题列表互斥展开，以及定位导航控制抽屉布局拥挤问题。
- 修改文件：frontend/src/components/Nav3DViewer.vue、frontend/src/pages/NavigationWorkspace.vue、frontend/src/styles.css、.agents/TASK_LOG.md。
- 主要变更：删除主视图无样式的 focus 罗盘按钮（与底部"重置视角"重复）；裁剪坐标轴由立方体线框改为中心 hub + 六向放射箭头，hover/点击亮起所在轴并与读数行联动；右上角新增数据驱动的竖排工具按钮栏（sideTools 注册表，新增面板只需追加定义），话题列表与地图裁剪面板互斥展开，加载离线地图自动切到裁剪面板、清除后回落话题列表；Nav3DViewer 新增 offlineClipPanelOpen prop 由父组件面板状态控制；定位导航控制抽屉重排为"任务控制/运动控制/初始位姿候选/手动输入位姿"四个分组卡片，初始位姿与手动输入行改网格布局；两面板与裁剪面板统一挂在按钮栏左侧（right: 66px，700px 断点 62px）。
- 已验证：frontend 下 `npm run typecheck` 与 `npm run build` 通过（仅常规大 chunk 警告）；5180 开发页浏览器实测：工具栏两按钮渲染、话题面板展开/收起互斥切换、地图裁剪按钮禁用态、定位导航抽屉四分组无溢出均正常，刷新后 console 无新增运行时错误。
- 限制：离线地图加载后的裁剪面板展开与放射箭头 hover 亮起效果未实测（需真实 PCD）；dev server HMR 编辑期会出现一次性的 Vue reload TypeError（reading 'flags'），硬刷新后不复现，非业务缺陷。

## 2026-09-11：坐标裁剪控件视觉重设计

- 任务目标：按用户详细设计规范重做离线地图裁剪面板的坐标轴控件视觉层，与平台 Low Poly 暖色毛玻璃风格统一；不改任何业务逻辑与事件绑定。
- 修改文件：frontend/src/components/Nav3DViewer.vue、frontend/src/styles.css、.agents/TASK_LOG.md。
- 主要变更：面板卡片改为规范毛玻璃参数（rgba(245,241,232,0.55)、blur(14px)、16px 圆角、柔和阴影），宽 192px；标题改"坐标裁剪/拖动轴向裁剪点云"两行；坐标轴控件重做为 SVG 几何层（两圈暖灰同心辅助圆 + 六条 2.5px 轴向细杆）+ 奶白半透明中心点 + 六个 28px 圆形命中区按钮（13px 小三角箭头、±X/±Y/±Z 标签）；三轴换低饱和暖色（X 珊瑚 #c96f5d、Y 鼠尾草 #7f9a7a、Z 赭黄 #a89a63），标签色更深一档；hover/拖拽态为淡光晕 + 箭头 1.05/1.08 缩放 + 轴杆 3.2px 变粗 + 其余方向压暗 0.35（:has() 渐进增强，容器 dragging-x/y/z 类由既有 activeOfflineClipFace 派生）；重置按钮改 32px ghost 风格"↻ 重置裁剪"；读数行标签同步新三色。所有 pointerdown/move/up、keydown、拖拽与裁剪逻辑、按钮 DOM 与事件绑定完全未动。
- 已验证：npm run typecheck 与 npm run build 通过；浏览器实测（加载真实 PCD map_origin.pcd）：面板/轴杆/箭头/标签/读数/重置渲染无重叠，hover 实测 ::before scale(1.05)+radial-gradient 光晕与轴杆 2.5→3.2px 变粗生效，重置按钮点击后读数与初始值完全一致，真实鼠标拖拽改变边界读数正常（第一轮代理曾误报重置异常，经初始值复核确认为误报）。
- 限制：拖拽中间态的"其余方向压暗 0.35"视觉由纯 CSS 类驱动，浏览器会话中未能截到按住瞬间的画面，未直接目视确认；合成 PointerEvent 因 setPointerCapture 拒绝合成 pointerId 无法自动化验证拖拽全程。

## 2026-09-11：定位导航抽屉非模态化与折叠状态记忆

- 任务目标：按用户反馈修复定位导航抽屉点击三维场景即收起、无法配合场景操作的问题；平台设置等抽屉内可折叠分组需记住上次展开/收起状态。
- 修改文件：frontend/src/composables/usePersistentDetails.ts（新增）、frontend/src/components/GlassDrawer.vue、frontend/src/pages/NavigationWorkspace.vue、frontend/src/styles.css、.agents/TASK_LOG.md。
- 主要变更：GlassDrawer 新增 persistent 非模态模式（无遮罩、drawer-layer pointer-events 穿透、抽屉本体恢复交互、跳过 Tab 焦点锁定、aria-modal false，Escape/X 仍可关闭）；定位导航（control）抽屉启用 persistent，打开时可正常旋转/点击三维场景；工具带三个抽屉按钮改为 toggle 语义（再点收起），话题列表"详情"跳转按钮保持打开语义不变；新增 usePersistentDetails（模块级状态 + localStorage ros-platform.details-open），平台设置（ROS 接入/离线地图/外观与场景）与诊断抽屉（话题详情/链路延迟/运行时参数/录制文件/接入检测/运行日志）共 9 个 details 分组改为受控绑定，展开状态跨抽屉开关与页面刷新保持。
- 已验证：npm run typecheck 与 npm run build 通过；浏览器实测：定位导航抽屉打开后点击/拖动 3D 场景不收起，按钮再点可收起；平台设置默认状态正确（ROS 接入展开、离线地图收起），改折叠状态后关开抽屉与刷新页面均保持（localStorage 实测值正确）；显示项等模态抽屉的遮罩关闭链路经 JS dismiss.click() 与 Escape 双路验证正常。
- 限制：自动化工具按视口坐标点击遮罩存在坐标偏移（事件落在 BODY），无法模拟真实用户点击遮罩关闭，该路径仅通过事件追踪+JS 触发间接验证；RelocalizationWorkspace 页面的 details 分组未纳入持久化（该页 details 为页面常驻或动态条件驱动，无抽屉销毁丢状态问题）。

## 2026-09-16：Android 直连机器狗适配

- 任务目标：参考 feat/ros_android 分支，把 ROS 测试平台当前分支适配为 Android App 可直接连接机器狗 IP/rosbridge，不依赖电脑后端完成话题读取、rosapi 查询和离线地图文件选择。
- 修改文件：frontend/android/**、frontend/capacitor.config.ts、frontend/package.json、frontend/package-lock.json、frontend/vite.config.ts、frontend/src/App.vue、frontend/src/composables/useNavigationController.ts、frontend/src/lib/nativeFilePicker.ts、frontend/src/lib/ros/directRosClient.ts、frontend/src/lib/ros/mobileAppState.ts、frontend/src/lib/ros/mobileCatalog.ts、.agents/TASK_LOG.md。
- 主要变更：恢复 Capacitor Android 工程、沉浸横屏 Activity、明文 ws/http 网络配置和原生文件选择插件；Vite 改为相对资源 base，保证 WebView 可加载打包资源；在后端 tools 接口不可用时提供 ROS 导航页面兜底工具定义；ROS 接入配置优先保存在本地缓存，后端保存失败时仍能在 Android 上继续使用；话题列表、接入检测和运行时参数在后端不可用时改走前端直连 rosbridge/rosapi；离线 PCD/YAML/PGM 在 Android 上通过原生文件选择与本地预览流程处理。
- 已验证：frontend 下 `npm run typecheck` 通过；`npm run build:android` 通过并完成 `npx cap sync android`；frontend/android 下 Gradle debug 包已产出 `frontend/android/app/build/outputs/apk/debug/app-debug.apk`。
- 限制：当前只验证 debug APK 构建，未做 release 签名；真机连接仍要求手机与机器狗网络互通，机器狗开放 rosbridge/rosapi，并允许 `ws://机器狗IP:9090` 这类明文连接；npm install 后仍提示 3 个 moderate 依赖审计项，未在本次处理。

## 2026-09-16：Android 包名与图标区分

- 任务目标：避免当前分支打出的 Android App 与 feat/ros_android 分支安装包互相覆盖或在桌面图标上混淆。
- 修改文件：frontend/capacitor.config.ts、frontend/android/app/build.gradle、frontend/android/app/src/main/AndroidManifest.xml、frontend/android/app/src/main/res/values/strings.xml、frontend/android/app/src/main/res/drawable/ros_platform_launcher.xml、frontend/android/app/src/main/java/com/moontoolbox/rosplatform/MainActivity.java、frontend/android/app/src/main/java/com/moontoolbox/rosplatform/RosFilePickerPlugin.java、.agents/TASK_LOG.md。
- 主要变更：appId/applicationId/namespace 从 `com.moontoolbox.rosnav` 改为 `com.moontoolbox.rosplatform`；应用名从 `MoonToolBox ROS Nav` 改为 `ROS Platform Dev`；MainActivity 与 RosFilePickerPlugin 移到新 Java package；Manifest 启动图标改用当前分支专用的暖色网格 ROS Platform 矢量图标。
- 已验证：frontend 下 `npm run build:android` 通过并同步生成 `capacitor.config.json`；frontend/android 下 `./gradlew.bat assembleDebug` 通过，debug APK 已重新产出。
- 限制：旧 `MoonToolBox ROS Nav` 如果已经装在手机上，本次包名不同，会作为新应用并存安装，不会自动升级覆盖旧应用。

## 2026-09-17：新增 IMU Allan 标定页面

- 任务目标：在 ROS_PLATFROM 分支新增可从左上角标题按钮切换进入的 IMU 标定模块，用于 Windows 本地解析 rosbag2 `.db3` 并做 Allan 方差/噪声参数估计。
- 修改文件：backend/app/catalog.py、backend/app/api/routes.py、backend/app/services/imu_calibration.py、data/tool_modules.json、frontend/src/api/client.ts、frontend/src/main.ts、frontend/src/App.vue、frontend/src/components/PlatformLauncher.vue、frontend/src/pages/ImuCalibrationPage.vue、.agents/PROJECT_OVERVIEW.md、.agents/TASK_LOG.md。
- 主要变更：新增 `imu_calibration` 工具、`/tools/imu-calibration` 路由和左上角工具箱第五项；后端直接读取 rosbag2 SQLite3 的 `topics/messages` 表，按 ROS2 CDR 对齐规则解析 `sensor_msgs/msg/Imu` 的 gyro/accel；新增 inspect/analyze API；前端页面支持 db3 选择、topic 检查、起始/时长/抽样/Tau 参数、Allan 双对数曲线、三轴估计表和 YAML 导出预览。
- 已验证：用 `G:\humble_loc\bags\livox_imu_allan_20260916_120110_0.db3` 检查出 `/livox/imu`、约 1401015 帧、约 200Hz；用 2 万帧抽样跑通 Allan 计算；`python -m compileall backend/app/services/imu_calibration.py backend/app/api/routes.py backend/app/catalog.py` 通过；frontend 下 `npm run build` 通过。
- 限制：当前只支持 `sensor_msgs/msg/Imu` 或 `sensor_msgs/Imu` 且 `serialization_format=cdr` 的 rosbag2 SQLite3；Allan 指标为第一版自动估计，拟合区间尚不能人工选择；本次样本显示 accel z 均值约 0.98，推断驱动可能按 g 而非 ROS 标准 m/s² 发布，页面当前按消息原单位展示。

## 2026-09-18 导航任务与定位面板分离

- 目标：参考图拆分导航侧栏，共享三维场景和机器人位置 HUD；支持当前位置与地图打点，导航通信延后接入。
- 修改文件：frontend/src/pages/NavigationWorkspace.vue；frontend/src/components/NavigationTasks.vue、Nav3DViewer.vue；frontend/src/lib/navigationTasks.ts；frontend/src/composables/useNavigationController.ts；frontend/tests/navigation-tasks.test.mjs；.agents/PROJECT_OVERVIEW.md、TASK_LOG.md。
- 主要变更：顶部切换、任务增删改、点位增删排序、定位到点、编号/朝向/虚线、草稿取消与保存、本地持久化、JSON 导入导出。定位抽屉移除导航入口，旧消息方法保留但新导航面板不调用。HUD 无改动。
- 接口：新增 TaskScene 与 NavigationTransport；execute 返回未接入，开始不下发，继续/暂停/取消禁用。坐标单位 m，yaw 单位 rad；坐标系不符时禁止编辑。
- 验证：类型检查、Vite 构建、任务协议回归通过。Edge/Playwright 检查打点、变换模式、手动坐标、取消、刷新恢复、断线取点保护及通信占位；切换前后 canvas 对象一致，无页面脚本错误。
- 风险与限制：真实硬件位姿、离线地图射线吸附、真实导航消息与执行反馈尚未验证。构建仍有大包提示。任务保存在当前浏览器，可用 JSON 迁移；连线不是规划路径。

## 2026-09-18 修复局域网新建任务并实现顺序执行

- 目标：修复新建无响应，完善建任务/编辑点位界面，按上一点成功后才下发下一点实现调度。
- 已确认根因：局域网 HTTP 下 isSecureContext=false，crypto.randomUUID 为 undefined；旧新建事件抛错，任务数仍为 0。之前 localhost 回归未覆盖此场景。
- 修改文件：frontend/src/components/NavigationTasks.vue；frontend/src/lib/navigationTasks.ts；新增 frontend/src/lib/navigationRunner.ts；frontend/tests/navigation-tasks.test.mjs；新增 frontend/tests/navigation-runner.test.mjs；docs/NAVIGATION_TASKS.md；.agents/PROJECT_OVERVIEW.md、TASK_LOG.md。
- 主要变更：兼容非安全上下文的编号；新建名称/类型表单及首点编辑；任务类型/时间/执行进度；编辑布局、坐标显示精度；真实/模拟执行切换；运行时锁定任务编辑；修改停止任务时清除旧进度。
- 执行逻辑：固定任务快照、单点下发、确认与到达分离；runId/goalId 过滤旧结果和重复反馈；到达后续发、失败停止；暂停期间记完成但不续发，继续确认后推进；取消后不下发后续点。模拟模式需人工反馈且不发 ROS 消息。
- 接口变化：整任务 execute 占位改为 sendGoal/control/subscribe；真实适配器仍返回未接入，可注入 NavigationTasks.transport。旧 ROS 控制器不受影响。
- 验证：协议测试、顺序执行回归、类型检查、构建通过；Edge/Playwright 在局域网 HTTP 5180 与 8100 验证新建、打点、三点编辑持久化、真实未接入、模拟顺序执行、暂停到达/继续、失败、取消和刷新，无页面脚本错误。
- 尚未验证：真实硬件位置取点、离线地图吸附、真实导航协议。仅持久化任务定义；真实执行恢复、断线/超时处理需通信适配层实现。构建大包警告仍存在。

## 2026-09-18 初始化与任务点改用组合位姿控件

- 目标：平移箭头和旋转圆环同时显示，无需点击按钮切换操作。
- 修改文件：frontend/src/lib/scene/combinedPoseControls.ts（新增）；frontend/src/components/Nav3DViewer.vue、NavigationTasks.vue；frontend/src/pages/NavigationWorkspace.vue；frontend/src/composables/useNavigationController.ts；frontend/src/lib/navigationTasks.ts；frontend/tests/combined-pose-controls.html、combined-pose-controls.test.cjs（新增）；docs/NAVIGATION_TASKS.md；.agents/PROJECT_OVERVIEW.md、TASK_LOG.md。
- 主要变更：组合控件负责两个 TransformControls 的公开指针方法调用与互斥，平移在内侧、旋转在外侧；去除自由旋转中心球以免遮挡平移。初始化保留三轴局部旋转；任务数据仅包含 yaw，因此使用世界坐标平移与 Z 轴旋转。删除旧切换按钮、模式状态与内部 setInitialPoseTransformMode 接口，替换为直接操作提示。
- 生命周期：指针捕获、松开、取消、失焦、候选清除、组件销毁统一释放；拖动期间冻结相机阻尼，避免残余相机运动改变交互平面。定位发布与任务保存仍走原回调。
- 验证：类型检查与构建通过；独立浏览器真实拖动验证 X/Y 平移、Z/X 旋转、相机不动、任务仅 yaw、失焦/清除/销毁；任务实际页面连续旋转和平移无需切换且坐标同步正确；导航创建/编辑/模拟顺序执行流程回归通过，无脚本错误。
- 尚未验证：真实机器狗定位发布、实机点云绑定后的拖动、触屏设备现场操作。构建仍有原有大包提示。

## 2026-09-18 任务点补全三轴姿态

- 目标：修复任务编辑只有单轴旋转的问题，使任务点与初始化均显示三轴圆环。
- 修改文件：frontend/src/lib/scene/combinedPoseControls.ts、lib/navigationTasks.ts、components/Nav3DViewer.vue、components/NavigationTasks.vue；tests/combined-pose-controls.html、combined-pose-controls.test.cjs、navigation-tasks.test.mjs、navigation-runner.test.mjs；docs/NAVIGATION_TASKS.md；.agents/PROJECT_OVERVIEW.md、TASK_LOG.md。
- 主要变更：取消任务点 showX/showY 限制，保留其世界坐标操作；新增 roll/pitch 输入、校验与持久化；完整姿态用于候选预览、机器人当前位置、重新编辑和场景方向箭头。下发点位通过原快照保留三轴数据。
- 兼容性：version 1 及原本地存储键不变，旧点位缺失 roll/pitch 自动补零；角度统一使用 XYZ 欧拉角和 rad。
- 验证：浏览器在初始化及任务模式实际拖动三轴旋转，任务表单完整姿态保存后重开与候选四元数一致；文件兼容/非法角度与下发字段回归通过。类型检查与生产构建通过。
- 尚未验证：真实机器狗三轴姿态取点和导航通信联调；实际导航端对横滚/俯仰的支持需后续适配。构建大包提示仍保留。

## 2026-09-18 导航任务弹窗与详情视觉优化

- 目标：仅优化新建任务弹窗及右侧详情的信息层级、密度和控件样式，与定位页面的暖灰工具界面一致。
- 修改文件：frontend/src/components/NavigationTasks.vue；docs/NAVIGATION_TASKS.md；.agents/TASK_LOG.md。
- 主要变更：弹窗宽度收为 320px，两行配置采用统一 30px 控件；压缩辅助文案，使用低饱和灰绿主按钮。详情宽度 310px，分为基础信息及任务点列表，元数据右对齐、小型状态标签、轻分隔线；点位行仅保留定位/编辑/删除图标，排序按钮移至点位编辑区。短窗口可滚动访问完整表单。
- 范围：未改动模式切换、左侧任务结构、三维场景、设备状态与底部执行控件；未变更通信或数据协议。项目地图无需更新。
- 验证：类型检查、生产构建通过；Edge 浏览器检查 1440x900 与 1280x720 排版、编辑排序；现有局域网浏览器回归覆盖创建、地图打点、保存刷新、模拟逐点执行、暂停继续、失败取消，无脚本错误。
- 限制：真实机器人通信与触屏设备尚未验证；构建仍有原有的大包警告。

## 2026-09-18 精简导航任务提示

- 目标：取消逐点导航常驻说明和点位保存成功提示；按操作节奏关闭新建、缺失机器人位姿及地图操作提示。
- 修改文件：frontend/src/components/NavigationTasks.vue；.agents/TASK_LOG.md。
- 主要变更：指定三类提示显示 2 秒；文档捕获阶段监听点击、指针按下及键盘操作关闭提示，不影响本次操作产生的新提示。地图提示每次切换打开任务仅显示一次，“不再提示”替换关闭图标，使用独立 localStorage 键 ros-platform.navigation-map-hint.dismissed 保存偏好，跨任务及刷新生效。卸载清理监听器与计时器；未修改导航调度和任务数据格式，项目地图无需更新。
- 验证：类型检查及生产构建通过；Edge 浏览器覆盖超时消失、操作关闭、同任务不重复、新任务恢复提示、跨任务和刷新持久关闭、静默保存，无脚本错误。
- 限制：偏好属于当前浏览器来源；清除站点数据会重置。构建保留原有大包警告，真实硬件通信尚未验证。

## 2026-09-18 导航任务编排流程与退出动效

- 目标：统一删除确认与文件展开反馈，移除模拟执行，添加渐隐，并改为先选择取点来源再创建点位。
- 修改文件：frontend/src/components/NavigationTasks.vue、Nav3DViewer.vue；frontend/src/pages/NavigationWorkspace.vue；frontend/src/lib/navigationRunner.ts；frontend/tests/navigation-runner.test.mjs、navigation-workflow.test.cjs（新增）；docs/NAVIGATION_TASKS.md；.agents/PROJECT_OVERVIEW.md、TASK_LOG.md。
- 主要变更：删除任务改为暖灰页面内确认窗；文件箭头旋转为向下；弹窗/侧栏/提示/编辑区及任务点列表使用 180ms 淡出；定位模式覆盖层切换也加入淡出。移除执行模式选择、人工结果按钮及生产模拟适配器。
- 点位流程：先选机器狗取点或地图打点。机器狗有效位姿生成草稿后手动保存；地图连续点击或拖动直接新增并持久化，坐标轴和表单实时更新当前点，完成打点退出。地图编号命中优先于空白点选，并丢弃此前未完成的地面查询；控件指针仲裁仍优先，避免误新增。
- 接口：新增 Viewer taskPosePlaced 事件区分新增与 taskPoseChange 编辑；NavigationTransport/RunState 删除 mode 字段，sendGoal/control/subscribe 及顺序调度不变。
- 验证：类型检查、生产构建、任务协议和顺序执行回归通过；新增 Edge 交互测试覆盖连续自动保存、实际坐标轴拖动不新增、编号选点、文件箭头、渐隐离场、删除取消/确认、真实未接入保护及刷新持久化。开发环境使用测试替身验证有效机器人位姿的手动保存分支，生产构建跳过该调试入口替身分支。
- 限制：真实机器人位姿与导航消息联调、离线点云射线服务及触屏设备尚未验证；已有构建大包警告保留。

## 2026-09-20 排查 loaded_pointcloud_map 无数据

- 目标：定位 /debug/loaded_pointcloud_map 数据无法接收的原因；本次仅进行只读检查。
- 已确认：用户提供发布者与 rosbridge 订阅者均为 RELIABLE / TRANSIENT_LOCAL。直连当前配置的 rosbridge 可发现该话题，但独立订阅 15 秒没有收到地图消息；同链路 /tf_static 与 /lio/cloud_local_base_exact 正常返回。
- 关键证据：通过 /ndt_scan_matcher/list_parameters、get_parameters 读取到 dynamic_map_loading.publish_loaded_map=false；describe_parameters 返回 read_only=false，但是否动态更新实际发布行为尚未验证。Autoware 官方参数文档说明此参数控制 debug/loaded_pointcloud_map 发布。
- 结论：运行中 NDT 节点的调试地图发布开关关闭；话题存在和发布端数量不代表实际已发布地图帧。应在 ROS 端开启对应配置并确认加载后发布，不能通过前端解析或 QoS 修改解决此开关问题。
- 修改文件：仅 .agents/TASK_LOG.md；未更改前端、机器人运行参数或重启节点，项目地图无需更新。
- 限制：ROS 主机 SSH 无免密访问；未读取其实际部署源码、未验证参数热更新或开启后的地图接收。用户 CLI 不支持 --once / --field，原命令未执行订阅。

## 2026-09-20 接入默认 SCAN 真实导航协议

- 目标：根据用户提供的接口说明，将导航任务页面接入单点请求、编号关联反馈、控制命令和定位状态，保留平台逐点队列。
- 新增文件：frontend/src/lib/rosNavigationTransport.ts（协议适配）、navigationOwnership.ts（同来源浏览器控制租约）；frontend/src/composables/useTaskNavigation.ts（共享连接生命周期）；frontend/tests/ros-navigation-transport.test.mjs、navigation-ros-workflow.test.cjs。
- 修改文件：frontend/src/lib/navigationRunner.ts；frontend/src/components/NavigationTasks.vue；frontend/src/pages/NavigationWorkspace.vue；frontend/tests/navigation-workflow.test.cjs；docs/NAVIGATION_TASKS.md；.agents/PROJECT_OVERVIEW.md、TASK_LOG.md。
- 协议：发布 /nav2_goal_request 的 String JSON，goalId 对应唯一 request_planid，pose 包含 frame_id/x/y/z/yaw，context 携带任务/运行/点序号与名称。订阅 /nav2_goal_context，只有同编号 reached 且 request_completed=true 才成功推进；path_ready、WAIT_TARGET 和恢复原因不算到点。默认不使用 /nav2_status。
- 控制：pause/resume/cancel 发往 /nav2_goal_control 并等待状态确认；取消后的空编号只在同一连接周期等待本次 cancel 时处理。陌生编号、连接目标改变、租约丢失均禁止控制。取消与到点竞态停止剩余队列。
- 健康：订阅 /nav_ndt_status，1/2 可启动，0/3 不可。状态与定位超过 3 秒视为过期，确认等待 8 秒；超时显示 unknown 并锁定任务，不自动重发。新增 blocked/unknown 运行状态及可选进度订阅，恢复收到当前编号状态再对账。定位异常只阻断平台队列推进，机器人暂停仍由导航端负责。
- 界面：沿用暖灰工具条展示导航阶段、定位质量和未就绪原因，未就绪禁用开始；执行状态新增定位等待/状态未知。
- 兼容：任务 JSON 保留 roll/pitch，但线协议仅发送 yaw；reached 不代表最终朝向达标。切换定位/导航不重建连接或执行器，刷新不自动恢复执行。
- 验证：类型检查、生产构建、原逐点执行与新增协议测试通过。浏览器隔离全部 WebSocket 验证生产页面连接、连续目标、暂停/继续、断流、取消及原点位编辑流程。现场仅只读订阅：context 为 idle 且字段符合协议，nav_ndt_status=1；未发布测试目标或控制消息。
- 限制：真实机器人运动、定位自动暂停恢复、实际最终姿态尚未验证。同来源浏览器租约不是跨设备服务端互斥；外部控制不校验请求编号，现场仍需唯一控制源。大包构建提示保留。
- 补充边界：暂停/取消确认超时仍保留用户停止后续队列的意图；迟到的到点反馈不触发续发。新增对应回归并通过，最终生产页面协议回归通过。

## 2026-09-20 导航列表拖动与路线插点
- 目标：补齐任务点拖动排序和三维顺序路线点击插入。
- 文件：frontend/src/components/NavigationTasks.vue、Nav3DViewer.vue、frontend/src/pages/NavigationWorkspace.vue、frontend/src/lib/navigationTasks.ts；frontend/tests/navigation-route-editing.test.cjs；docs/NAVIGATION_TASKS.md、项目地图。
- 变更：拖放落点边缘提示、列表移动动画和边缘滚动；路线 8px 拾取与 5px 拖动排除，相邻编号校验，插点立即保存并选中。保留原点编辑模式与运行任务锁定。
- 验证：typecheck、Vite build 通过；浏览器双向拖放、路线插点、刷新持久化、视角拖动防误触及原连续打点/坐标轴回归通过；隔离 WebSocket 的导航逐点执行、暂停继续与取消回归通过。
- 限制：尚未验证触屏拖放和真实机器人执行；没有发送真实导航目标。构建仍有大于 500 kB 的分包提示。

## 2026-09-22 位姿编辑缩放、插点方向与多客户端位姿
- 文件：frontend/src/lib/scene/poseVisualScale.ts、combinedPoseControls.ts；frontend/src/lib/navigationTasks.ts；frontend/src/components/Nav3DViewer.vue、NavigationTasks.vue；frontend/tests/navigation-tasks.test.mjs、combined-pose-controls.html/.test.cjs、navigation-multiclient-pose.test.cjs；docs/NAVIGATION_TASKS.md、项目地图。
- 变更：控件/图标距离缩放衰减且封顶，编号显示与拾取优先；插点默认方向取入段/出段切线角平分线，处理折返/重合；重复选择同点也将列表居中。统一模型、HUD、狗当前位置 TF 解析，旧 body 无样本时降级至完整 base_link 链并标识。
- 现场只读证据：配置 robot_tf_frame=body；两个并发 WebSocket 各 10 秒收到 /display/tf 20 帧、/tf 20 帧、/tf_static 1 帧，抽样 TF 包含 base_link 未包含 body。未复现双客户端互相断流，不把配置问题等同于全部双机故障根因。未发送任何导航目标。
- 验证：类型检查和构建通过；连续打点、路线插点、列表拖动、三轴旋转与导航协议回归通过；新增隔离双浏览器覆盖接入/断开互不影响、base_link 降级、body 恢复优先、同点重复选中列表居中；方向边界单测通过。查看截图确认控件收敛和编号可见。
- 尚未验证：用户两台物理设备现场复测与真实机器人运动；构建仍有既有的大分包警告。

## 2026-09-22 Super-LIO 建图工作台界面

- 目标：在现有三维定位导航工作台内补齐建图模式，覆盖 Super-LIO 实时建图与录包处理的关键输入、预检、任务状态及产物信息。
- 修改文件：`frontend/src/pages/NavigationWorkspace.vue`、`frontend/src/components/MappingWorkspace.vue`、`.agents/PROJECT_OVERVIEW.md`、`.agents/TASK_LOG.md`。
- 主要变更：顶部模式增加“建图”；三维场景不重建，建图覆盖层左右分别展示输入校验和地图产物，底部提供本地状态机形式的开始、暂停、结束操作。录包模式明确要求先解析 rosbag2 metadata 并绑定 LiDAR/IMU/TF，实时模式明确校验外参与时间连续性；产物定义为全局点云、轨迹关键帧和可复现配置快照。
- 布局适配：建图输入面板改为受顶部和底部安全区约束的内部滚动容器；进入建图模式时隐藏仅供定位使用的“重置视角”与说明，避免小高度窗口覆盖输入参数。
- 验证：`frontend` 下 `npm run typecheck`、`npm run build` 通过；浏览器实测定位→建图切换、实时/录包切换及离线任务开始/结束状态均正常，无控制台异常。
- 限制：当前仅是前端交互与信息架构，未接入 Super-LIO 节点生命周期、真实 rosbag2 文件选择/解析、数据流频率检查、录制、PCD/轨迹导出或地图后处理；构建保留既有大于 500 kB 的分包警告。

## 2026-09-22 保存当前分支并准备 Android 适配方案
- 用户要求：先提交并推送当前全部修改，再参考 feat/ros_android 分支给出适配方案。
- 提交范围：当前平台重构、导航/定位/建图前端、ROS 通信、相关后端与测试，以及现有 Android 工程调整。
- 验证：本次提交前前端类型检查、生产构建与导航任务单测通过；Android APK 尚未构建验证。
- 推送与 Android 方案结果在本次会话说明。

- 推送结果：当前实现提交 1b72fa9 已推送并验证 origin/ROS_PLATFROM；直连失败后使用系统已有代理 127.0.0.1:7897 的单次 Git 参数完成，未修改全局配置。
- Android 方案：新建 docs/ANDROID_ADAPTATION_PLAN.md，已核对远端安卓分支 8b37ac9。确认旧悬浮框会实时写回，不符合确定才提交；当前 adjustNothing/Insets 消费、固定面板布局、JSON 网页导入导出与鼠标手势需统一适配。提出输入草稿事务、原生 IME 桥接、单面板布局、文件位置隔离及实机验收。只更新方案和项目地图，未实现 Android 新功能。
