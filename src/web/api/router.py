"""认证 API 与 v1 路由组装。"""

from dataclasses import asdict
from ipaddress import ip_address
from secrets import token_urlsafe
from typing import Annotated, Optional

from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    HTTPException,
    Request,
    Response,
    status,
)
from pydantic import BaseModel, Field

from src.service.web_auth_service import AuthenticatedSession
from src.web.api.common import SESSION_COOKIE_NAME, build_authenticate
from src.web.api.maintenance_routes import create_maintenance_router
from src.web.api.manga_routes import create_manga_router
from src.web.api.permission_routes import create_permission_router
from src.web.api.setting_routes import create_setting_router
from src.web.api.system_routes import create_system_router
from src.web.api.task_routes import create_task_router
from src.web.dependencies import WebDependencies
from src.web.errors import ApiError
from src.web.security import CSRF_COOKIE_NAME, LoginRateLimiter


class PasswordRequest(BaseModel):
    """管理员密码请求。"""

    password: str = Field(min_length=12, max_length=1024)


class PasswordChangeRequest(BaseModel):
    """管理员修改密码请求。"""

    old_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=12, max_length=1024)


def _is_loopback(request: Request) -> bool:
    """严格判断直接连接地址是否为回环地址。"""
    return request.client is not None and ip_address(request.client.host).is_loopback


def create_api_router(  # pylint: disable=too-many-locals
    dependencies: WebDependencies, login_rate_limiter: LoginRateLimiter
) -> APIRouter:
    """创建绑定既有应用服务的 v1 API 路由。"""
    router = APIRouter(prefix="/api/v1")
    auth_service = dependencies.auth_service
    authenticate = build_authenticate(auth_service)

    @router.get("/auth/status")
    def auth_status(
        token: Annotated[Optional[str], Cookie(alias=SESSION_COOKIE_NAME)] = None,
    ) -> dict[str, bool]:
        """返回初始化和当前登录状态。"""
        authenticated = auth_service.authenticate(token) if token else None
        return {
            "initialized": auth_service.is_initialized(),
            "authenticated": authenticated is not None,
        }

    @router.post("/auth/setup", status_code=status.HTTP_201_CREATED)
    def setup(request: Request, body: PasswordRequest) -> dict[str, bool]:
        """仅允许从回环地址首次创建管理员。"""
        if not _is_loopback(request):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "只能从本机初始化管理员")
        try:
            auth_service.setup(body.password)
        except ValueError as error:
            raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
        return {"initialized": True}

    @router.post("/auth/login")
    def login(
        request: Request, body: PasswordRequest, response: Response
    ) -> dict[str, object]:
        """登录并写入 HttpOnly 会话 Cookie。"""
        if request.client is None:
            raise ApiError(400, "CLIENT_ADDRESS_MISSING", "无法识别客户端地址")
        client_ip = request.client.host
        if not login_rate_limiter.is_allowed(client_ip):
            raise ApiError(429, "LOGIN_RATE_LIMITED", "登录尝试过于频繁，请稍后重试")
        try:
            created = auth_service.login(body.password, client_ip)
        except ValueError as error:
            login_rate_limiter.record_failure(client_ip)
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "登录凭据无效") from error
        login_rate_limiter.reset(client_ip)
        csrf_token = token_urlsafe(32)
        response.set_cookie(
            SESSION_COOKIE_NAME,
            created.token,
            max_age=auth_service.session_hours * 3600,
            httponly=True,
            secure=False,
            samesite="strict",
            path="/",
        )
        response.set_cookie(
            CSRF_COOKIE_NAME,
            csrf_token,
            max_age=auth_service.session_hours * 3600,
            httponly=False,
            secure=False,
            samesite="strict",
            path="/",
        )
        return {"authenticated": True, "expires_at": created.expires_at}

    @router.post("/auth/logout")
    def logout(
        response: Response,
        authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
        token: Annotated[str, Cookie(alias=SESSION_COOKIE_NAME)],
    ) -> dict[str, bool]:
        """销毁当前会话并删除 Cookie。"""
        del authenticated
        auth_service.logout(token)
        response.delete_cookie(SESSION_COOKIE_NAME, path="/")
        response.delete_cookie(CSRF_COOKIE_NAME, path="/")
        return {"authenticated": False}

    @router.get("/auth/me")
    def me(
        authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> dict[str, object]:
        """返回当前单管理员公开信息。"""
        admin = auth_service.get_admin_status()
        if admin is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "管理员不存在")
        return {**asdict(admin), "session_expires_at": authenticated.expires_at}

    @router.put("/auth/password")
    def change_password(
        body: PasswordChangeRequest,
        response: Response,
        authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> dict[str, bool]:
        """修改密码并使全部会话失效。"""
        del authenticated
        try:
            auth_service.change_password(body.old_password, body.new_password)
        except ValueError as error:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(error)) from error
        response.delete_cookie(SESSION_COOKIE_NAME, path="/")
        response.delete_cookie(CSRF_COOKIE_NAME, path="/")
        return {"authenticated": False}

    router.include_router(create_system_router(dependencies, authenticate))
    router.include_router(create_manga_router(dependencies, authenticate))
    router.include_router(create_task_router(dependencies, authenticate))
    router.include_router(create_permission_router(dependencies, authenticate))
    router.include_router(create_setting_router(dependencies, authenticate))
    router.include_router(create_maintenance_router(dependencies, authenticate))
    return router
