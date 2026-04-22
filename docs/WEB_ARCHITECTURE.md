# Web 架构说明

当前主线已经切到：

- `frontend/`
  Vue + Vite 前端
- `backend/`
  FastAPI 服务层
- `cpp/`
  C++ 核心和 CLI

## 当前职责

- `frontend`
  负责页面、参数录入、工具切换、分区、收藏、日志展示
- `backend`
  负责工具目录、偏好设置、任务入口、调用 C++ CLI
- `cpp`
  负责重计算逻辑

## 当前状态

- `pcd -> pgm`
  已接通 `frontend -> backend -> pcd_map_cli.exe`
- `pcd slicing`
  前后端页面和接口骨架已存在，CLI 还未完全接通
- `ip check`
  前后端页面和接口骨架已存在
- `bag replay`
  已接通 `frontend -> backend -> costmap_cli.exe`
- `MTSlash 导出`
  已接通账号登录、收藏夹读取、浏览器模式标签页读取和单帖 TXT 导出

## 工具分区与收藏

前端左侧导航已支持：

- 默认分区：`Favorites / Mapping / Network / Perception / Other`
- 自定义分区
- 拖拽工具到分区标题进行归类
- 星标收藏到 `Favorites`

偏好设置通过后端接口持久化：

- `GET /api/preferences`
- `PUT /api/preferences`

存储文件：

- `backend/data/tool_preferences.json`

## 下一步

继续沿 `frontend -> backend -> cpp` 的方向收敛旧 Python GUI 能力：

- 将仍在 `src/ros_tool_suite/tools/` 中维护的旧桌面逻辑逐步下沉到后端或 C++ CLI
- 把体积较大的前端工具页面拆成职责更清晰的组件
- 为 MTSlash 这类依赖外部页面结构的模块补充诊断说明和失败样例记录
