"""功能说明：仅发行版启用的实例校验与浏览器偏好存储，避免换端口导致任务看似丢失。"""
import json
import os
import threading
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from app.paths import DATA_ROOT

router = APIRouter(prefix="/api/desktop")
profile_path = DATA_ROOT / "browser-profile.json"
profile_lock = threading.Lock()


def allowed_key(key: str) -> bool:
    """只持久化用户设置，不保存导航执行租约，防止重启误恢复控制权。"""
    return (key.startswith("ros-platform.") and "owner" not in key.lower()) or key in {"moontoolbox.rosNavMobileState", "moontoolbox.rosPlatform.navConfig"}


@router.get("/instance")
def instance():
    return {"product": "ROSPlatform", "instance": os.environ["ROS_PLATFORM_INSTANCE"], "port": int(os.environ["ROS_PLATFORM_PORT"])}


def read_profile():
    if not profile_path.exists():
        return {}
    return json.loads(profile_path.read_text(encoding="utf-8"))


@router.get("/profile")
def profile():
    with profile_lock:
        return read_profile()


class ProfileValue(BaseModel):
    key: str
    value: str | None


@router.post("/profile")
def update_profile(payload: ProfileValue, request: Request):
    """逐键原子更新，保留其他标签页设置；拒绝外站写入本机偏好。"""
    if request.headers.get("origin") != f"http://127.0.0.1:{os.environ['ROS_PLATFORM_PORT']}":
        raise HTTPException(403, "仅允许当前平台页面保存设置")
    if not allowed_key(payload.key) or len(payload.value or "") > 5_000_000:
        raise HTTPException(400, "设置键或大小不合法")
    with profile_lock:
        values = read_profile()
        if payload.value is None:
            values.pop(payload.key, None)
        else:
            values[payload.key] = payload.value
        temporary = profile_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(values, ensure_ascii=False), encoding="utf-8")
        temporary.replace(profile_path)
    return {"status": "ok"}
