# 四模块对应与验证边界

| 页面 | 控制层 | 实际业务 |
| --- | --- | --- |
| / | NavigationWorkspace / useNavigationController | 共享 rosbridge、TF/PointCloud2/Map/Path/Marker/Bspline、初始位姿、导航目标/暂停/恢复/取消、延迟、参数、录制 |
| /tools/pcd-map | MappingPage | pcd_map/run → pcd_map_cli → PGM/YAML/PNG |
| /tools/pcd-tile | MappingPage | 预扫描、pcd_tile/run → pcd_tile_cli → 切片/metadata |
| /tools/global-relocalization | RelocalizationWorkspace / useRelocalizationController | PCD/候选点读取、人工 YAML/审核 CSV、C++ 真实 candidates/descriptors/ring_keys/sector_keys |

候选编辑包含锁定、删除区域、回收站和历史。加载真实文件清除演示历史；全部删除后禁止将空审核误判为自动重采样。质量过滤和导出格式沿用原算法。

主视图保留原有点云解析、体素裁剪、地面法线和初始位姿操作。电量读取 /battery，速度读取 /odometry/filtered，消息超时显示未知。不同话题名称可使用通用监控卡。

平台的 React/Next/R3F 页面移植到 Vue/原生 Three.js，以复用原 ROS 适配器和控制链路。布局、材质、模型和交互参考 platform，业务使用 ros_tool。

## 已验证

- Vue 严格类型检查、Vite 生产构建、四 CLI Windows Release 编译。
- 四项 HTTP/C++ 集成回归：仅四模块、移除模块 404、子页面刷新、地图/切片文件、离线体素/射线、真实候选描述子。
- 浏览器对照首页、地图和候选点页；真实地图生成/预览、候选点导入、拖动保持 Z、撤销、锁定保护和最终导出。
- 本地 rosbridge 替身：场景接管、TF 驱动模型、PointCloud2、真实电量/速度、话题复选与监控。

## 尚未验证

真实机器人的服务/action 名称、自定义消息版本、实际导航运动、现场网络重连、长时间录制、超大点云帧率和安装包发布。协议替身及合成点云不能代替现场验证。
