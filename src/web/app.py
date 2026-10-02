"""FastAPI 应用工厂；导入模块不会启动监听线程。"""

from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import AsyncIterator

import asyncio
import mimetypes

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.web.api import create_api_router
from src.web.dependencies import WebDependencies
from src.web.errors import ApiError, install_error_handlers
from src.web.events.broadcaster import StatusBroadcaster
from src.web.security import (
    LoginRateLimiter,
    WebSecurityMiddleware,
    allowed_web_origins,
    allows_any_host,
)


def create_web_app(
    dependencies: WebDependencies,
    web_host: str = "127.0.0.1",
    web_port: int = 7999,
    status_interval_seconds: float = 2.0,
    extra_origins: set[str] | None = None,
) -> FastAPI:
    """创建 WebUI ASGI 应用，装配 API、事件推送与静态资源。"""
    static_root = Path(__file__).with_name("static")
    assets_root = static_root / "assets"
    index_path = static_root / "index.html"
    if not index_path.is_file() or not assets_root.is_dir():
        raise RuntimeError("WebUI 静态资源不完整，请重新安装正式发布包")

    allowed_origins = allowed_web_origins(web_host, web_port, extra_origins)
    allow_any_host = allows_any_host(web_host)
    broadcaster = StatusBroadcaster(
        dependencies.event_bus,
        dependencies.system_service.get_status,
        interval_seconds=status_interval_seconds,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        """应用生命周期内运行状态广播，退出时取消任务。"""
        task = asyncio.create_task(broadcaster.run())
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    app = FastAPI(
        title="JMcomicBot WebUI",
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    app.add_middleware(
        WebSecurityMiddleware,
        allowed_hosts={web_host, "127.0.0.1", "localhost", "::1"},
        allowed_origins=allowed_origins,
        allow_any_host=allow_any_host,
    )
    install_error_handlers(app)
    app.include_router(
        create_api_router(
            dependencies, LoginRateLimiter(), allowed_origins, allow_any_host
        )
    )
    # 部分系统（如 Termux）的 MIME 数据库缺少 .mjs 映射；PDF.js 的
    # module worker 要求 JavaScript MIME 类型，这里显式声明保证跨平台一致。
    mimetypes.add_type("text/javascript", ".mjs")
    app.mount("/assets", StaticFiles(directory=assets_root), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_spa(full_path: str, _request: Request) -> FileResponse:
        """为前端路由返回入口页，未知 API 保持 JSON 404。"""
        if full_path.startswith("api/"):
            raise ApiError(404, "API_NOT_FOUND", "接口不存在")
        return FileResponse(index_path, media_type="text/html")

    return app
