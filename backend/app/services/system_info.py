import socket
from pathlib import Path

from app.models import SystemInfoResponse


ROOT_DIR = Path(__file__).resolve().parents[3]


def get_local_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except Exception:
        try:
            hostname = socket.gethostname()
            addresses = socket.gethostbyname_ex(hostname)[2]
            for address in addresses:
                if address and not address.startswith("127."):
                    return address
        except Exception:
            pass
    return "127.0.0.1"


def get_system_info() -> SystemInfoResponse:
    local_ip = get_local_ip()
    parts = local_ip.split(".")
    subnet_prefix = ".".join(parts[:3]) if len(parts) == 4 else ""
    return SystemInfoResponse(local_ip=local_ip, subnet_prefix=subnet_prefix, app_root=str(ROOT_DIR))
