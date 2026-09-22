# C++ 业务核心

- pcd_map_cli：PCD 栅格化，输出 PGM/YAML/PNG。
- pcd_tile_cli：网格切片、重叠、ASCII/二进制与 metadata。
- global_relocalization_cli：自动/审核候选点虚拟扫描与真实描述子。
- nav_pcd_preview_cli：导航离线地图下采样和预览。

```powershell
cmake -S cpp -B cpp/build -G "Visual Studio 17 2022" -A x64
cmake --build cpp/build --config Release --parallel 4
```

程序输出位于 cpp/build。MSVC 使用 UTF-8 源码，后端按当前工作区调用。保留原算法和数据格式。
