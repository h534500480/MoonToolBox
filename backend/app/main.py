"""功能说明：平台 API 与四模块静态页面入口，支持刷新子页面。"""
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os

from app.api.routes import router
from app.paths import FRONTEND_DIST, PACKAGED


app = FastAPI(title="ROS Platform Backend", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[f"http://127.0.0.1:{os.environ['ROS_PLATFORM_PORT']}"] if PACKAGED else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")
if PACKAGED:
    from app.desktop_api import router as desktop_router
    app.include_router(desktop_router)

if FRONTEND_DIST.exists():
    @app.get("/tools/pcd-map", include_in_schema=False)
    @app.get("/tools/pcd-tile", include_in_schema=False)
    @app.get("/tools/global-relocalization", include_in_schema=False)
    @app.get("/tools/imu-calibration", include_in_schema=False)
    def platform_page():
        """让前端历史路由在直接访问或刷新时仍能加载入口。"""
        html = (FRONTEND_DIST / "index.html").read_text(encoding="utf-8")
        return HTMLResponse(html.replace("<head>", '<head><base href="/">', 1))

    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
