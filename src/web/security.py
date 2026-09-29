"""WebUI Host、Origin、CSRF、安全响应头和登录限速。"""

from collections import defaultdict, deque
from secrets import compare_digest
from threading import Lock
from time import monotonic
from typing import Deque
from uuid import uuid4

from fastapi import Request, status
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from src.web.errors import error_response

CSRF_COOKIE_NAME = "jmbot_csrf"
CSRF_HEADER_NAME = "X-CSRF-Token"
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_CSRF_EXEMPT_PATHS = {"/api/v1/auth/setup", "/api/v1/auth/login"}


class LoginRateLimiter:
    """按直连客户端 IP 限制时间窗口内的登录失败次数。"""

    def __init__(self, maximum_failures: int = 5, window_seconds: int = 60) -> None:
        self.maximum_failures = maximum_failures
        self.window_seconds = window_seconds
        self._failures: dict[str, Deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def _remove_expired(self, client_ip: str, now: float) -> Deque[float]:
        failures = self._failures[client_ip]
        threshold = now - self.window_seconds
        while failures and failures[0] <= threshold:
            failures.popleft()
        return failures

    def is_allowed(self, client_ip: str) -> bool:
        """返回客户端是否仍可尝试登录。"""
        with self._lock:
            return (
                len(self._remove_expired(client_ip, monotonic()))
                < self.maximum_failures
            )

    def record_failure(self, client_ip: str) -> None:
        """记录一次失败登录。"""
        with self._lock:
            self._remove_expired(client_ip, monotonic()).append(monotonic())

    def reset(self, client_ip: str) -> None:
        """登录成功后清除客户端失败记录。"""
        with self._lock:
            self._failures.pop(client_ip, None)


class WebSecurityMiddleware(
    BaseHTTPMiddleware
):  # pylint: disable=too-few-public-methods
    """执行同源访问控制并写入基础安全响应头。"""

    def __init__(
        self,
        app,
        allowed_hosts: set[str],
        allowed_origins: set[str],
    ) -> None:
        super().__init__(app)
        self.allowed_hosts = allowed_hosts
        self.allowed_origins = allowed_origins

    @staticmethod
    def _add_security_headers(request: Request, response: Response) -> Response:
        """为正常与拒绝响应统一增加安全头和缓存策略。"""
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; frame-ancestors 'none'"
        )
        if request.url.path.startswith("/api/") or response.headers.get(
            "content-type", ""
        ).startswith("text/html"):
            response.headers["Cache-Control"] = "no-store"
        elif request.url.path.startswith("/assets/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request.state.request_id = str(uuid4())
        host = request.url.hostname
        if host not in self.allowed_hosts:
            return self._add_security_headers(
                request,
                error_response(
                    request,
                    status.HTTP_400_BAD_REQUEST,
                    "INVALID_HOST",
                    "请求 Host 不受信任",
                ),
            )

        if request.method not in _SAFE_METHODS:
            origin = request.headers.get("origin")
            if origin is not None and origin not in self.allowed_origins:
                return self._add_security_headers(
                    request,
                    error_response(
                        request,
                        status.HTTP_403_FORBIDDEN,
                        "INVALID_ORIGIN",
                        "请求 Origin 不受信任",
                    ),
                )
            if (
                request.url.path.startswith("/api/v1")
                and request.url.path not in _CSRF_EXEMPT_PATHS
            ):
                cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
                header_token = request.headers.get(CSRF_HEADER_NAME)
                if (
                    cookie_token is None
                    or header_token is None
                    or not compare_digest(cookie_token, header_token)
                ):
                    return self._add_security_headers(
                        request,
                        error_response(
                            request,
                            status.HTTP_403_FORBIDDEN,
                            "CSRF_FAILED",
                            "CSRF 校验失败",
                        ),
                    )

        response = await call_next(request)
        return self._add_security_headers(request, response)


def allowed_web_origins(host: str, port: int) -> set[str]:
    """生成当前 WebUI 监听地址允许的同源集合。"""
    hosts = {host, "127.0.0.1", "localhost", "[::1]"}
    return {f"http://{item}:{port}" for item in hosts}
