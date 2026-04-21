# ROS Tool Suite

当前项目已经整理成一个可继续扩展的个人工具箱，而不是单一脚本。

## 当前结构

- `tool_suite_gui.py`
  根目录兼容启动入口，继续支持 `python .\tool_suite_gui.py`
- `src/ros_tool_suite/`
  Python 主源码
- `src/ros_tool_suite/tools/`
  各个功能模块
- `backend/`
  FastAPI 服务层，统一对外提供工具 API
- `frontend/`
  Vue + Vite 前端，作为后续桌面壳 / Web 壳的主 UI
- `docs/ARCHITECTURE.md`
  目录和后续扩展建议
- `docs/WEB_ARCHITECTURE.md`
  Web 架构说明
- `cpp/`
  C++ 核心与 CLI
- `web/`
  早期预留目录，当前主线已切到 `frontend/ + backend/`
- `scripts/build_onefile.ps1`
  单文件 EXE 打包脚本

## 当前功能

- `pcd -> pgm`
  从点云生成 `map.pgm`、`map.yaml`、透明绿道图
- `pcd slicing`
  切分点云并生成 metadata
- `ip check`
  扫描设备、解析 MAC 和 SSH 状态
- `bag replay`
  回放 costmap 并导出 GIF / PNG

## 当前主线

- `frontend/`
  负责页面、参数、日志、状态和工具切换
- `backend/`
  负责 API、任务入口、后续调度 C++ CLI
- `cpp/`
  负责核心计算与命令行工具

当前已经打通：

- Vue 前端骨架
- FastAPI 后端骨架
- `pcd_map_cli / pcd_tile_cli / network_scan_cli / costmap_cli`
- `frontend -> backend -> pcd_map_cli` 真实执行链路
- 左侧工具分区、收藏、拖拽归类
- 分区和收藏通过 `backend/data/tool_preferences.json` 持久化
- C++ GUI 仅作为实验产物保留，不再作为主方向

## 工具分区与收藏

- 左侧支持默认分区：`Favorites / Mapping / Network / Perception / Other`
- 支持新增自定义分区
- 支持将工具拖到目标分区标题上完成归类
- 支持点击星标加入 `Favorites`
- 分区和收藏不再只保存在浏览器，后端会写入 `backend/data/tool_preferences.json`

## 启动

```powershell
python .\tool_suite_gui.py
```

## 启动 Web 版

后端：

```powershell
python .\backend\run.py
```

前端：

```powershell
cd .\frontend
npm run dev
```

也可以直接用：

```powershell
.\scripts\run_backend.cmd
.\scripts\run_frontend.cmd
```

默认地址：

- backend: `http://127.0.0.1:8000`
- frontend: `http://127.0.0.1:5173`

## 本地一键安装 / 启动 Web 版

首次部署：

```powershell
.\scripts\install_local.cmd
```

启动：

```powershell
.\scripts\start_local.cmd
```

启动后访问：

- `http://127.0.0.1:8000`

这个模式会：

- 在 `.venv/` 里安装 Python 依赖
- 构建 `cpp/build/*.exe`
- 安装并构建 `frontend/dist`
- 由 FastAPI 后端直接托管前端页面

目标机器需要预先安装：

- Python 3.10+
- Node.js LTS
- CMake
- 可用的 C++ 编译环境，例如 Visual Studio Build Tools；如果安装了 Ninja 会自动使用 Ninja

如果 `cpp/build/` 里已经带有 `pcd_map_cli.exe`、`pcd_tile_cli.exe`、`network_scan_cli.exe`、`costmap_cli.exe`，安装脚本会跳过 C++ 构建，此时目标机器不需要 CMake。

## 打包单文件 EXE

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_onefile.ps1
```

## 依赖

```powershell
pip install -r .\requirements.txt
```

Web 依赖：

```powershell
python -m pip install -r .\backend\requirements.txt
cd .\frontend
npm install
```

## 说明

- 当前桌面版仍然是 Python GUI。
- Web 主线已经起好骨架，后续建议优先沿 `frontend/ + backend/ + cpp/` 演进。
- 后续建议把性能瓶颈逐步下沉到 `cpp/`。
- `pcd -> pgm` 已经接通真实执行链路，其他工具仍是骨架态。
