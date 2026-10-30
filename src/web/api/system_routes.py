"""系统状态、队列读取与系统控制 API。"""

from dataclasses import asdict
from typing import Annotated, Callable, Dict, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Request, status
from pydantic import BaseModel

from src.service.web_auth_service import AuthenticatedSession
from src.web.api.common import build_operation_context
from src.web.dependencies import WebDependencies
from src.web.errors import ApiError

AuthenticateCallable = Callable[..., AuthenticatedSession]


class RecoveryDecisionRequest(BaseModel):
    """恢复询问只接受继续或取消两种动作。"""

    action: Literal["continue", "cancel"]


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

    @router.get("/system/recovery")
    def recovery_status(
        _authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> Dict[str, object]:
        """返回启动恢复询问状态；没有待恢复任务时 pending 为 false。"""
        prompt = dependencies.recovery_prompt_provider()
        if prompt is None:
            return {
                "pending": False,
                "task_count": 0,
                "remaining_seconds": 0,
                "decision": None,
            }
        return {
            "pending": prompt.is_pending(),
            "task_count": prompt.task_count,
            "remaining_seconds": prompt.remaining_seconds(),
            "decision": prompt.decision,
        }

    @router.post("/system/recovery")
    def resolve_recovery(
        body: RecoveryDecisionRequest,
        _authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> Dict[str, bool]:
        """终端或 WebUI 任一渠道先给出的决定生效，重复提交返回冲突。"""
        prompt = dependencies.recovery_prompt_provider()
        if prompt is None or not prompt.is_pending():
            raise ApiError(409, "RECOVERY_NOT_PENDING", "当前没有待处理的恢复询问")
        return {"resolved": prompt.resolve(body.action)}

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

    @router.post("/system/restart", status_code=status.HTTP_202_ACCEPTED)
    def restart_bot(
        request: Request,
        background_tasks: BackgroundTasks,
        authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> dict[str, bool]:
        """请求优雅重启；复用安全关闭收尾路径，close 后由 main 拉起新进程。"""
        context = build_operation_context(request, authenticated)
        background_tasks.add_task(dependencies.system_service.request_restart, context)
        return {"restart": True}

    return router
