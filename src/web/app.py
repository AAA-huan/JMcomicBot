"""FastAPI 应用工厂；导入模块不会启动监听线程。"""

from fastapi import FastAPI


def create_web_app() -> FastAPI:
    """创建 WebUI ASGI 应用，后续阶段在此装配 API 路由。"""
    return FastAPI(
        title="JMcomicBot WebUI",
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
