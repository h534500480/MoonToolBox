#!/usr/bin/env python3
# -*- coding: utf-8 -*-

TOOLS = [
    {
        "key": "slam",
        "title": "pcd -> pgm",
        "subtitle": "从点云生成 PGM、YAML 和绿道图",
        "module": "ros_tool_suite.tools.pcd_slam_map_tool",
        "class_name": "MapToolApp",
        "kwargs": {"embedded": True},
        "group": "pcd_tools",
    },
    {
        "key": "tile",
        "title": "pcd slicing",
        "subtitle": "切分点云并生成 metadata",
        "module": "ros_tool_suite.tools.pcd_tile_split_gui",
        "class_name": "App",
        "kwargs": {"embedded": True},
        "group": "pcd_tools",
    },
    {
        "key": "network",
        "title": "ip check",
        "subtitle": "扫描设备、解析 MAC 和 SSH 状态",
        "module": "ros_tool_suite.tools.ipdector",
        "class_name": "NetworkScannerApp",
        "kwargs": {"embedded": True},
        "group": "network",
    },
    {
        "key": "costmap",
        "title": "bag replay",
        "subtitle": "回放 costmap 帧并导出 GIF / PNG",
        "module": "ros_tool_suite.tools.costmap_player",
        "class_name": "CostmapPlayerPage",
        "kwargs": {"embedded": True},
        "pack_widget": True,
        "group": "perception",
    },
]

GROUP_ORDER = [
    ("pcd_tools", "pcd_tools"),
    ("network", "network"),
    ("perception", "perception"),
]
