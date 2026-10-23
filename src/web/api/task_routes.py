"""下载任务查询、创建与取消 API。"""

from dataclasses import asdict
from typing import Annotated, Callable, List, Optional

import threading

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field

from src.logging.logger_config import logger
from src.service.download_service import DOWNLOAD_REQUEST_LIMIT
from src.service.operation_context import OperationContext
from src.service.web_auth_service import AuthenticatedSession
from src.web.api.common import build_operation_context
from src.web.dependencies import WebDependencies
from src.web.errors import ApiError

AuthenticateCallable = Callable[..., AuthenticatedSession]


def _publish_queue_status(dependencies: WebDependencies) -> None:
    """立即推送队列状态，避免前端等待下一次周期采样。"""
    snapshot = dependencies.system_service.get_status()
    dependencies.event_bus.publish(
        "queue.updated",
        {"download": snapshot.download_queue, "send": snapshot.send_queue},
    )


def _enqueue_pending_in_background(
    dependencies: WebDependencies,
    pending_ids: List[str],
    context: OperationContext,
) -> None:
    """后台把预检通过的漫画逐个入队，完成后推送最新队列状态。"""
    try:
        result = dependencies.download_service.enqueue_pending(
            pending_ids, context, None
        )
        logger.info(
            f"后台批量入队完成：入队 {result.queued_count} 个，"
            f"重复 {result.duplicate_count} 个"
        )
    # 后台线程边界必须记录异常，否则用户只会看到任务没有出现
    # pylint: disable-next=broad-exception-caught
    except Exception as error:
        logger.error(f"后台批量入队下载任务失败: {error}")
    finally:
        _publish_queue_status(dependencies)


# 单次下载请求的漫画数量上限，与下载服务保持单一来源（消除两处漂移）
# DownloadRequest.max_length 直接引用 download_service.DOWNLOAD_REQUEST_LIMIT


class DownloadRequest(BaseModel):
    """漫画下载请求。"""

    manga_ids: List[str] = Field(min_length=1, max_length=DOWNLOAD_REQUEST_LIMIT)


class BatchTaskIdsRequest(BaseModel):
    """批量任务操作请求；task_ids 去重保序，上限 100。"""

    task_ids: List[str] = Field(min_length=1, max_length=100)


def create_task_router(
    dependencies: WebDependencies, authenticate: AuthenticateCallable
) -> APIRouter:
    """创建下载任务查询、创建与取消路由。"""
    router = APIRouter(tags=["任务"])

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
            raise ApiError(400, "INVALID_QUERY", str(error)) from error

    @router.get("/tasks/{task_id}")
    def get_task(
        task_id: str,
        _authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> dict[str, object]:
        task = dependencies.task_query_service.get(task_id)
        if task is None:
            raise ApiError(404, "TASK_NOT_FOUND", "未找到指定任务")
        return asdict(task)

    @router.post("/tasks/downloads", status_code=status.HTTP_202_ACCEPTED)
    def create_download_tasks(
        body: DownloadRequest,
        request: Request,
        authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> dict[str, object]:
        """接收批量下载请求，立即返回并在后台逐个入队。

        预检阶段只做一次批量活动任务查询；返回后由后台线程创建任务，
        WebSocket 的 task.updated / queue.updated 会驱动任务列表实时刷新。
        """
        context = build_operation_context(request, authenticated)
        try:
            prepared = dependencies.download_service.prepare(list(body.manga_ids))
        except ValueError as error:
            raise ApiError(400, "INVALID_DOWNLOAD_REQUEST", str(error)) from error
        if prepared.pending_ids:
            threading.Thread(
                target=_enqueue_pending_in_background,
                args=(dependencies, list(prepared.pending_ids), context),
                daemon=True,
                name="download-enqueue",
            ).start()
        return {
            "items": [asdict(item) for item in prepared.items],
            "queued_count": prepared.accepted_count,
            "duplicate_count": prepared.duplicate_count,
            "skipped_blacklisted": list(prepared.skipped_blacklisted),
        }

    @router.post("/tasks/pause")
    def pause_download_queue(
        _request: Request,
        _authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> dict[str, object]:
        """暂停下载队列；幂等，已暂停时 changed 为 False。"""
        changed = dependencies.download_service.pause()
        _publish_queue_status(dependencies)
        return {
            "paused": dependencies.download_service.is_paused(),
            "changed": changed,
        }

    @router.post("/tasks/resume")
    def resume_download_queue(
        _request: Request,
        _authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> dict[str, object]:
        """恢复下载队列；幂等，未暂停时 changed 为 False。"""
        changed = dependencies.download_service.resume()
        _publish_queue_status(dependencies)
        return {
            "paused": dependencies.download_service.is_paused(),
            "changed": changed,
        }

    @router.get("/downloads/progress")
    def get_download_progress(
        _authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> dict[str, object]:
        """返回当前或最近一次下载进度快照，供页面刷新后恢复。"""
        snapshot = dependencies.download_progress_tracker.snapshot()
        return {"active": snapshot.to_dict() if snapshot is not None else None}

    @router.post("/tasks/{task_id}/cancel")
    def cancel_task(
        task_id: str,
        _request: Request,
        _authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> dict[str, object]:
        """取消尚未开始的下载任务。"""
        result = dependencies.download_service.cancel_task(task_id)
        if result.status == "not_found":
            raise ApiError(404, "TASK_NOT_FOUND", "未找到指定任务")
        if result.status == "not_download":
            raise ApiError(409, "TASK_NOT_DOWNLOAD", "只有下载任务可以取消")
        if result.status == "not_queued":
            raise ApiError(409, "TASK_NOT_QUEUED", "任务已开始或已结束，无法取消")
        task = dependencies.task_query_service.get(task_id)
        return {
            "task_id": task_id,
            "cancelled": True,
            "task": asdict(task) if task is not None else None,
        }

    @router.post("/tasks/cancel-queued")
    def cancel_queued_tasks(
        _request: Request,
        _authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> dict[str, int]:
        """取消全部尚未开始的下载任务。"""
        return {"cancelled_count": dependencies.download_service.cancel_queued_tasks()}

    @router.post("/tasks/cancel")
    def cancel_tasks(
        body: BatchTaskIdsRequest,
        _request: Request,
        _authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> dict[str, object]:
        """批量取消排队中的下载任务，逐项返回状态。"""
        result = dependencies.download_service.cancel_tasks(list(body.task_ids))
        return {
            "items": [asdict(item) for item in result.items],
            "cancelled_count": result.succeeded_count,
            "failed_count": result.failed_count,
        }

    @router.post("/tasks/retry", status_code=status.HTTP_202_ACCEPTED)
    def retry_tasks(
        body: BatchTaskIdsRequest,
        request: Request,
        authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> dict[str, object]:
        """批量重试失败/中断的下载任务，复用原任务记录重新入队。"""
        context = build_operation_context(request, authenticated)
        result = dependencies.download_service.retry_tasks(list(body.task_ids), context)
        return {
            "items": [asdict(item) for item in result.items],
            "requeued_count": result.succeeded_count,
            "failed_count": result.failed_count,
        }

    return router
