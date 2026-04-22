"""旧桌面版局域网扫描工具。

该模块包含 Tkinter 页面、ping 扫描、ARP/MAC 解析和 CSV 导出逻辑。当前 Web
主线已经有独立的后端网络扫描服务，后续新增扫描能力应优先沉淀到
`backend/app/services/network_scan.py` 或 C++ 网络模块。
"""

import csv
import os
import queue
import re
import socket
import subprocess
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from ros_tool_suite.shared_ui import (
    apply_suite_theme,
    make_card,
    style_text_widget,
    apply_log_tags,
    append_tagged_text,
)


class NetworkScannerApp:
    """旧桌面版局域网扫描页面。

    输入为 Tk 容器，页面内部调度 ping、ARP、主机名和端口探测。Web 主线对应
    能力位于后端 `network_scan.py`。
    """

    def __init__(self, root, embedded=False):
        self.root = root
        self.embedded = embedded
        if not embedded and isinstance(root, (tk.Tk, tk.Toplevel)):
            self.root.title("局域网扫描工具")
            self.root.geometry("1180x720")
            self.root.minsize(1000, 620)

        self.stop_flag = False
        self.result_queue = queue.Queue()
        self.results = []
        self.total_targets = 0
        self.finished_targets = 0
        self.alive_count = 0
        self.scan_thread = None

        apply_suite_theme(root)
        self._build_ui()
        self._poll_queue()

    def _build_ui(self):
        shell = ttk.Frame(self.root, style="App.TFrame", padding=14)
        shell.pack(fill="both", expand=True)

        ttk.Label(shell, text="局域网扫描", style="Title.TLabel").pack(anchor="w")
        ttk.Label(shell, text="统一风格界面，不改扫描逻辑。", style="SubTitle.TLabel").pack(anchor="w", pady=(2, 12))

        top_card, top = make_card(shell, padding=14)
        top_card.pack(fill="x", pady=(0, 12))

        # 参数区
        row1 = ttk.Frame(top)
        row1.pack(fill="x", pady=4)

        ttk.Label(row1, text="网段前缀 x.x.x").pack(side="left")
        self.prefix_var = tk.StringVar(value="192.168.43")
        ttk.Entry(row1, textvariable=self.prefix_var, width=18, style="Suite.TEntry").pack(side="left", padx=6)

        ttk.Label(row1, text="起始").pack(side="left", padx=(12, 0))
        self.start_var = tk.StringVar(value="1")
        ttk.Entry(row1, textvariable=self.start_var, width=6, style="Suite.TEntry").pack(side="left", padx=6)

        ttk.Label(row1, text="结束").pack(side="left")
        self.end_var = tk.StringVar(value="245")
        ttk.Entry(row1, textvariable=self.end_var, width=6, style="Suite.TEntry").pack(side="left", padx=6)

        ttk.Label(row1, text="线程数").pack(side="left", padx=(12, 0))
        self.threads_var = tk.StringVar(value="64")
        ttk.Entry(row1, textvariable=self.threads_var, width=6, style="Suite.TEntry").pack(side="left", padx=6)

        ttk.Label(row1, text="超时(ms)").pack(side="left", padx=(12, 0))
        self.timeout_var = tk.StringVar(value="400")
        ttk.Entry(row1, textvariable=self.timeout_var, width=8, style="Suite.TEntry").pack(side="left", padx=6)

        row2 = ttk.Frame(top)
        row2.pack(fill="x", pady=4)

        ttk.Label(row2, text="MAC关键字过滤").pack(side="left")
        self.mac_filter_var = tk.StringVar(value="")
        ttk.Entry(row2, textvariable=self.mac_filter_var, width=20, style="Suite.TEntry").pack(side="left", padx=6)

        ttk.Label(row2, text="仅显示在线").pack(side="left", padx=(12, 0))
        self.only_alive_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row2, variable=self.only_alive_var, command=self.refresh_table, style="Suite.TCheckbutton").pack(side="left")

        ttk.Label(row2, text="关键字搜索").pack(side="left", padx=(12, 0))
        self.keyword_var = tk.StringVar(value="")
        keyword_entry = ttk.Entry(row2, textvariable=self.keyword_var, width=22, style="Suite.TEntry")
        keyword_entry.pack(side="left", padx=6)
        keyword_entry.bind("<KeyRelease>", lambda e: self.refresh_table())

        self.btn_start = ttk.Button(row2, text="开始扫描", command=self.start_scan, style="Primary.TButton")
        self.btn_start.pack(side="left", padx=(16, 6))

        self.btn_stop = ttk.Button(row2, text="停止扫描", command=self.stop_scan, state="disabled", style="Secondary.TButton")
        self.btn_stop.pack(side="left", padx=6)

        self.btn_refresh = ttk.Button(row2, text="刷新表格", command=self.refresh_table, style="Soft.TButton")
        self.btn_refresh.pack(side="left", padx=6)

        self.btn_export = ttk.Button(row2, text="导出CSV", command=self.export_csv, style="Soft.TButton")
        self.btn_export.pack(side="left", padx=6)

        # 状态区
        status_card, status_frame = make_card(shell, padding=14)
        status_card.pack(fill="x", pady=(0, 12))

        self.progress = ttk.Progressbar(status_frame, orient="horizontal", mode="determinate", style="Suite.Horizontal.TProgressbar")
        self.progress.pack(fill="x", pady=6)

        info_row = ttk.Frame(status_frame)
        info_row.pack(fill="x")

        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(info_row, textvariable=self.status_var).pack(side="left")

        self.summary_var = tk.StringVar(value="在线设备: 0 | 已完成: 0/0")
        ttk.Label(info_row, textvariable=self.summary_var).pack(side="right")

        # 表格区
        table_card, table_frame = make_card(shell, padding=12)
        table_card.pack(fill="both", expand=True, pady=(0, 12))

        columns = (
            "ip", "status", "latency", "hostname", "mac", "arp_type", "port_22", "note"
        )

        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", style="Suite.Treeview")
        self.tree.heading("ip", text="IP")
        self.tree.heading("status", text="状态")
        self.tree.heading("latency", text="延迟(ms)")
        self.tree.heading("hostname", text="主机名")
        self.tree.heading("mac", text="MAC")
        self.tree.heading("arp_type", text="ARP类型")
        self.tree.heading("port_22", text="SSH(22)")
        self.tree.heading("note", text="备注")

        self.tree.column("ip", width=120, anchor="center")
        self.tree.column("status", width=70, anchor="center")
        self.tree.column("latency", width=85, anchor="center")
        self.tree.column("hostname", width=180, anchor="w")
        self.tree.column("mac", width=150, anchor="center")
        self.tree.column("arp_type", width=80, anchor="center")
        self.tree.column("port_22", width=70, anchor="center")
        self.tree.column("note", width=360, anchor="w")

        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview, style="Suite.Vertical.TScrollbar")
        hsb = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview, style="Suite.Horizontal.TScrollbar")
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)

        # 日志区
        log_frame = ttk.LabelFrame(shell, text="日志", padding=8, style="Section.TLabelframe")
        log_frame.pack(fill="x")

        self.log_text = tk.Text(log_frame, height=8, wrap="word")
        self.log_text.pack(fill="both", expand=True)
        style_text_widget(self.log_text, height=8)
        apply_log_tags(self.log_text)

    def log(self, text):
        ts = time.strftime("%H:%M:%S")
        append_tagged_text(self.log_text, f"[{ts}] {text}\n")
        self.log_text.see("end")

    def validate_inputs(self):
        prefix = self.prefix_var.get().strip()
        start = self.start_var.get().strip()
        end = self.end_var.get().strip()
        threads = self.threads_var.get().strip()
        timeout = self.timeout_var.get().strip()

        if not re.fullmatch(r"\d{1,3}\.\d{1,3}\.\d{1,3}", prefix):
            raise ValueError("网段前缀格式错误，应为 x.x.x，例如 192.168.43")

        parts = prefix.split(".")
        for p in parts:
            n = int(p)
            if not (0 <= n <= 255):
                raise ValueError("网段前缀中的每一段都必须在 0~255 之间")

        start_num = int(start)
        end_num = int(end)
        thread_num = int(threads)
        timeout_num = int(timeout)

        if not (1 <= start_num <= 254 and 1 <= end_num <= 254 and start_num <= end_num):
            raise ValueError("扫描范围必须在 1~254，且起始值不能大于结束值")

        if not (1 <= thread_num <= 512):
            raise ValueError("线程数建议在 1~512")

        if not (50 <= timeout_num <= 5000):
            raise ValueError("超时建议在 50~5000 ms")

        return prefix, start_num, end_num, thread_num, timeout_num

    def clear_results(self):
        self.results = []
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.progress["value"] = 0
        self.alive_count = 0
        self.finished_targets = 0
        self.total_targets = 0
        self.summary_var.set("在线设备: 0 | 已完成: 0/0")

    def start_scan(self):
        if self.scan_thread and self.scan_thread.is_alive():
            messagebox.showwarning("提示", "扫描正在进行中")
            return

        try:
            prefix, start_num, end_num, thread_num, timeout_num = self.validate_inputs()
        except Exception as e:
            messagebox.showerror("输入错误", str(e))
            return

        self.clear_results()
        self.stop_flag = False
        self.total_targets = end_num - start_num + 1

        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.status_var.set("正在扫描...")
        self.log(f"开始扫描 {prefix}.{start_num} ~ {prefix}.{end_num}，线程数={thread_num}，超时={timeout_num}ms")

        self.scan_thread = threading.Thread(
            target=self.scan_network,
            args=(prefix, start_num, end_num, thread_num, timeout_num),
            daemon=True
        )
        self.scan_thread.start()

    def stop_scan(self):
        self.stop_flag = True
        self.log("收到停止请求，正在结束扫描...")
        self.status_var.set("正在停止...")

    def scan_network(self, prefix, start_num, end_num, thread_num, timeout_num):
        """按网段并发扫描。

        结果通过队列回传给 UI 线程，避免 worker 线程直接操作 Tk 控件。
        """
        import concurrent.futures

        targets = [f"{prefix}.{i}" for i in range(start_num, end_num + 1)]

        with concurrent.futures.ThreadPoolExecutor(max_workers=thread_num) as executor:
            future_map = {
                executor.submit(self.scan_one_ip, ip, timeout_num): ip for ip in targets
            }

            for future in concurrent.futures.as_completed(future_map):
                if self.stop_flag:
                    break

                ip = future_map[future]
                try:
                    result = future.result()
                except Exception as e:
                    result = {
                        "ip": ip,
                        "status": "错误",
                        "latency": "",
                        "hostname": "",
                        "mac": "",
                        "arp_type": "",
                        "port_22": "",
                        "note": f"扫描异常: {e}"
                    }

                self.result_queue.put(("result", result))

        self.result_queue.put(("done", None))

    def scan_one_ip(self, ip, timeout_ms):
        alive, latency = self.ping_ip(ip, timeout_ms)

        hostname = ""
        mac = ""
        arp_type = ""
        port_22 = ""
        note = ""

        if alive:
            hostname = self.resolve_hostname(ip)
            time.sleep(0.03)  # 给 ARP 表一点时间
            mac, arp_type = self.lookup_arp(ip)
            port_22 = "开" if self.check_port(ip, 22, timeout=0.25) else "关"

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
            "note": note
        }

    def ping_ip(self, ip, timeout_ms):
        """
        Windows ping:
        -n 1: 发1个包
        -w timeout_ms: 超时毫秒
        """
        try:
            result = subprocess.run(
                ["ping", "-n", "1", "-w", str(timeout_ms), ip],
                capture_output=True,
                text=True,
                encoding="gbk",
                errors="ignore"
            )
            output = result.stdout

            if result.returncode == 0:
                latency = ""
                m = re.search(r"时间[=<]\s*(\d+)\s*ms", output)
                if not m:
                    m = re.search(r"time[=<]\s*(\d+)\s*ms", output, re.IGNORECASE)
                if m:
                    latency = m.group(1)
                return True, latency
            return False, ""
        except Exception:
            # ping 是系统命令，目标不可达、编码异常或命令失败都按离线处理。
            return False, ""

    def lookup_arp(self, ip):
        try:
            result = subprocess.run(
                ["arp", "-a", ip],
                capture_output=True,
                text=True,
                encoding="gbk",
                errors="ignore"
            )
            text = result.stdout

            # Windows 示例:
            # 192.168.43.210         48-8f-4b-61-f0-78      动态
            pattern = re.compile(
                r"(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F\-]{17})\s+(\S+)"
            )
            for match in pattern.finditer(text):
                if match.group(1) == ip:
                    mac = match.group(2).lower()
                    arp_type = match.group(3)
                    return mac, arp_type
        except Exception:
            # ARP 表查询失败只影响 MAC 展示，不应中断单个 IP 的扫描结果。
            pass
        return "", ""

    def resolve_hostname(self, ip):
        try:
            host, _, _ = socket.gethostbyaddr(ip)
            return host
        except Exception:
            # 反向 DNS 在局域网里经常不可用，失败时保留空主机名。
            return ""

    def check_port(self, ip, port, timeout=0.25):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(timeout)
                return s.connect_ex((ip, port)) == 0
        except Exception:
            # 端口探测失败等价于端口未开放，避免网络异常打断整轮扫描。
            return False

    def _poll_queue(self):
        try:
            while True:
                item_type, payload = self.result_queue.get_nowait()

                if item_type == "result":
                    self.finished_targets += 1
                    self.results.append(payload)

                    if payload["status"] == "在线":
                        self.alive_count += 1
                        self.log(
                            f"发现在线设备: {payload['ip']} | 主机名={payload['hostname'] or '未知'} | "
                            f"MAC={payload['mac'] or '未知'} | SSH={payload['port_22'] or '未知'}"
                        )

                    progress_percent = (self.finished_targets / max(self.total_targets, 1)) * 100
                    self.progress["value"] = progress_percent
                    self.summary_var.set(
                        f"在线设备: {self.alive_count} | 已完成: {self.finished_targets}/{self.total_targets}"
                    )

                    self.refresh_table()

                elif item_type == "done":
                    self.btn_start.config(state="normal")
                    self.btn_stop.config(state="disabled")

                    if self.stop_flag:
                        self.status_var.set("已停止")
                        self.log("扫描已停止")
                    else:
                        self.status_var.set("扫描完成")
                        self.log(f"扫描完成，共发现在线设备 {self.alive_count} 台")

        except queue.Empty:
            pass

        self.root.after(120, self._poll_queue)

    def refresh_table(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

        mac_filter = self.mac_filter_var.get().strip().lower()
        keyword = self.keyword_var.get().strip().lower()
        only_alive = self.only_alive_var.get()

        def ip_sort_key(ip):
            try:
                return [int(x) for x in ip.split(".")]
            except Exception:
                return [999, 999, 999, 999]

        for row in sorted(self.results, key=lambda x: ip_sort_key(x["ip"])):
            if only_alive and row["status"] != "在线":
                continue

            if mac_filter and mac_filter not in (row["mac"] or "").lower():
                continue

            if keyword:
                merged = " ".join(str(row.get(k, "")) for k in row.keys()).lower()
                if keyword not in merged:
                    continue

            self.tree.insert(
                "",
                "end",
                values=(
                    row["ip"],
                    row["status"],
                    row["latency"],
                    row["hostname"],
                    row["mac"],
                    row["arp_type"],
                    row["port_22"],
                    row["note"]
                )
            )

    def export_csv(self):
        if not self.results:
            messagebox.showwarning("提示", "当前没有可导出的结果")
            return

        path = filedialog.asksaveasfilename(
            title="导出CSV",
            defaultextension=".csv",
            filetypes=[("CSV 文件", "*.csv")]
        )
        if not path:
            return

        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(["IP", "状态", "延迟(ms)", "主机名", "MAC", "ARP类型", "SSH(22)", "备注"])
                for row in self.results:
                    writer.writerow([
                        row["ip"],
                        row["status"],
                        row["latency"],
                        row["hostname"],
                        row["mac"],
                        row["arp_type"],
                        row["port_22"],
                        row["note"]
                    ])
            messagebox.showinfo("成功", f"已导出到:\n{path}")
            self.log(f"结果已导出到 {path}")
        except Exception as e:
            messagebox.showerror("导出失败", str(e))


def main():
    root = tk.Tk()
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        # DPI 设置只影响显示清晰度，失败时继续使用系统默认缩放。
        pass

    style = ttk.Style()
    try:
        style.theme_use("vista")
    except Exception:
        # 非 Windows 或主题不可用时保留默认 ttk 主题。
        pass

    app = NetworkScannerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
