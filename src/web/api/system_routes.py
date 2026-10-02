"""系统状态、队列读取与系统控制 API。"""

from dataclasses import asdict
from typing import Annotated, Callable

from fastapi import APIRouter, BackgroundTasks, Depends, Request, status

from src.service.web_auth_service import AuthenticatedSession
from src.web.api.common import build_operation_context
from src.web.dependencies import WebDependencies
from src.web.errors import ApiError

AuthenticateCallable = Callable[..., AuthenticatedSession]


def create_system_router(
    dependencies: WebDependencies, authenticate: AuthenticateCallable
) -> APIRouter:
    """创建系统状态、队列与系统控制路由。"""
    router = APIRouter(tags=["系统"])

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

    @router.post("/system/napcat/reconnect")
    def reconnect_napcat(
        request: Request,
        authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> dict[str, bool]:
        """请求 NapCat 重连；断开后由自动重连恢复。"""
        context = build_operation_context(request, authenticated)
        accepted = dependencies.system_service.request_reconnect(context)
        if not accepted:
            raise ApiError(409, "RECONNECT_UNAVAILABLE", "连接正在关闭，无法重连")
        return {"accepted": True}

    @router.post("/system/shutdown", status_code=status.HTTP_202_ACCEPTED)
    def shutdown_bot(
        request: Request,
        background_tasks: BackgroundTasks,
        authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> dict[str, bool]:
        """请求安全关闭；先返回响应，再由后台任务触发关闭。"""
        context = build_operation_context(request, authenticated)
        background_tasks.add_task(dependencies.system_service.request_shutdown, context)
        return {"shutdown": True}

    return router
