#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""旧桌面版系统信息辅助函数。"""

import socket


def detect_local_ip():
    """获取本机优先出站网卡 IP。

    这里连接公共 DNS 只用于让系统选择路由，不会真正发送 UDP 数据包；失败时
    返回回环地址，保证桌面壳顶部状态栏仍能渲染。
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # 不会真正发包，只让系统判断默认出站网卡。
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        return ip or "127.0.0.1"
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()
