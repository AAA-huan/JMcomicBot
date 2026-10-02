"""下载任务查询、创建与取消 API。"""

from dataclasses import asdict
from typing import Annotated, Callable, List, Optional

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field

from src.service.web_auth_service import AuthenticatedSession
from src.web.api.common import build_operation_context
from src.web.dependencies import WebDependencies
from src.web.errors import ApiError

AuthenticateCallable = Callable[..., AuthenticatedSession]

# 单次下载请求的漫画数量上限，与下载服务保持一致
DOWNLOAD_REQUEST_LIMIT = 20


class DownloadRequest(BaseModel):
    """漫画下载请求。"""

    manga_ids: List[str] = Field(min_length=1, max_length=DOWNLOAD_REQUEST_LIMIT)


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
        """请求下载单个或多个漫画；重复请求返回既有任务而不是重复建立。"""
        context = build_operation_context(request, authenticated)
        try:
            result = dependencies.download_service.request(
                list(body.manga_ids), context, None
            )
        except ValueError as error:
            raise ApiError(400, "INVALID_DOWNLOAD_REQUEST", str(error)) from error
        return {
            "items": [asdict(item) for item in result.items],
            "queued_count": result.queued_count,
            "duplicate_count": result.duplicate_count,
        }

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

    return router
