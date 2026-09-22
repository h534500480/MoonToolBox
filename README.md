# ROS 测试平台

本分支 ROS_PLATFROM 以 ros-test-platform 的页面和交互为参考，使用 Vue 3、Vite、TypeScript、Three.js，保留 ros_tool 的 FastAPI/C++ 业务实现。首页直接进入三维工作台，菜单仅含 PCD 转 PGM、PCD 切片、全局重定位候选点、ROS 定位导航测试。

## 运行

需要 Windows、Python 3.10+、Node.js 22、CMake 和 Visual Studio C++ 编译工具。
首次运行 scripts/install_local.cmd；安装后运行 scripts/start_local.cmd，访问 http://127.0.0.1:8100。scripts/stop_local.cmd 停止本工作区托盘与后端。

开发启动（两个终端）：

```powershell
.\.venv\Scripts\python.exe backend/run.py
cd frontend
npm run dev
```

开发页面 http://127.0.0.1:5180，代理 API 到 8100；端口与原项目分开。C++ 四个可执行程序位于 cpp/build，文件输出默认位于当前工作区 output*。

## 使用

- 初始为演示场地、机器狗与遥测。设置中连接 ROS 或加载离线点云/体素后，真实数据接管。狗模型由 TF base_link 或位姿驱动；断线显示最后有效姿态，需显式“返回演示”才恢复演示。
- 话题支持搜索、拖入监控、批量添加、暂停、折叠、排序、双击详情和录制。底部工具栏提供定位导航、显示项和诊断。
- 候选点支持点击/Shift 多选、框选、点组拖动、人工补点、锁定、删除区域、回收站、撤销/重做和姿态编辑。拖动保持 Z；高度及 roll/pitch/yaw 在编辑面板调整。
- 演示候选点禁止导出。真实审核通过 C++ 计算描述子，质量过滤沿用原算法；最终数量和拒绝数量见执行输出。

## 验证

```powershell
cd frontend
npm run typecheck
npm run build
cd ..
.\.venv\Scripts\python.exe tests/test_platform.py
```

集成测试启动独立后端，用临时点云验证路由、地图/切片输出、体素/射线与真实描述子。
tests/mock_rosbridge.py 提供 ws://127.0.0.1:9099，仅模拟本地消息；控制下发只写 output_qa/commands.jsonl，不接入真实机器人。

真实机器人、服务版本、现场网络、长时录制、超大地图性能和安装包发布尚未验证。架构与对应接口见 docs/WEB_ARCHITECTURE.md。
