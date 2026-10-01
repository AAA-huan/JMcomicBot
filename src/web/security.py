"""WebUI Host、Origin、CSRF、安全响应头和登录限速。"""

from collections import defaultdict, deque
from secrets import compare_digest
from threading import Lock
from time import monotonic
from typing import Deque
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import Request, status
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from src.web.errors import error_response

CSRF_COOKIE_NAME = "jmbot_csrf"
CSRF_HEADER_NAME = "X-CSRF-Token"
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_CSRF_EXEMPT_PATHS = {"/api/v1/auth/setup", "/api/v1/auth/login"}


def allows_any_host(host: str) -> bool:
    """监听所有网卡（0.0.0.0/::）时返回 True，用于放宽 Host 校验。"""
    return host in {"0.0.0.0", "::"}


def origin_is_trusted(
    origin: str,
    host_header: str | None,
    allowed_origins: set[str],
    allow_any_host: bool,
) -> bool:
    """校验请求来源是否可信。

    静态白名单始终有效；局域网模式下额外允许与请求 Host 完全一致的同源
    来源，既支持手机/其它设备访问，又拒绝其它站点的跨站请求。
    """
    if origin in allowed_origins:
        return True
    if not allow_any_host or not host_header:
        return False
    parsed = urlparse(origin)
    return bool(parsed.netloc) and parsed.netloc == host_header


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
        allow_any_host: bool = False,
    ) -> None:
        super().__init__(app)
        self.allowed_hosts = allowed_hosts
        self.allowed_origins = allowed_origins
        # 绑定所有网卡时放行任意 Host；来源仍要求同源或命中白名单
        self.allow_any_host = allow_any_host

    @staticmethod
    def _add_security_headers(request: Request, response: Response) -> Response:
        """为正常与拒绝响应统一增加安全头和缓存策略。"""
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "frame-ancestors 'none'"
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
        if not self.allow_any_host and host not in self.allowed_hosts:
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
            if origin is not None and not origin_is_trusted(
                origin,
                request.headers.get("host"),
                self.allowed_origins,
                self.allow_any_host,
            ):
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


def allowed_web_origins(
    host: str, port: int, extra_origins: set[str] | None = None
) -> set[str]:
    """生成当前 WebUI 监听地址与方法允许的同源集合。"""
    hosts = {host, "127.0.0.1", "localhost", "[::1]"}
    origins = {f"http://{item}:{port}" for item in hosts}
    if extra_origins:
        origins |= set(extra_origins)
    return origins
