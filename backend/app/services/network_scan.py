import concurrent.futures
import csv
import os
from pathlib import Path
import re
import socket
import subprocess
import time
from typing import Dict, List, Optional

from app.models import ToolRunResponse
from app.services.system_info import get_system_info


WINDOWS_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


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
    try:
        if os.name == "nt":
            result = _run_command(["arp", "-a", ip], timeout=2.0)
            text = result.stdout
            pattern = re.compile(r"(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F\-]{17})\s+(\S+)")
            for match in pattern.finditer(text):
                if match.group(1) == ip:
                    return match.group(2).lower(), match.group(3)
        else:
            result = _run_command(["arp", "-n", ip], timeout=2.0)
            text = result.stdout
            pattern = re.compile(r"(\d+\.\d+\.\d+\.\d+)\s+\S+\s+([0-9a-fA-F:]{17})")
            for match in pattern.finditer(text):
                if match.group(1) == ip:
                    return match.group(2).lower(), ""
    except Exception:
        pass
    return "", ""


def resolve_hostname(ip: str):
    try:
        host, _, _ = socket.gethostbyaddr(ip)
        return host
    except Exception:
        return ""


def check_port(ip: str, port: int, timeout: float = 0.25):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            return sock.connect_ex((ip, port)) == 0
    except Exception:
        return False


def scan_one_ip(ip: str, timeout_ms: int) -> Dict[str, str]:
    alive, latency = ping_ip(ip, timeout_ms)
    hostname = ""
    mac = ""
    arp_type = ""
    port_22 = ""
    note = ""

    if alive:
        hostname = resolve_hostname(ip)
        time.sleep(0.03)
        mac, arp_type = lookup_arp(ip)
        port_22 = "开" if check_port(ip, 22, timeout=0.25) else "关"

        notes = []
        if hostname:
            notes.append(f"主机名={hostname}")
        if mac:
            notes.append(f"MAC={mac}")
        if port_22 == "开":
            notes.append("可能可SSH连接")
        elif port_22 == "关":
            notes.append("22端口未开或被拦截")
        note = "；".join(notes) if notes else "在线设备"

    return {
        "ip": ip,
        "status": "在线" if alive else "离线",
        "latency": latency,
        "hostname": hostname,
        "mac": mac,
        "arp_type": arp_type,
        "port_22": port_22,
        "note": note,
    }


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
    rows: List[Dict[str, str]] = []
    logs = [
        f"[INFO] 本机IP: {system_info.local_ip}",
        f"[INFO] 开始扫描 {prefix}.{start} ~ {prefix}.{end}，线程数={threads}，超时={timeout_ms}ms",
    ]

    with concurrent.futures.ThreadPoolExecutor(max_workers=threads) as executor:
        future_map = {executor.submit(scan_one_ip, ip, timeout_ms): ip for ip in targets}
        for future in concurrent.futures.as_completed(future_map):
            ip = future_map[future]
            try:
                row = future.result()
            except Exception as exc:
                row = {
                    "ip": ip,
                    "status": "错误",
                    "latency": "",
                    "hostname": "",
                    "mac": "",
                    "arp_type": "",
                    "port_22": "",
                    "note": f"扫描异常: {exc}",
                }
            rows.append(row)
            if row["status"] == "在线":
                logs.append(
                    f"[INFO] 发现在线设备: {row['ip']} | 主机名={row['hostname'] or '未知'} | MAC={row['mac'] or '未知'} | SSH={row['port_22'] or '未知'}"
                )

    rows.sort(key=lambda row: [int(part) for part in row["ip"].split(".")])
    alive_count = sum(1 for row in rows if row["status"] == "在线")
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
