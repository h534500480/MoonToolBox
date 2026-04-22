#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""旧桌面版兼容启动入口。

当前主线是 `frontend/ + backend/ + cpp/`，这个文件继续保留是为了支持
`python .\tool_suite_gui.py` 的历史启动方式。实际桌面壳实现位于
`src/ros_tool_suite/app.py`。
"""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ros_tool_suite.app import main


if __name__ == "__main__":
    main()
