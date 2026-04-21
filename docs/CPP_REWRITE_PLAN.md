# PCD -> SLAM 地图 C++ 重写计划

当前策略已经切换为：

- Python 版本继续保留，作为参考实现
- C++ 版本直接从头重写
- 不再优先围绕 Tkinter 页面继续深拆

## 参考来源

主要参考文件：

- `src/ros_tool_suite/tools/pcd_slam_map_tool.py`

这个文件当前仍保留完整的 Python 参考逻辑，适合逐函数对照迁移。

## C++ 第一阶段

目标：

- 先完成 `pcd_map_cli`
- 与 Python 版对齐输入参数和输出文件名

建议实现顺序：

1. `PCDReader`
   支持 PCD 头解析和 `ascii / binary` 点读取
2. `build_grid`
   扫描 extent、栅格化、分类
3. grid 后处理
   障碍物膨胀、walkable hole fill
4. exporters
   输出 pgm / yaml / walkable png / preview png
5. CLI 参数
   对齐 Python 版本

## 验证方式

每完成一阶段，用同一个 PCD 同时跑：

- Python 参考版
- C++ CLI

对比：

- 地图尺寸
- origin
- point_count
- walkable / obstacle / unknown 数量
- 输出图像视觉结果
