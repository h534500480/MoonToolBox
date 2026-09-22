"""功能说明：四模块定义及工作区独立的默认输出路径。"""
import json
from pathlib import Path
from typing import Dict, List

from app.models import ToolDefinition, ToolField


ROOT_DIR = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT_DIR / "data"
MODULE_CONFIG_PATH = CONFIG_DIR / "tool_modules.json"


ALL_TOOL_DEFINITIONS = [
    ToolDefinition(
        key="pcd_map",
        title="PCD 转 PGM",
        subtitle="PCD 生成 SLAM 地图",
        description="从 PCD 点云生成 SLAM 栅格地图（PGM/YAML）：按高度截取点云，分别生成可行走层与障碍层，支持地面容差、障碍膨胀与孔洞填补。",
        primary_action="生成地图",
        secondary_action="选择",
        fields=[
            ToolField(key="input_pcd", label="输入 PCD", placeholder="G:/path/map.pcd"),
            ToolField(key="output_dir", label="输出目录", value=str(ROOT_DIR / "output")),
            ToolField(key="base_name", label="输出名称", value="map"),
            ToolField(key="resolution", label="分辨率", value="0.05"),
            ToolField(key="clip_min_z", label="截取最小 Z", value="-1.0"),
            ToolField(key="clip_max_z", label="截取最大 Z", value="2.0"),
            ToolField(key="walkable_min_z", label="可行走最小 Z", value="-0.2"),
            ToolField(key="walkable_max_z", label="可行走最大 Z", value="0.2"),
            ToolField(key="obstacle_min_z", label="障碍最小 Z", value="0.25"),
            ToolField(key="obstacle_max_z", label="障碍最大 Z", value="2.0"),
            ToolField(key="ground_tolerance", label="地面容差", value="0.12"),
            ToolField(key="min_points_per_cell", label="每格最少点数", value="1"),
            ToolField(key="obstacle_inflate_radius", label="障碍膨胀半径", value="0.1"),
            ToolField(key="hole_fill_neighbors", label="孔洞填补邻居数", value="5"),
            ToolField(key="overlay_smooth_radius", label="绿道平滑半径", value="0.0"),
        ],
    ),
    ToolDefinition(
        key="pcd_tile",
        title="PCD 切片",
        subtitle="点云切片与 metadata",
        description="将大幅 PCD 点云按网格切片，支持重叠区域、二进制与 ASCII 格式，并生成 metadata。",
        primary_action="切分点云",
        secondary_action="选择",
        fields=[
            ToolField(key="input_pcd", label="输入 PCD", placeholder="G:/path/map.pcd"),
            ToolField(key="output_dir", label="输出目录", value=str(ROOT_DIR / "output_tiles")),
            ToolField(key="tile_size", label="切片尺寸", value="20.0"),
            ToolField(key="overlap", label="重叠范围", value="0.0"),
            ToolField(key="format", label="输出格式", value="binary"),
            ToolField(key="zip_output", label="压缩输出", value="false"),
        ],
    ),
    ToolDefinition(
        key="global_relocalization_candidates",
        title="全局重定位候选点",
        subtitle="候选点生成与审核",
        description="从离线点云生成全局重定位候选点，支持审核、拖动、姿态编辑与描述子导出。",
        primary_action="确认候选点",
        secondary_action="选择",
        fields=[
            ToolField(key="input_pcd", label="输入 PCD", placeholder="G:/path/map.pcd"),
            ToolField(key="candidate_file", label="候选点文件", placeholder="G:/path/global_relocalization_db/candidates.csv"),
            ToolField(key="output_dir", label="输出目录", value=str(ROOT_DIR / "output_global_relocalization")),
            ToolField(key="config_path", label="离线配置 YAML", placeholder="src/ros_func/config/global_relocalization/offline_6dof_database.yaml"),
            ToolField(key="manual_file", label="人工编辑 YAML", placeholder="G:/path/global_relocalization_db/manual_candidates.yaml"),
            ToolField(key="candidate_format", label="候选点格式", value="csv"),
            ToolField(key="fixed_frame", label="固定坐标系", value="map"),
            ToolField(key="base_frame", label="机器人坐标系", value="base_link"),
        ],
    ),
    ToolDefinition(
        key="ros_nav_test",
        title="ROS 定位导航测试",
        subtitle="定位导航可视化工作台",
        description="定位与导航可视化工作台，支持离线地图、实时话题、初始位姿、导航控制、诊断与录制。",
        primary_action="启动测试布局",
        secondary_action="选择",
        fields=[
            ToolField(key="ros_provider", label="接入方式", value="rosbridge"),
            ToolField(key="ros_bridge_url", label="Bridge 地址", value=""),
            ToolField(key="ros_api_service", label="Topic 查询服务", value="/rosapi/topics_and_raw_types"),
            ToolField(key="fixed_frame", label="固定坐标系", value="map"),
            ToolField(key="robot_tf_frame", label="机器人 TF 坐标系", value="body"),
            ToolField(key="map_topic", label="地图 Topic", value="/map"),
            ToolField(key="offline_map_pcd", label="离线地图 PCD", placeholder="G:/path/map.pcd"),
            ToolField(key="offline_map_yaml", label="map.yaml", placeholder="G:/path/map.yaml"),
            ToolField(key="offline_map_pgm", label="map.pgm", placeholder="G:/path/map.pgm"),
            ToolField(key="offline_map_voxel_leaf_m", label="离线点云下采样 m", value="0.20"),
            ToolField(key="offline_map_occupancy_voxel_m", label="占据 voxel m", value="0.30"),
            ToolField(key="offline_map_max_points", label="离线点云最大点数", value="60000"),
            ToolField(key="offline_map_max_voxels", label="占据最大 voxel", value="60000"),
            ToolField(key="offline_map_display_mode", label="离线地图显示方式", value="voxel"),
            ToolField(key="offline_map_point_size", label="离线点云大小", value="0.06"),
            ToolField(key="offline_map_point_color", label="离线点云颜色", value="#d7dee8"),
            ToolField(key="offline_map_voxel_color", label="占据网格颜色", value="#a79d86"),
            ToolField(key="initial_pose_base_height_offset_m", label="初始化 base 高度偏移 m", value="0.35"),
            ToolField(key="initial_pose_ground_normal_radius_m", label="初始化地面法线半径 m", value="0.80"),
            ToolField(key="initial_pose_ground_max_slope_deg", label="初始化最大地面坡度 °", value="30"),
            ToolField(key="pose_topic", label="定位 Topic", value="/ndt_pose"),
            ToolField(key="path_topic", label="路径 Topic", value="/plan"),
            ToolField(key="refresh_hz", label="刷新频率 Hz", value="10"),
            ToolField(key="timeout_ms", label="连接超时 ms", value="8000"),
            ToolField(key="output_dir", label="快照输出目录", value=str(ROOT_DIR / "output_nav")),
        ],
    ),
    ToolDefinition(
        key="imu_calibration",
        title="IMU 标定",
        subtitle="Allan 方差与噪声参数",
        description="读取 rosbag2 SQLite3 db3 中的 sensor_msgs/msg/Imu，计算 gyro/accel Allan deviation、噪声密度、随机游走和 bias instability。",
        primary_action="开始标定",
        secondary_action="选择",
        fields=[
            ToolField(key="bag_path", label="rosbag2 db3", value="G:/humble_loc/bags/livox_imu_allan_20260916_120110_0.db3", placeholder="G:/path/imu_0.db3"),
            ToolField(key="topic", label="IMU Topic", value="/livox/imu", placeholder="/livox/imu"),
            ToolField(key="start_s", label="起始秒", value="0"),
            ToolField(key="duration_s", label="分析时长秒", value="0"),
            ToolField(key="stride", label="抽样步长", value="1"),
            ToolField(key="max_samples", label="最大样本数", value="500000"),
            ToolField(key="min_tau_s", label="最小 Tau 秒", value="0.01"),
            ToolField(key="max_tau_s", label="最大 Tau 秒", value="1000"),
            ToolField(key="points_per_axis", label="Tau 点数", value="48"),
        ],
    ),
]


def _default_enabled_map() -> Dict[str, bool]:
    return {tool.key: True for tool in ALL_TOOL_DEFINITIONS}


def load_tool_module_config() -> Dict[str, bool]:
    defaults = _default_enabled_map()
    if not MODULE_CONFIG_PATH.exists():
        return defaults

    try:
        raw = json.loads(MODULE_CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return defaults

    enabled_tools = raw.get("enabled_tools", {})
    if not isinstance(enabled_tools, dict):
        return defaults

    normalized = defaults.copy()
    for key, value in enabled_tools.items():
        if key in normalized:
            normalized[key] = bool(value)
    return normalized


def save_default_tool_module_config() -> None:
    if MODULE_CONFIG_PATH.exists():
        return
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "enabled_tools": _default_enabled_map(),
    }
    MODULE_CONFIG_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_tool_definitions() -> List[ToolDefinition]:
    enabled_map = load_tool_module_config()
    return [tool for tool in ALL_TOOL_DEFINITIONS if enabled_map.get(tool.key, True)]


def is_tool_enabled(tool_key: str) -> bool:
    enabled_map = load_tool_module_config()
    return enabled_map.get(tool_key, False)


save_default_tool_module_config()
