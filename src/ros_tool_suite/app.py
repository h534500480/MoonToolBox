#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""旧 Tkinter 桌面壳的包内入口。

该入口只负责导出桌面壳和工具注册表，供根目录 `tool_suite_gui.py` 兼容启动。
Web 主线不要从这里新增功能。
"""

from ros_tool_suite.tools.registry import GROUP_ORDER, TOOLS
from ros_tool_suite.ui.desktop.shell import ToolSuiteApp, main


__all__ = ["GROUP_ORDER", "TOOLS", "ToolSuiteApp", "main"]


if __name__ == "__main__":
    main()
