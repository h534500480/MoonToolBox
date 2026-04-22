# 旧桌面工具模块

本目录保存早期 Tkinter 桌面版工具页面和部分命令行能力。

当前主线已经切到 `frontend/ + backend/ + cpp/`，因此这里的代码主要承担：

- 兼容 `python .\tool_suite_gui.py` 的旧桌面入口
- 保留早期 PCD、网络扫描、Costmap 工具实现
- 作为后续迁移到后端服务或 C++ CLI 的功能参考

维护规则：

- 不在这里新增 Web 主线能力，新增 Web 工具优先放到 `backend/app/services/`、`backend/app/catalog.py` 和 `frontend/src/`。
- 修改大体量模块时优先补清楚边界和错误上下文，避免在单个文件里继续堆叠复杂逻辑。
- 若要迁移目录或拆文件，先更新 `registry.py`、打包脚本和 README，避免破坏旧桌面启动入口。
