"""AccessLogMiddleware 访问日志单元测试。"""

import asyncio
from typing import List

import pytest
from starlette.requests import Request
from starlette.responses import Response

from src.web.middleware.access_log import AccessLogMiddleware


class _Recorder:
    """替换 logger，仅收集 info 调用的消息。"""

    def __init__(self) -> None:
        self.calls: List[str] = []

    def info(self, message: str) -> None:
        self.calls.append(message)


def _make_request(
    method: str = "GET",
    path: str = "/api/messages",
    query: str = "",
    client_host: str | None = "127.0.0.1",
    http_version: str = "1.1",
) -> Request:
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "raw_path": path.encode(),
        "query_string": query.encode(),
        "headers": [],
        "client": (client_host, 12345) if client_host is not None else None,
        "http_version": http_version,
        "scheme": "http",
        "server": ("127.0.0.1", 8000),
        "root_path": "",
        "app": None,
    }

    async def receive():  # pragma: no cover
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(scope, receive)


def _make_middleware(recorder: _Recorder) -> AccessLogMiddleware:
    """构造 middleware 并替换其模块级 logger。"""

    async def dummy_app(scope, receive, send):  # pragma: no cover
        return None

    middleware = AccessLogMiddleware(dummy_app)
    # dispatch 内部引用模块级 logger，直接替换模块属性
    import src.web.middleware.access_log as module

    module.logger = recorder  # type: ignore[attr-defined]
    return middleware


def _make_call_next(status_code: int = 200):
    async def call_next(request: Request) -> Response:
        return Response(status_code=status_code)

    return call_next


def _run(middleware: AccessLogMiddleware, request: Request, status_code: int = 200):
    asyncio.run(middleware.dispatch(request, _make_call_next(status_code)))


def test_api_get_request_logged_as_http_server_line() -> None:
    """GET /api/ 请求记一行 IP - - \"请求行\" 状态 -。"""
    recorder = _Recorder()
    middleware = _make_middleware(recorder)
    _run(middleware, _make_request())
    assert recorder.calls == ['127.0.0.1 - - "GET /api/messages HTTP/1.1" 200 -']


def test_api_request_with_query_keeps_query_string() -> None:
    """query 非空时拼到路径后，保留原始查询串。"""
    recorder = _Recorder()
    middleware = _make_middleware(recorder)
    request = _make_request(query="since_id=0&limit=1")
    _run(middleware, request)
    assert recorder.calls == [
        '127.0.0.1 - - "GET /api/messages?since_id=0&limit=1 HTTP/1.1" 200 -'
    ]


def test_post_request_and_non_200_status_recorded() -> None:
    """写方法与非 200 状态码同样记录。"""
    recorder = _Recorder()
    middleware = _make_middleware(recorder)
    request = _make_request(method="POST", path="/api/v1/manga/123/download")
    _run(middleware, request, status_code=202)
    assert recorder.calls == [
        '127.0.0.1 - - "POST /api/v1/manga/123/download HTTP/1.1" 202 -'
    ]


def test_security_rejected_status_still_logged() -> None:
    """被安全 middleware 拒绝的 403 也记一行访问日志。"""
    recorder = _Recorder()
    middleware = _make_middleware(recorder)
    request = _make_request(method="POST", path="/api/v1/auth/setup")
    _run(middleware, request, status_code=403)
    assert recorder.calls == ['127.0.0.1 - - "POST /api/v1/auth/setup HTTP/1.1" 403 -']


def test_http_version_reflected_in_request_line() -> None:
    """http_version 非 1.1 时行内取实际版本。"""
    recorder = _Recorder()
    middleware = _make_middleware(recorder)
    request = _make_request(http_version="2.0")
    _run(middleware, request)
    assert recorder.calls == ['127.0.0.1 - - "GET /api/messages HTTP/2.0" 200 -']


def test_missing_client_uses_dash_placeholder() -> None:
    """Unix socket 等场景 client 为 None 时 IP 用 - 占位。"""
    recorder = _Recorder()
    middleware = _make_middleware(recorder)
    request = _make_request(client_host=None)
    _run(middleware, request)
    assert recorder.calls == ['- - - "GET /api/messages HTTP/1.1" 200 -']


@pytest.mark.parametrize(
    "path",
    ["/assets/index.js", "/static/icons/icon-192.png", "/manifest.webmanifest", "/"],
)
def test_static_and_spa_paths_not_logged(path: str) -> None:
    """静态资源与 SPA 入口不记访问日志。"""
    recorder = _Recorder()
    middleware = _make_middleware(recorder)
    _run(middleware, _make_request(path=path))
    assert recorder.calls == []
