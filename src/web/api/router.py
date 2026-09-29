"""认证、系统状态、漫画和任务只读 API。"""

from dataclasses import asdict
from ipaddress import ip_address
from secrets import token_urlsafe
from typing import Annotated, Optional

from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from pydantic import BaseModel, Field

from src.service.web_auth_service import AuthenticatedSession
from src.web.dependencies import WebDependencies
from src.web.errors import ApiError
from src.web.security import CSRF_COOKIE_NAME, LoginRateLimiter

SESSION_COOKIE_NAME = "jmbot_session"


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


def create_api_router(  # pylint: disable=too-many-locals,too-many-statements
    dependencies: WebDependencies, login_rate_limiter: LoginRateLimiter
) -> APIRouter:
    """创建绑定既有应用服务的 v1 API 路由。"""
    router = APIRouter(prefix="/api/v1")
    auth_service = dependencies.auth_service

    def authenticate(
        token: Annotated[Optional[str], Cookie(alias=SESSION_COOKIE_NAME)] = None,
    ) -> AuthenticatedSession:
        if token is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "尚未登录")
        authenticated = auth_service.authenticate(token)
        if authenticated is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "会话无效或已过期")
        return authenticated

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
            created = auth_service.login(body.password)
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

    @router.get("/system/status")
    def system_status(
        _authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> dict[str, object]:
        return asdict(dependencies.system_service.get_status())

    @router.get("/queues/download")
    def download_queue(
        _authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> dict[str, object]:
        return dependencies.system_service.get_status().download_queue

    @router.get("/queues/send")
    def send_queue(
        _authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> dict[str, object]:
        return dependencies.system_service.get_status().send_queue

    @router.get("/mangas")
    def list_mangas(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        _authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
        search: Optional[str] = None,
        manga_status: Annotated[Optional[str], Query(alias="status")] = None,
        tag: Optional[str] = None,
        sort: str = "downloaded_at_desc",
    ) -> dict[str, object]:
        try:
            return asdict(
                dependencies.manga_query_service.list(
                    page, page_size, search, manga_status, tag, sort
                )
            )
        except ValueError as error:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(error)) from error

    @router.get("/mangas/{manga_id}")
    def get_manga(
        manga_id: str,
        _authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> dict[str, object]:
        manga = dependencies.manga_query_service.get(manga_id)
        if manga is None:
            raise ApiError(404, "MANGA_NOT_FOUND", "未找到指定漫画")
        return asdict(manga)

    @router.get("/mangas/{manga_id}/files")
    def list_manga_files(
        manga_id: str,
        _authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> list[dict[str, object]]:
        manga = dependencies.manga_query_service.get(manga_id)
        if manga is None:
            raise ApiError(404, "MANGA_NOT_FOUND", "未找到指定漫画")
        return [asdict(item) for item in manga.files]

    @router.get("/tasks")
    def list_tasks(
        _authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
        task_type: Optional[str] = None,
        task_status: Annotated[Optional[str], Query(alias="status")] = None,
        manga_id: Optional[str] = None,
    ) -> dict[str, object]:
        try:
            return asdict(
                dependencies.task_query_service.list(
                    page, page_size, task_type, task_status, manga_id
                )
            )
        except ValueError as error:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(error)) from error

    @router.get("/tasks/{task_id}")
    def get_task(
        task_id: str,
        _authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> dict[str, object]:
        task = dependencies.task_query_service.get(task_id)
        if task is None:
            raise ApiError(404, "TASK_NOT_FOUND", "未找到指定任务")
        return asdict(task)

    return router
