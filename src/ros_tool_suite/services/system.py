#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import socket


def detect_local_ip():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # No packets are sent; this asks Windows which local interface would be used.
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        return ip or "127.0.0.1"
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()
