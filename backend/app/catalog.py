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
        description="已接 C++ pcd_map_cli，当前可从 Web 界面触发真实地图生成。",
        primary_action="生成地图",
        secondary_action="选择",
        fields=[
            ToolField(key="input_pcd", label="输入 PCD", placeholder="G:/path/map.pcd"),
            ToolField(key="output_dir", label="输出目录", value="G:/ros_proj/ros_tool/output"),
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
        description="已接 C++ pcd_tile_cli，当前可执行切片骨架并输出 metadata。",
        primary_action="切分点云",
        secondary_action="选择",
        fields=[
            ToolField(key="input_pcd", label="输入 PCD", placeholder="G:/path/map.pcd"),
            ToolField(key="output_dir", label="输出目录", value=""),
            ToolField(key="tile_size", label="切片尺寸", value="20.0"),
            ToolField(key="overlap", label="重叠范围", value="0.0"),
            ToolField(key="format", label="输出格式", value="binary"),
            ToolField(key="zip_output", label="压缩输出", value="false"),
        ],
    ),
    ToolDefinition(
        key="network_scan",
        title="IP 扫描",
        subtitle="局域网扫描",
        description="已接 Python 后端真实扫描逻辑，支持主机名、MAC、SSH 和结果导出。",
        primary_action="开始扫描",
        secondary_action="导出",
        fields=[
            ToolField(key="prefix", label="网段前缀", value=""),
            ToolField(key="start", label="起始地址", value="1"),
            ToolField(key="end", label="结束地址", value="245"),
            ToolField(key="timeout_ms", label="超时毫秒", value="400"),
            ToolField(key="threads", label="线程数", value="64"),
        ],
    ),
    ToolDefinition(
        key="costmap",
        title="Costmap 回放",
        subtitle="Costmap 回放",
        description="解析 costmap YAML，支持帧回放、阈值高亮、Footprint 预览和 PNG/GIF 导出。",
        primary_action="加载 Costmap",
        secondary_action="选择",
        fields=[
            ToolField(key="yaml_path", label="输入 YAML", placeholder="G:/path/costmap.yaml"),
            ToolField(key="output_dir", label="导出目录", value="G:/ros_proj/ros_tool/output_costmap"),
            ToolField(key="fps", label="帧率 FPS", value="2.0"),
            ToolField(key="export_gif", label="导出 GIF", value="true"),
            ToolField(key="export_png", label="导出 PNG 序列", value="false"),
            ToolField(key="threshold", label="Lethal 阈值", value="99"),
            ToolField(key="show_lethal", label="显示 Lethal", value="true"),
            ToolField(key="show_footprint", label="显示 Footprint", value="true"),
            ToolField(key="footprint_length", label="机器人长度 m", value="0.70"),
            ToolField(key="footprint_width", label="机器人宽度 m", value="0.40"),
        ],
    ),
    ToolDefinition(
        key="ros_nav_test",
        title="ROS 定位导航测试",
        subtitle="定位导航可视化工作台",
        description="用于搭建 ROS 定位导航测试页，包含三维主视图、话题选择区和可折叠的可视化小窗列表。",
        primary_action="启动测试布局",
        secondary_action="选择",
        fields=[
            ToolField(key="ros_provider", label="接入方式", value="rosbridge"),
            ToolField(key="ros_bridge_url", label="Bridge 地址", value="ws://127.0.0.1:9090"),
            ToolField(key="ros_api_service", label="Topic 查询服务", value="/rosapi/topics_and_raw_types"),
            ToolField(key="fixed_frame", label="固定坐标系", value="map"),
            ToolField(key="map_topic", label="地图 Topic", value="/map"),
            ToolField(key="pose_topic", label="定位 Topic", value="/ndt_pose"),
            ToolField(key="path_topic", label="路径 Topic", value="/plan"),
            ToolField(key="refresh_hz", label="刷新频率 Hz", value="10"),
            ToolField(key="timeout_ms", label="连接超时 ms", value="2500"),
            ToolField(key="output_dir", label="快照输出目录", value="G:/ros_proj/ros_tool/output_nav"),
        ],
    ),
    ToolDefinition(
        key="mtslash_export",
        title="MTSlash 导出",
        subtitle="帖子转章节 TXT",
        description="按合规限速模式抓取你有权访问的 mtslash.life 单帖正文，并生成目录和分章节 TXT。",
        primary_action="导出 TXT",
        secondary_action="选择",
        fields=[
            ToolField(key="thread_url", label="帖子 URL", placeholder="https://mtslash.life/thread-123-1-1.html"),
            ToolField(key="output_dir", label="输出目录", value=""),
            ToolField(key="browser_mode", label="浏览器模式", value="false"),
            ToolField(key="browser_type", label="浏览器", value="edge"),
            ToolField(key="only_thread_author", label="只导出楼主", value="true"),
            ToolField(key="max_pages", label="最大页数", value="20"),
            ToolField(key="delay_seconds", label="请求间隔秒", value="1.5"),
            ToolField(key="cookie", label="Cookie（可选）", placeholder="仅填写你自己账号的会话 Cookie"),
            ToolField(key="login_username", label="登录账号（可选）", placeholder="不填 Cookie 时使用"),
            ToolField(key="login_password", label="登录密码（可选）", placeholder="只用于本次内存登录"),
            ToolField(key="captcha_code", label="验证码", placeholder="先点获取验证码，再人工输入"),
            ToolField(key="login_session_id", label="登录会话 ID", value=""),
            ToolField(key="question_id", label="安全提问编号", value="0"),
            ToolField(key="answer", label="安全提问答案", value=""),
            ToolField(key="user_agent", label="User-Agent", value="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
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
