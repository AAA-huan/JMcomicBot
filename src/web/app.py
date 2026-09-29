"""FastAPI 应用工厂；导入模块不会启动监听线程。"""

from fastapi import FastAPI

from src.web.api import create_api_router
from src.web.dependencies import WebDependencies


def create_web_app(dependencies: WebDependencies) -> FastAPI:
    """创建 WebUI ASGI 应用，后续阶段在此装配 API 路由。"""
    app = FastAPI(
        title="JMcomicBot WebUI",
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.include_router(create_api_router(dependencies))
    return app
