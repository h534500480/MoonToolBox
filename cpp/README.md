# C++ 主线目录

这个目录现在按“可直接写核心引擎”的方式整理，不再按 Python 页面结构走。

## 当前结构

- `CMakeLists.txt`
  C++ 构建入口
- `include/ros_tool_suite/mapping/`
  核心头文件
- `src/mapping/`
  点云读取、栅格化、导出实现
- `src/pcd_map_cli/`
  命令行入口

## 目标

第一阶段先做一个独立的 `pcd_map_cli`：

- 输入：PCD 路径 + 输出目录 + 生成参数
- 输出：
  - `map.pgm`
  - `map.yaml`
  - `map_walkable.png`
  - `map_walkable_preview.png`

## 设计原则

- 直接参考现有 Python 逻辑重写，不依赖 Tkinter
- 先做 CLI，再接桌面/Web 前端
- Python 版保留为参考实现和结果对照

## 当前状态

这次已经把骨架和接口起好，但由于当前环境没有确认可用的 C++ 编译工具链，尚未实际编译验证。
