import concurrent.futures
import csv
import os
from pathlib import Path
import re
import socket
import subprocess
import threading
import time
from typing import Dict, Iterable, List, Optional, Tuple

from app.models import ToolRunResponse
from app.services.system_info import get_system_info


WINDOWS_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
HOSTNAME_LOOKUP_TIMEOUT_SEC = 0.8
NETBIOS_LOOKUP_TIMEOUT_SEC = 1.2
MDNS_DISCOVERY_TIMEOUT_SEC = 1.8
SSH_PROBE_TIMEOUT_SEC = 0.18
SOCKET_TIMEOUT_LOCK = threading.Lock()
MDNS_SERVICE_TYPES = [
    "_workstation._tcp.local.",
    "_ssh._tcp.local.",
    "_sftp-ssh._tcp.local.",
    "_http._tcp.local.",
    "_device-info._tcp.local.",
]


def _run_command(command: List[str], timeout: Optional[float] = None) -> subprocess.CompletedProcess:
    kwargs = {
        "capture_output": True,
        "text": True,
        "encoding": "gbk" if os.name == "nt" else "utf-8",
        "errors": "ignore",
        "timeout": timeout,
        "check": False,
    }
    if os.name == "nt":
        kwargs["creationflags"] = WINDOWS_NO_WINDOW
    return subprocess.run(command, **kwargs)


def ping_ip(ip: str, timeout_ms: int):
    try:
        if os.name == "nt":
            result = _run_command(["ping", "-n", "1", "-w", str(timeout_ms), ip], timeout=max(1.0, timeout_ms / 1000.0 + 1.0))
            output = result.stdout
        else:
            timeout_sec = max(1, int(timeout_ms / 1000))
            result = _run_command(["ping", "-c", "1", "-W", str(timeout_sec), ip], timeout=timeout_sec + 1.0)
            output = result.stdout

        if result.returncode == 0:
            latency = ""
            match = re.search(r"时间[=<]\s*(\d+)\s*ms", output)
            if not match:
                match = re.search(r"time[=<]\s*(\d+(\.\d+)?)\s*ms", output, re.IGNORECASE)
            if match:
                latency = match.group(1)
            return True, latency
        return False, ""
    except Exception:
        return False, ""


def lookup_arp(ip: str):
    return read_arp_table().get(ip, ("", ""))


def parse_arp_table(text: str) -> Dict[str, Tuple[str, str]]:
    rows: Dict[str, Tuple[str, str]] = {}
    if os.name == "nt":
        pattern = re.compile(r"(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F\-]{17})\s+(\S+)")
        for match in pattern.finditer(text):
            rows[match.group(1)] = (match.group(2).lower(), match.group(3))
        return rows

    pattern = re.compile(r"(\d+\.\d+\.\d+\.\d+)\s+\S+\s+([0-9a-fA-F:]{17})")
    for match in pattern.finditer(text):
        rows[match.group(1)] = (match.group(2).lower(), "")
    return rows


def read_arp_table() -> Dict[str, Tuple[str, str]]:
    try:
        command = ["arp", "-a"] if os.name == "nt" else ["arp", "-n"]
        result = _run_command(command, timeout=2.5)
        return parse_arp_table(result.stdout)
    except Exception:
        return {}


def resolve_hostname(ip: str):
    with SOCKET_TIMEOUT_LOCK:
        previous_timeout = socket.getdefaulttimeout()
        try:
            socket.setdefaulttimeout(HOSTNAME_LOOKUP_TIMEOUT_SEC)
            host, _, _ = socket.gethostbyaddr(ip)
            return host
        except Exception:
            return ""
        finally:
            socket.setdefaulttimeout(previous_timeout)


def resolve_netbios_name(ip: str) -> str:
    if os.name != "nt":
        return ""
    try:
        result = _run_command(["nbtstat", "-A", ip], timeout=NETBIOS_LOOKUP_TIMEOUT_SEC)
        for line in result.stdout.splitlines():
            if "<00>" not in line or "GROUP" in line.upper():
                continue
            name = line.split("<00>", 1)[0].strip()
            if name and not name.startswith("__"):
                return name
    except Exception:
        return ""
    return ""


def normalize_mdns_hostname(name: str) -> str:
    return name.strip().rstrip(".")


def addresses_from_zeroconf_info(info: object) -> List[str]:
    addresses: List[str] = []
    parsed_addresses = getattr(info, "parsed_addresses", None)
    if callable(parsed_addresses):
        try:
            addresses.extend(str(item) for item in parsed_addresses())
        except Exception:
            pass

    raw_addresses = getattr(info, "addresses", []) or []
    for raw_address in raw_addresses:
        try:
            addresses.append(socket.inet_ntoa(raw_address))
        except Exception:
            continue
    return [address for address in addresses if re.match(r"^\d+\.\d+\.\d+\.\d+$", address)]


def discover_mdns_names(target_ips: Iterable[str], timeout_sec: float = MDNS_DISCOVERY_TIMEOUT_SEC) -> Dict[str, str]:
    target_ip_set = set(target_ips)
    if not target_ip_set:
        return {}

    try:
        from zeroconf import ServiceBrowser, ServiceStateChange, Zeroconf
    except Exception:
        return {}

    mdns_names: Dict[str, str] = {}

    def handle_service_state_change(zeroconf: object, service_type: str, name: str, state_change: object) -> None:
        if state_change != ServiceStateChange.Added:
            return
        try:
            info = zeroconf.get_service_info(service_type, name, timeout=500)
        except Exception:
            return
        if not info:
            return

        hostname = normalize_mdns_hostname(str(getattr(info, "server", "") or name))
        if not hostname:
            return
        for address in addresses_from_zeroconf_info(info):
            if address in target_ip_set and address not in mdns_names:
                mdns_names[address] = hostname

    zeroconf = None
    browsers = []
    try:
        zeroconf = Zeroconf()
        for service_type in MDNS_SERVICE_TYPES:
            try:
                browsers.append(ServiceBrowser(zeroconf, service_type, handlers=[handle_service_state_change]))
            except Exception:
                continue
        time.sleep(max(0.2, timeout_sec))
    except Exception:
        return mdns_names
    finally:
        for browser in browsers:
            cancel = getattr(browser, "cancel", None)
            if callable(cancel):
                try:
                    cancel()
                except Exception:
                    pass
        if zeroconf is not None:
            try:
                zeroconf.close()
            except Exception:
                pass
    return mdns_names


def resolve_device_name(ip: str, mdns_names: Dict[str, str]) -> Tuple[str, str]:
    hostname = resolve_hostname(ip)
    if hostname:
        return hostname, "dns"
    mdns_name = mdns_names.get(ip, "")
    if mdns_name:
        return mdns_name, "mdns"
    netbios_name = resolve_netbios_name(ip)
    if netbios_name:
        return netbios_name, "netbios"
    return "", ""


def check_port(ip: str, port: int, timeout: float = 0.25):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            return sock.connect_ex((ip, port)) == 0
    except Exception:
        return False


def scan_reachability(ip: str, timeout_ms: int) -> Dict[str, str]:
    alive, latency = ping_ip(ip, timeout_ms)
    return {
        "ip": ip,
        "status": "在线" if alive else "离线",
        "latency": latency,
        "hostname": "",
        "mac": "",
        "arp_type": "",
        "port_22": "",
        "note": "",
    }


def enrich_online_row(row: Dict[str, str], arp_table: Dict[str, Tuple[str, str]], mdns_names: Dict[str, str]) -> Dict[str, str]:
    ip = row["ip"]
    hostname = ""
    hostname_source = ""
    mac = ""
    arp_type = ""
    port_22 = ""
    note = ""

    hostname, hostname_source = resolve_device_name(ip, mdns_names)
    mac, arp_type = arp_table.get(ip, ("", ""))
    port_22 = "开" if check_port(ip, 22, timeout=SSH_PROBE_TIMEOUT_SEC) else "关"

    notes = []
    if row.get("note"):
        notes.append(row["note"])
    if hostname:
        notes.append(f"主机名={hostname}({hostname_source})" if hostname_source else f"主机名={hostname}")
    if mac:
        notes.append(f"MAC={mac}")
    if port_22 == "开":
        notes.append("可能可SSH连接")
    elif port_22 == "关":
        notes.append("22端口未开或被拦截")
    note = "；".join(notes) if notes else "在线设备"

    return {
        "ip": ip,
        "status": row["status"],
        "latency": row["latency"],
        "hostname": hostname,
        "mac": mac,
        "arp_type": arp_type,
        "port_22": port_22,
        "note": note,
    }


def ip_sort_key(ip: str) -> List[int]:
    try:
        return [int(part) for part in ip.split(".")]
    except Exception:
        return [999, 999, 999, 999]


def collect_reachability(targets: Iterable[str], timeout_ms: int, threads: int) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=threads) as executor:
        future_map = {executor.submit(scan_reachability, ip, timeout_ms): ip for ip in targets}
        for future in concurrent.futures.as_completed(future_map):
            ip = future_map[future]
            try:
                rows.append(future.result())
            except Exception as exc:
                rows.append({
                    "ip": ip,
                    "status": "错误",
                    "latency": "",
                    "hostname": "",
                    "mac": "",
                    "arp_type": "",
                    "port_22": "",
                    "note": f"扫描异常: {exc}",
                })
    return rows


def enrich_online_rows(rows: List[Dict[str, str]], threads: int) -> Tuple[List[Dict[str, str]], int]:
    arp_table = read_arp_table()
    for row in rows:
        if row["status"] == "离线" and row["ip"] in arp_table:
            row["status"] = "在线"
            row["note"] = "ARP表发现，可能禁用 ICMP ping"
    online_rows = [row for row in rows if row["status"] == "在线"]
    if not online_rows:
        return rows, 0

    enriched_by_ip: Dict[str, Dict[str, str]] = {}
    enrich_threads = max(1, min(threads, 96, len(online_rows)))
    mdns_names = discover_mdns_names(row["ip"] for row in online_rows)
    with concurrent.futures.ThreadPoolExecutor(max_workers=enrich_threads) as executor:
        future_map = {executor.submit(enrich_online_row, row, arp_table, mdns_names): row["ip"] for row in online_rows}
        for future in concurrent.futures.as_completed(future_map):
            ip = future_map[future]
            try:
                enriched_by_ip[ip] = future.result()
            except Exception as exc:
                fallback = next((row for row in online_rows if row["ip"] == ip), None)
                if fallback:
                    enriched_by_ip[ip] = {
                        **fallback,
                        "note": f"在线，详情补全异常: {exc}",
                    }

    return [enriched_by_ip.get(row["ip"], row) for row in rows], len(mdns_names)


def export_scan_rows(rows: List[Dict[str, str]], output_path: str) -> str:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as file_obj:
        writer = csv.writer(file_obj)
        writer.writerow(["IP", "状态", "延迟(ms)", "主机名", "MAC", "ARP类型", "SSH(22)", "备注"])
        for row in rows:
            writer.writerow([
                row["ip"],
                row["status"],
                row["latency"],
                row["hostname"],
                row["mac"],
                row["arp_type"],
                row["port_22"],
                row["note"],
            ])
    return str(path)


def run_network_scan(values: Dict[str, str]) -> ToolRunResponse:
    system_info = get_system_info()
    prefix = values.get("prefix", "").strip() or system_info.subnet_prefix or "192.168.1"
    start = int(values.get("start", "").strip() or "1")
    end = int(values.get("end", "").strip() or "245")
    timeout_ms = int(values.get("timeout_ms", "").strip() or "400")
    threads = int(values.get("threads", "").strip() or "64")
    export_path = values.get("export_path", "").strip()

    start = max(1, min(254, start))
    end = max(start, min(254, end))
    threads = max(1, min(512, threads))
    timeout_ms = max(50, min(5000, timeout_ms))

    targets = [f"{prefix}.{index}" for index in range(start, end + 1)]
    logs = [
        f"[INFO] 本机IP: {system_info.local_ip}",
        f"[INFO] 开始扫描 {prefix}.{start} ~ {prefix}.{end}，线程数={threads}，超时={timeout_ms}ms",
    ]

    started_at = time.monotonic()
    rows = collect_reachability(targets, timeout_ms, threads)
    reachability_elapsed = time.monotonic() - started_at
    alive_count_before_enrich = sum(1 for row in rows if row["status"] == "在线")
    logs.append(f"[INFO] 连通性扫描完成：在线 {alive_count_before_enrich} 台，用时 {reachability_elapsed:.2f}s")

    enrich_started_at = time.monotonic()
    rows, mdns_count = enrich_online_rows(rows, threads)
    enrich_elapsed = time.monotonic() - enrich_started_at
    logs.append(f"[INFO] 在线设备详情补全完成，用时 {enrich_elapsed:.2f}s，mDNS匹配 {mdns_count} 台")

    rows.sort(key=lambda row: ip_sort_key(row["ip"]))
    alive_count = sum(1 for row in rows if row["status"] == "在线")
    for row in rows:
        if row["status"] == "在线":
            logs.append(
                f"[INFO] 发现在线设备: {row['ip']} | 主机名={row['hostname'] or '未知'} | MAC={row['mac'] or '未知'} | SSH={row['port_22'] or '未知'}"
            )
    logs.append(f"[INFO] 扫描完成，共发现在线设备 {alive_count} 台")

    data = {
        "rows": rows,
        "alive_count": alive_count,
        "finished_targets": len(rows),
        "total_targets": len(targets),
        "local_ip": system_info.local_ip,
        "subnet_prefix": system_info.subnet_prefix,
    }

    if export_path:
        csv_path = export_scan_rows(rows, export_path)
        data["export_path"] = csv_path
        logs.append(f"[INFO] 结果已导出到 {csv_path}")

    summary = f"扫描完成：在线设备 {alive_count} 台，已完成 {len(rows)}/{len(targets)}"
    return ToolRunResponse(tool="network_scan", status="success", summary=summary, logs=logs, data=data)
