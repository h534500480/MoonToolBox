"""功能说明：隔离运行发行包，验证端口冲突、实例识别、跨端口偏好和四个真实 C++ 算法。"""
import json
import os
from pathlib import Path
import socket
import sqlite3
import struct
import math
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener


def main():
    """仅启动给定测试程序，不终止占用端口的其他服务；退出时回收自己创建的进程。"""
    executable = Path(sys.argv[1]).resolve()
    command = [str(executable)] if executable.suffix == ".exe" else [sys.executable, str(executable)]
    environment = os.environ.copy()
    for name in ("PYTHONPATH", "PYTHONHOME", "ROS_PLATFORM_RESOURCES", "ROS_PLATFORM_DATA"):
        environment.pop(name, None)
    if executable.suffix == ".exe":
        environment["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
    opener = build_opener(ProxyHandler({}))
    processes = []
    with tempfile.TemporaryDirectory(prefix="ros-distribution-") as temporary, socket.socket() as occupied:
        directory = Path(temporary)
        occupied.bind(("127.0.0.1", 0))
        occupied.listen(1)
        blocked = occupied.getsockname()[1]

        def start(port):
            process = subprocess.Popen(command + ["--headless", "--no-browser", "--data-dir", str(directory), "--port", str(port)], env=environment, cwd=directory)
            processes.append(process)
            for _ in range(300):
                if process.poll() is not None:
                    raise AssertionError((directory / "desktop.log").read_text(encoding="utf-8"))
                try:
                    state = json.loads((directory / "instance.json").read_text())
                    url = f"http://127.0.0.1:{state['port']}"
                    with opener.open(url + "/api/desktop/instance", timeout=.5) as response:
                        if json.load(response)["instance"] == state["instance"]:
                            return process, state, url
                except (OSError, ValueError, KeyError):
                    pass
                time.sleep(.1)
            raise AssertionError("发行服务启动超时")

        def request(path, payload=None):
            req = Request(url + path, data=json.dumps(payload).encode() if payload is not None else None, headers={"Content-Type": "application/json", "Origin": url})
            with opener.open(req, timeout=90) as response:
                return json.load(response)

        try:
            process, state, url = start(blocked)
            assert state["port"] != blocked, "必须绕开占用端口"
            assert occupied.getsockname()[1] == blocked
            for route in ("/", "/tools/pcd-map", "/tools/imu-calibration"):
                with opener.open(url + route) as response:
                    assert b'<div id="app">' in response.read()
            assert {tool["key"] for tool in request("/api/tools")} == {"pcd_map", "pcd_tile", "global_relocalization_candidates", "ros_nav_test", "imu_calibration"}
            second = subprocess.run(command + ["--headless", "--no-browser", "--data-dir", str(directory)], env=environment, cwd=directory, timeout=30)
            assert second.returncode == 0 and process.poll() is None, "再次启动应复用既有实例"
            key = "ros-platform.navigation-tasks.v1"
            request("/api/desktop/profile", {"key": key, "value": '{"version":1,"tasks":[]}'})
            assert key in request("/api/desktop/profile")

            points = [(x*.2, y*.2, 0) for x in range(-20, 21) for y in range(-20, 21)]
            points += [(3, y*.2, z*.2) for y in range(-20, 21) for z in range(1, 16)]
            pcd = directory / "room.pcd"
            pcd.write_text(f'VERSION .7\nFIELDS x y z\nSIZE 4 4 4\nTYPE F F F\nCOUNT 1 1 1\nWIDTH {len(points)}\nHEIGHT 1\nVIEWPOINT 0 0 0 1 0 0 0\nPOINTS {len(points)}\nDATA ascii\n' + '\n'.join(' '.join(map(str, point)) for point in points))
            for tool, extra in [
                ("pcd_map", {"resolution": ".2"}),
                ("pcd_tile", {"tile_size": "3", "overlap": ".2", "format": "binary"}),
                ("global_relocalization_candidates", {"final_candidates_json": json.dumps([{"candidate_id": 1, "x": 0, "y": 0, "z": .35, "yaw_deg": 0, "roll_deg": 0, "pitch_deg": 0, "source": "manual_added", "locked": True}]), "config_json": json.dumps({"virtual_lidar": {"horizontal_step_deg": 5, "vertical_step_deg": 5}})}),
            ]:
                result = request(f"/api/tools/{tool}/run", {"values": {"input_pcd": str(pcd), "output_dir": str(directory / tool), **extra}})
                assert result["status"] == "success", result
                assert any((directory / tool).iterdir()), tool
            assert request("/api/tools/ros_nav_test/offline-map-preview?" + urlencode({"pcd_path": str(pcd), "voxel_leaf_m": .2, "max_points": 6000}))
            assert request("/api/tools/ros_nav_test/offline-map-raycast", {"origin": [0, 0, 3], "direction": [0, 0, -1]})["hit"]
            # 使用标准 CDR IMU 消息验证 SQLite 与 NumPy 的发行运行依赖。
            bag = directory / "imu.db3"
            with sqlite3.connect(bag) as connection:
                connection.execute("CREATE TABLE topics(id INTEGER, name TEXT, type TEXT, serialization_format TEXT)")
                connection.execute("CREATE TABLE messages(id INTEGER, topic_id INTEGER, timestamp INTEGER, data BLOB)")
                connection.execute("INSERT INTO topics VALUES(1, '/imu', 'sensor_msgs/msg/Imu', 'cdr')")
                for index in range(400):
                    seconds, nanos = divmod(1_000_000_000 + index * 10_000_000, 1_000_000_000)
                    values = [0.0] * 37
                    values[3] = 1.0
                    values[13:16] = [math.sin(index) * .001] * 3
                    values[25:28] = [.001 * math.cos(index), 0.0, 9.81]
                    payload = b'\x00\x01\x00\x00' + struct.pack('<iII', seconds, nanos, 4) + b'imu\x00' + struct.pack('<37d', *values)
                    connection.execute("INSERT INTO messages VALUES(?, 1, ?, ?)", (index, seconds * 1_000_000_000 + nanos, payload))
            connection.close()
            analysis = request("/api/tools/imu_calibration/analyze", {"bag_path": str(bag), "topic": "/imu"})
            assert analysis["status"] == "success" and analysis["sample"]["count"] == 400, analysis
            process.terminate()
            process.wait(timeout=15)
            (directory / "instance.json").unlink(missing_ok=True)
            process, next_state, url = start(0)
            assert next_state["instance"] != state["instance"]
            assert key in request("/api/desktop/profile"), "更换端口仍应保留任务"
            print("PASS: 隔离 PATH 启动、端口冲突、单实例、页面、跨端口存储、四个 C++ 算法及 IMU SQLite/NumPy 分析")
        finally:
            for process in processes:
                if process.poll() is None:
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
                    process.wait(timeout=15)
            time.sleep(.5)


if __name__ == "__main__":
    main()
