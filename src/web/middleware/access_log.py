"""为 /api/ 请求输出访问日志，复刻 http.server 行格式。

uvicorn 原生 access log 走标准 logging，与项目自定义 Logger 不兼容；
这里改用 FastAPI middleware 接入项目统一 Logger，只记 /api/ 请求，
避免 /assets/、/static/ 等静态资源刷屏。
"""

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from src.logging.logger_config import logger


class AccessLogMiddleware(BaseHTTPMiddleware):
    """仅记录 /api/ 请求；静态资源与 SPA 入口不输出，避免噪声。"""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # 静态资源与 SPA 入口不记，避免图标/CSS 等高频请求刷屏
        if not request.url.path.startswith("/api/"):
            return await call_next(request)
        response = await call_next(request)
        # client 在 Unix socket 等场景可能为 None，IP 用 - 占位
        client_ip = request.client.host if request.client is not None else "-"
        # query 非空时拼到路径后，与 http.server 行格式一致
        query = f"?{request.url.query}" if request.url.query else ""
        http_version = request.scope.get("http_version", "1.1")
        request_line = f"{request.method} {request.url.path}{query} HTTP/{http_version}"
        logger.info(f'{client_ip} - - "{request_line}" {response.status_code} -')
        return response
