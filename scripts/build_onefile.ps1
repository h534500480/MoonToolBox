$ErrorActionPreference = "Stop"

python -m PyInstaller `
  --noconfirm `
  --clean `
  --onefile `
  --windowed `
  --name ros_tool_suite_onefile `
  --hidden-import ros_tool_suite.tools.pcd_slam_map_tool `
  --hidden-import ros_tool_suite.tools.pcd_tile_split_gui `
  --hidden-import ros_tool_suite.tools.ipdector `
  --hidden-import ros_tool_suite.tools.costmap_player `
  --hidden-import ros_tool_suite.shared_ui `
  tool_suite_gui.py
