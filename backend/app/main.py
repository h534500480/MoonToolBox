"""功能说明：平台 API 与四模块静态页面入口，支持刷新子页面。"""
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app.api.routes import router


app = FastAPI(title="ROS Platform Backend", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
FRONTEND_DIST = FRONTEND_DIST.resolve()

if FRONTEND_DIST.exists():
    @app.get("/tools/pcd-map", include_in_schema=False)
    @app.get("/tools/pcd-tile", include_in_schema=False)
    @app.get("/tools/global-relocalization", include_in_schema=False)
    def platform_page():
        """让前端历史路由在直接访问或刷新时仍能加载入口。"""
        return FileResponse(FRONTEND_DIST / "index.html")

    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
