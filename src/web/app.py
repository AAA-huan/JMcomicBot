"""FastAPI 应用工厂；导入模块不会启动监听线程。"""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.web.api import create_api_router
from src.web.dependencies import WebDependencies
from src.web.errors import ApiError, install_error_handlers
from src.web.security import (
    LoginRateLimiter,
    WebSecurityMiddleware,
    allowed_web_origins,
)


def create_web_app(
    dependencies: WebDependencies,
    web_host: str = "127.0.0.1",
    web_port: int = 8000,
) -> FastAPI:
    """创建 WebUI ASGI 应用，后续阶段在此装配 API 路由。"""
    app = FastAPI(
        title="JMcomicBot WebUI",
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    static_root = Path(__file__).with_name("static")
    assets_root = static_root / "assets"
    index_path = static_root / "index.html"
    if not index_path.is_file() or not assets_root.is_dir():
        raise RuntimeError("WebUI 静态资源不完整，请重新安装正式发布包")

    app.add_middleware(
        WebSecurityMiddleware,
        allowed_hosts={web_host, "127.0.0.1", "localhost", "::1"},
        allowed_origins=allowed_web_origins(web_host, web_port),
    )
    install_error_handlers(app)
    app.include_router(create_api_router(dependencies, LoginRateLimiter()))
    app.mount("/assets", StaticFiles(directory=assets_root), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_spa(full_path: str, _request: Request) -> FileResponse:
        """为前端路由返回入口页，未知 API 保持 JSON 404。"""
        if full_path.startswith("api/"):
            raise ApiError(404, "API_NOT_FOUND", "接口不存在")
        return FileResponse(index_path, media_type="text/html")

    return app
