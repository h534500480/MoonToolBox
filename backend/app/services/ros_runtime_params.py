"""ROS 运行时参数抓取服务。

该模块面向 ros_nav_test 页面，负责通过 rosbridge 调 ROS2 参数服务，
读取当前运行中的 Nav2 / NDT 关键节点参数，并按业务分组返回给前端展示。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import uuid4

from websockets.sync.client import connect

from app.models import (
    RosDataSourceConfig,
    RosRuntimeParamGroup,
    RosRuntimeParamNode,
    RosRuntimeParamsResponse,
    RosRuntimeParamSection,
)


RUNTIME_GROUPS: list[tuple[str, str, list[tuple[str, list[str]]]]] = [
    (
        "nav2",
        "Nav2",
        [
            ("规划", ["/planner_server"]),
            ("控制", ["/controller_server"]),
            ("行为与导航状态机", ["/behavior_server", "/bt_navigator"]),
            ("代价地图", ["/local_costmap/local_costmap", "/global_costmap/global_costmap"]),
        ],
    ),
    (
        "ndt",
        "NDT",
        [
            ("点云预处理", ["/cloud_filter_node", "/custom_to_pointcloud2", "/cloud_frame_rewriter"]),
            ("IMU 与滤波", ["/imu_source_bridge", "/ekf_filter_node"]),
            ("定位辅助与时序", [
                "/initialpose_bridge",
                "/map_odom_publisher",
                "/ndt_score_bridge",
                "/localization_startup_manager",
                "/ndt_health_monitor",
            ]),
            ("NDT 与地图", [
                "/ndt_scan_matcher",
                "/pcd_loader_service",
                "/map_server",
                "/lifecycle_manager_localization",
            ]),
        ],
    ),
]


def _timeout_seconds(config: RosDataSourceConfig) -> float:
    raw = config.options.get("timeout_ms", "8000")
    try:
        timeout_ms = max(8000, int(raw))
    except ValueError:
        timeout_ms = 8000
    return timeout_ms / 1000.0


def _service_name(node_name: str, suffix: str) -> str:
    normalized = node_name.rstrip("/")
    return f"{normalized}/{suffix}" if normalized else f"/{suffix}"


def _call_service(ws, service: str, args: dict[str, Any], timeout: float) -> dict[str, Any]:
    request_id = f"svc:{service}:{uuid4().hex}"
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
        if payload.get("op") != "service_response" or payload.get("id") != request_id:
            continue
        return payload


def _extract_service_values(response: dict[str, Any]) -> dict[str, Any]:
    values = response.get("values", {}) or {}
    if isinstance(values, dict) and "result" in values and isinstance(values["result"], dict):
        return values["result"]
    return values if isinstance(values, dict) else {}


def _decode_parameter_value(value: dict[str, Any]) -> Any:
    if not isinstance(value, dict):
        return value
    parameter_type = int(value.get("type", 0) or 0)
    if parameter_type == 1:
        return bool(value.get("bool_value", False))
    if parameter_type == 2:
        return int(value.get("integer_value", 0) or 0)
    if parameter_type == 3:
        return float(value.get("double_value", 0.0) or 0.0)
    if parameter_type == 4:
        return str(value.get("string_value", ""))
    if parameter_type == 5:
        return list(value.get("byte_array_value", []) or [])
    if parameter_type == 6:
        return list(value.get("bool_array_value", []) or [])
    if parameter_type == 7:
        return [int(item) for item in (value.get("integer_array_value", []) or [])]
    if parameter_type == 8:
        return [float(item) for item in (value.get("double_array_value", []) or [])]
    if parameter_type == 9:
        return [str(item) for item in (value.get("string_array_value", []) or [])]
    return None


def _load_node_runtime_params(ws, node_name: str, timeout: float) -> dict[str, Any]:
    list_service = _resolve_parameter_service(ws, node_name, "list_parameters", timeout)
    list_response = _call_service(
        ws,
        list_service,
        {"prefixes": [], "depth": 100},
        timeout,
    )
    if list_response.get("result") is not True:
        raise RuntimeError(str(list_response.get("values") or list_response))

    list_values = _extract_service_values(list_response)
    names = list_values.get("names", []) or []
    if not names:
        return {}

    get_service = _resolve_parameter_service(ws, node_name, "get_parameters", timeout)
    get_response = _call_service(
        ws,
        get_service,
        {"names": names},
        timeout,
    )
    if get_response.get("result") is not True:
        raise RuntimeError(str(get_response.get("values") or get_response))

    get_values = _extract_service_values(get_response)
    values = get_values.get("values", []) or []
    params: dict[str, Any] = {}
    for index, name in enumerate(names):
        params[str(name)] = _decode_parameter_value(values[index] if index < len(values) else {})
    return params


def _list_services(ws, timeout: float) -> list[str]:
    response = _call_service(ws, "/rosapi/services", {}, timeout)
    if response.get("result") is not True:
        return []
    values = _extract_service_values(response)
    services = values.get("services", []) or []
    return [str(item).strip() for item in services if str(item).strip()]


def _resolve_parameter_service(ws, node_name: str, suffix: str, timeout: float) -> str:
    direct_name = _service_name(node_name, suffix)
    services = _list_services(ws, timeout)
    if direct_name in services:
        return direct_name

    expected_suffix = direct_name
    candidates = [service for service in services if service.endswith(expected_suffix)]
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        exact_leaf = [service for service in candidates if service.rsplit("/", 2)[-2] == node_name.strip("/").split("/")[-1]]
        if len(exact_leaf) == 1:
            return exact_leaf[0]
        candidates.sort(key=len)
        return candidates[0]

    raise RuntimeError(f"Service {direct_name} does not exist")


def list_ros_runtime_params(config: RosDataSourceConfig) -> RosRuntimeParamsResponse:
    provider = (config.provider or "rosbridge").strip().lower()
    if provider != "rosbridge":
        return RosRuntimeParamsResponse(
            provider=provider,
            status="error",
            message="当前运行时参数窗口只支持 rosbridge 数据源。",
            updated_at=datetime.now().isoformat(timespec="seconds"),
            groups=[],
            failed_nodes=[],
        )

    url = config.options.get("url", "").strip()
    if not url:
        return RosRuntimeParamsResponse(
            provider=provider,
            status="error",
            message="未配置 rosbridge WebSocket 地址。",
            updated_at=datetime.now().isoformat(timespec="seconds"),
            groups=[],
            failed_nodes=[],
        )

    timeout = _timeout_seconds(config)
    groups: list[RosRuntimeParamGroup] = []
    failed_nodes: list[str] = []

    try:
        with connect(url, open_timeout=timeout, close_timeout=timeout) as ws:
            for group_key, group_label, sections in RUNTIME_GROUPS:
                section_items: list[RosRuntimeParamSection] = []
                for section_title, node_names in sections:
                    nodes: list[RosRuntimeParamNode] = []
                    for node_name in node_names:
                        try:
                            params = _load_node_runtime_params(ws, node_name, timeout)
                            nodes.append(RosRuntimeParamNode(node=node_name, params=params, error=""))
                        except Exception as exc:  # noqa: BLE001
                            error_message = str(exc)
                            failed_nodes.append(f"{node_name}: {error_message}")
                            nodes.append(RosRuntimeParamNode(node=node_name, params={}, error=error_message))
                    section_items.append(RosRuntimeParamSection(title=section_title, nodes=nodes))
                groups.append(RosRuntimeParamGroup(key=group_key, label=group_label, sections=section_items))
    except Exception as exc:  # noqa: BLE001
        return RosRuntimeParamsResponse(
            provider=provider,
            status="error",
            message=f"读取 ROS 运行时参数失败: {exc}",
            updated_at=datetime.now().isoformat(timespec="seconds"),
            groups=[],
            failed_nodes=[],
        )

    status = "partial" if failed_nodes else "success"
    message = "已读取 Nav2 / NDT 运行时参数。" if not failed_nodes else f"部分节点读取失败，共 {len(failed_nodes)} 个。"
    return RosRuntimeParamsResponse(
        provider=provider,
        status=status,
        message=message,
        updated_at=datetime.now().isoformat(timespec="seconds"),
        groups=groups,
        failed_nodes=failed_nodes,
    )
