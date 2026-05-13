"""ROS 数据接入层。

该模块为导航测试页提供统一的数据源抽象，当前先支持：
1. mock：本地静态示例数据，便于无 ROS 环境时调 UI
2. rosbridge：通过 WebSocket 调 rosbridge/rosapi 获取连接状态和 topic 列表

后续若要接入其他方式，只需要新增适配器并注册到工厂中，不需要重写前端。
"""

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from websockets.sync.client import connect

from app.models import RosDataSourceConfig, RosInspectionResponse, RosTopicItem, RosTopicListResponse


ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"
ROS_DATA_SOURCE_CONFIG_PATH = DATA_DIR / "ros_data_source.json"


DEFAULT_ROS_DATA_SOURCE_CONFIG = RosDataSourceConfig(
    provider="rosbridge",
    options={
        "url": "ws://127.0.0.1:9090",
        "rosapi_service": "/rosapi/topics_and_raw_types",
        "timeout_ms": "2500",
    },
)


@dataclass
class AdapterInspection:
    """封装适配器检测结果，避免路由层直接处理底层细节。"""

    status: str
    message: str
    capabilities: List[str]
    detected_hints: List[str]
    topics_count: int = 0


class BaseRosDataSourceAdapter:
    """ROS 数据源适配器基类。"""

    provider = "base"

    def inspect(self, config: RosDataSourceConfig) -> AdapterInspection:
        raise NotImplementedError

    def list_topics(self, config: RosDataSourceConfig) -> RosTopicListResponse:
        raise NotImplementedError


class MockRosDataSourceAdapter(BaseRosDataSourceAdapter):
    """用于界面联调的 mock 适配器。"""

    provider = "mock"

    def inspect(self, config: RosDataSourceConfig) -> AdapterInspection:
        return AdapterInspection(
            status="success",
            message="当前使用 mock 数据源，适合在没有机器狗或没有 ROS 环境时联调页面。",
            capabilities=["inspect", "list_topics", "mock_data"],
            detected_hints=["未连接真实 ROS；topic 列表来自本地静态样例。"],
            topics_count=len(self._topics()),
        )

    def list_topics(self, config: RosDataSourceConfig) -> RosTopicListResponse:
        return RosTopicListResponse(
            provider=self.provider,
            status="success",
            message="已返回 mock topic 列表。",
            topics=self._topics(),
        )

    def _topics(self) -> List[RosTopicItem]:
        return [
            RosTopicItem(name="/map", type="nav_msgs/OccupancyGrid"),
            RosTopicItem(name="/tf", type="tf2_msgs/TFMessage"),
            RosTopicItem(name="/amcl_pose", type="geometry_msgs/PoseWithCovarianceStamped"),
            RosTopicItem(name="/plan", type="nav_msgs/Path"),
            RosTopicItem(name="/scan", type="sensor_msgs/LaserScan"),
            RosTopicItem(name="/particlecloud", type="geometry_msgs/PoseArray"),
        ]


class RosbridgeRosDataSourceAdapter(BaseRosDataSourceAdapter):
    """通过 rosbridge websocket 接入 ROS 数据。"""

    provider = "rosbridge"

    def inspect(self, config: RosDataSourceConfig) -> AdapterInspection:
        url = config.options.get("url", "").strip()
        if not url:
            return AdapterInspection(
                status="error",
                message="未配置 rosbridge WebSocket 地址。",
                capabilities=[],
                detected_hints=["请填写类似 ws://127.0.0.1:9090 的地址。"],
                topics_count=0,
            )

        timeout = self._timeout_seconds(config)
        try:
            with connect(url, open_timeout=timeout, close_timeout=timeout) as ws:
                hints = [f"WebSocket 连接成功: {url}"]
                capabilities = ["inspect", "list_topics"]
                topics_response = self._call_topics_service(ws, config)
                if topics_response and topics_response.status == "success":
                    hints.append("检测到 rosapi 主题查询服务，可直接获取 topic 列表。")
                    capabilities.append("rosapi_topics")
                    return AdapterInspection(
                        status="success",
                        message="rosbridge 可用，且 rosapi 主题查询正常。",
                        capabilities=capabilities,
                        detected_hints=hints,
                        topics_count=len(topics_response.topics),
                    )

                hints.append("WebSocket 可连通，但 rosapi topic 查询未成功，可能只启了 rosbridge，没启 rosapi。")
                return AdapterInspection(
                    status="partial",
                    message="rosbridge 连接成功，但 topic 列表查询能力不完整。",
                    capabilities=capabilities,
                    detected_hints=hints,
                    topics_count=0,
                )
        except Exception as exc:
            return AdapterInspection(
                status="error",
                message=f"连接 rosbridge 失败: {exc}",
                capabilities=[],
                detected_hints=[
                    "如果机器狗使用的是 rosbridge，常见端口是 9090。",
                    "如果端口不通，可能实际用的是其他桥接方案，或桥接服务没启动。",
                ],
                topics_count=0,
            )

    def list_topics(self, config: RosDataSourceConfig) -> RosTopicListResponse:
        url = config.options.get("url", "").strip()
        if not url:
            return RosTopicListResponse(
                provider=self.provider,
                status="error",
                message="未配置 rosbridge WebSocket 地址。",
                topics=[],
            )

        timeout = self._timeout_seconds(config)
        try:
            with connect(url, open_timeout=timeout, close_timeout=timeout) as ws:
                response = self._call_topics_service(ws, config)
                if response:
                    return response
        except Exception as exc:
            return RosTopicListResponse(
                provider=self.provider,
                status="error",
                message=f"读取 rosbridge topic 失败: {exc}",
                topics=[],
            )

        return RosTopicListResponse(
            provider=self.provider,
            status="partial",
            message="rosbridge 已连接，但没有拿到可用的 topic 列表。",
            topics=[],
        )

    def _timeout_seconds(self, config: RosDataSourceConfig) -> float:
        raw = config.options.get("timeout_ms", "2500")
        try:
            timeout_ms = max(300, int(raw))
        except ValueError:
            timeout_ms = 2500
        return timeout_ms / 1000.0

    def _call_topics_service(self, ws, config: RosDataSourceConfig) -> Optional[RosTopicListResponse]:
        service_name = config.options.get("rosapi_service", "/rosapi/topics_and_raw_types").strip() or "/rosapi/topics_and_raw_types"
        timeout = self._timeout_seconds(config)

        service_response = self._call_service(ws, service_name, {}, timeout)
        if service_response and service_response.get("result") is True:
            values = service_response.get("values", {}) or {}
            topics = values.get("topics", []) or []
            types = values.get("types", []) or []
            typed_topics = [
                RosTopicItem(name=str(topic), type=str(types[index] if index < len(types) else ""))
                for index, topic in enumerate(topics)
            ]
            return RosTopicListResponse(
                provider=self.provider,
                status="success",
                message=f"已通过 {service_name} 获取 {len(typed_topics)} 个 topic。",
                topics=typed_topics,
            )

        fallback_response = self._call_service(ws, "/rosapi/topics", {}, timeout)
        if not fallback_response or fallback_response.get("result") is not True:
            return None

        fallback_values = fallback_response.get("values", {}) or {}
        topics = fallback_values.get("topics", []) or []
        typed_topics = [RosTopicItem(name=str(topic), type="") for topic in topics]
        return RosTopicListResponse(
            provider=self.provider,
            status="partial",
            message="已通过 /rosapi/topics 获取 topic 名称，但没有拿到消息类型。",
            topics=typed_topics,
        )

    def _call_service(self, ws, service: str, args: Dict[str, object], timeout: float) -> Optional[Dict[str, object]]:
        request_id = f"svc:{service}:{uuid.uuid4().hex}"
        ws.send(
            json.dumps(
                {
                    "op": "call_service",
                    "id": request_id,
                    "service": service,
                    "args": args,
                },
                ensure_ascii=False,
            )
        )

        while True:
            raw = ws.recv(timeout=timeout)
            if not isinstance(raw, str):
                continue
            payload = json.loads(raw)
            if payload.get("op") != "service_response":
                continue
            if payload.get("id") != request_id:
                continue
            return payload


def ensure_default_ros_data_source_config() -> None:
    """首次启动时落默认配置，避免前端没有配置可读。"""

    if ROS_DATA_SOURCE_CONFIG_PATH.exists():
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ROS_DATA_SOURCE_CONFIG_PATH.write_text(
        json.dumps(DEFAULT_ROS_DATA_SOURCE_CONFIG.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_ros_data_source_config() -> RosDataSourceConfig:
    ensure_default_ros_data_source_config()
    try:
        raw = json.loads(ROS_DATA_SOURCE_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return DEFAULT_ROS_DATA_SOURCE_CONFIG.model_copy(deep=True)
    try:
        parsed = RosDataSourceConfig.model_validate(raw)
    except Exception:
        return DEFAULT_ROS_DATA_SOURCE_CONFIG.model_copy(deep=True)
    return parsed


def save_ros_data_source_config(config: RosDataSourceConfig) -> RosDataSourceConfig:
    ensure_default_ros_data_source_config()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    normalized = RosDataSourceConfig(
        provider=(config.provider or "rosbridge").strip(),
        options={str(key): str(value) for key, value in config.options.items()},
    )
    ROS_DATA_SOURCE_CONFIG_PATH.write_text(
        json.dumps(normalized.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return normalized


def inspect_ros_data_source(config: Optional[RosDataSourceConfig] = None) -> RosInspectionResponse:
    normalized = config or load_ros_data_source_config()
    adapter = get_ros_data_source_adapter(normalized.provider)
    result = adapter.inspect(normalized)
    return RosInspectionResponse(
        provider=normalized.provider,
        status=result.status,
        message=result.message,
        capabilities=result.capabilities,
        detected_hints=result.detected_hints,
        topics_count=result.topics_count,
    )


def list_ros_topics(config: Optional[RosDataSourceConfig] = None) -> RosTopicListResponse:
    normalized = config or load_ros_data_source_config()
    adapter = get_ros_data_source_adapter(normalized.provider)
    return adapter.list_topics(normalized)


def get_ros_data_source_adapter(provider: str) -> BaseRosDataSourceAdapter:
    """按 provider 分发适配器，便于后续扩展新的接入方式。"""

    normalized = (provider or "").strip().lower()
    if normalized == "mock":
        return MockRosDataSourceAdapter()
    if normalized == "rosbridge":
        return RosbridgeRosDataSourceAdapter()
    raise RuntimeError(f"不支持的 ROS 数据源类型: {provider}")


ensure_default_ros_data_source_config()
