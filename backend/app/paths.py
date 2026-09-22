"""功能说明：区分只读程序资源与可写用户数据，兼容源码和独立发行包。"""
import os
from pathlib import Path

# 发行入口在导入业务模块前设置路径，避免依赖编译后的模块文件位置。
SOURCE_ROOT = Path(__file__).resolve().parents[2]
RESOURCE_ROOT = Path(os.environ.get("ROS_PLATFORM_RESOURCES", SOURCE_ROOT)).resolve()
DATA_ROOT = Path(os.environ.get("ROS_PLATFORM_DATA", SOURCE_ROOT)).resolve()
PACKAGED = os.environ.get("ROS_PLATFORM_PACKAGED") == "1"
CONFIG_ROOT = DATA_ROOT / "config" if PACKAGED else SOURCE_ROOT / "backend" / "data"
CPP_BUILD_DIR = RESOURCE_ROOT / "cpp" / "build"
FRONTEND_DIST = RESOURCE_ROOT / "frontend" / "dist"
