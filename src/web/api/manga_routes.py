"""漫画查询、元数据修改与删除 API。"""

from dataclasses import asdict
from typing import Annotated, Callable, List, Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from src.service import MangaDeleteOutcome
from src.service.manga_service import ADMIN_FAVORITE_DELETE_MESSAGE
from src.service.web_auth_service import AuthenticatedSession
from src.web.dependencies import WebDependencies
from src.web.errors import ApiError

from .common import build_operation_context

AuthenticateCallable = Callable[..., AuthenticatedSession]

# 批量删除单次请求上限，避免一个请求内执行过多磁盘操作
BATCH_DELETE_LIMIT = 100


class MangaMetadataPatchRequest(BaseModel):
    """漫画元数据修改请求，只允许白名单字段。"""

    title: Optional[str] = Field(default=None, max_length=255)
    author: Optional[str] = Field(default=None, max_length=255)
    tags: Optional[List[str]] = None


class MangaBatchDeleteRequest(BaseModel):
    """批量删除请求。"""

    manga_ids: List[str] = Field(min_length=1, max_length=BATCH_DELETE_LIMIT)


def _raise_delete_error(outcome: MangaDeleteOutcome) -> None:
    """把单个删除失败结果映射为明确的 HTTP 错误。"""
    if outcome.error_code == "admin_favorite":
        raise ApiError(409, "MANGA_ADMIN_FAVORITE", ADMIN_FAVORITE_DELETE_MESSAGE)
    if outcome.error_code == "file_not_found":
        raise ApiError(404, "MANGA_NOT_FOUND", "未找到指定漫画")
    if outcome.error_code == "download_conflict":
        raise ApiError(409, "MANGA_DOWNLOADING", "漫画正在下载中，无法删除")
    if outcome.error_code == "send_conflict":
        raise ApiError(409, "MANGA_SENDING", "漫画文件正在发送中，无法删除")
    if outcome.error_code == "delete_directory_missing":
        raise ApiError(500, "DOWNLOAD_DIRECTORY_MISSING", "下载目录不存在，请检查配置")
    raise ApiError(500, "DELETE_FAILED", "删除漫画失败")


def create_manga_router(
    dependencies: WebDependencies, authenticate: AuthenticateCallable
) -> APIRouter:
    """创建漫画查询、元数据修改与删除路由。"""
    router = APIRouter(tags=["漫画"])

    @router.get("/mangas")
    def list_mangas(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
        search: Optional[str] = None,
        manga_status: Annotated[Optional[str], Query(alias="status")] = None,
        tag: Optional[str] = None,
        sort: str = "downloaded_at_desc",
        favorite_only: bool = False,
        history_only: bool = False,
    ) -> dict[str, object]:
        try:
            return asdict(
                dependencies.manga_query_service.list(
                    page,
                    page_size,
                    search,
                    manga_status,
                    tag,
                    sort,
                    favorite_only=favorite_only,
                    history_only=history_only,
                    admin_id=authenticated.admin_id,
                )
            )
        except ValueError as error:
            raise ApiError(400, "INVALID_QUERY", str(error)) from error

    @router.get("/mangas/{manga_id}")
    def get_manga(
        manga_id: str,
        authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> dict[str, object]:
        manga = dependencies.manga_query_service.get(manga_id, authenticated.admin_id)
        if manga is None:
            raise ApiError(404, "MANGA_NOT_FOUND", "未找到指定漫画")
        return asdict(manga)

    @router.get("/mangas/{manga_id}/files")
    def list_manga_files(
        manga_id: str,
        authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> list[dict[str, object]]:
        manga = dependencies.manga_query_service.get(manga_id, authenticated.admin_id)
        if manga is None:
            raise ApiError(404, "MANGA_NOT_FOUND", "未找到指定漫画")
        return [asdict(item) for item in manga.files]

    def change_favorite(
        manga_id: str,
        favorite: bool,
        request: Request,
        authenticated: AuthenticatedSession,
    ) -> dict[str, object]:
        """收藏归属只使用服务端认证账户，不接受客户端指定身份。"""
        try:
            changed = dependencies.favorite_service.set_favorite(
                authenticated.admin_id,
                manga_id,
                favorite,
                build_operation_context(request, authenticated),
            )
        except LookupError as error:
            raise ApiError(404, "MANGA_NOT_FOUND", "未找到指定漫画") from error
        return {"manga_id": manga_id, "is_favorite": favorite, "changed": changed}

    @router.put("/mangas/{manga_id}/favorite")
    def add_favorite(
        manga_id: str,
        request: Request,
        authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> dict[str, object]:
        """幂等收藏漫画。"""
        return change_favorite(manga_id, True, request, authenticated)

    @router.delete("/mangas/{manga_id}/favorite")
    def remove_favorite(
        manga_id: str,
        request: Request,
        authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> dict[str, object]:
        """幂等取消收藏。"""
        return change_favorite(manga_id, False, request, authenticated)

    @router.patch("/mangas/{manga_id}")
    def patch_manga(
        manga_id: str,
        body: MangaMetadataPatchRequest,
        request: Request,
        authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> dict[str, object]:
        """按白名单修改标题、作者与标签，并写审计。"""
        context = build_operation_context(request, authenticated)
        fields = {name: getattr(body, name) for name in body.model_fields_set}
        try:
            updated = dependencies.manga_service.patch_metadata(
                manga_id, fields, context
            )
        except ValueError as error:
            raise ApiError(400, "INVALID_MANGA_METADATA", str(error)) from error
        if not updated:
            raise ApiError(404, "MANGA_NOT_FOUND", "未找到指定漫画")
        manga = dependencies.manga_query_service.get(manga_id, authenticated.admin_id)
        if manga is None:
            raise ApiError(404, "MANGA_NOT_FOUND", "未找到指定漫画")
        return asdict(manga)

    @router.delete("/mangas/{manga_id}")
    def delete_manga(
        manga_id: str,
        request: Request,
        authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> dict[str, object]:
        """删除单个漫画；重复删除返回 404，不产生重复副作用。"""
        context = build_operation_context(request, authenticated)
        result = dependencies.manga_service.delete([manga_id], context)
        outcome = result.outcomes[0]
        if not outcome.succeeded:
            _raise_delete_error(outcome)
        return {
            "task_id": result.task_id,
            "manga_id": manga_id,
            "deleted": True,
            "deleted_file_count": outcome.deleted_file_count,
        }

    @router.post("/mangas/batch-delete")
    def batch_delete_mangas(
        body: MangaBatchDeleteRequest,
        request: Request,
        authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> dict[str, object]:
        """批量删除漫画，返回每个对象的结构化结果。"""
        context = build_operation_context(request, authenticated)
        result = dependencies.manga_service.delete(list(body.manga_ids), context)
        return {
            "task_id": result.task_id,
            "items": [
                {
                    "manga_id": outcome.manga_id,
                    "succeeded": outcome.succeeded,
                    "error_code": outcome.error_code,
                    "deleted_file_count": outcome.deleted_file_count,
                    "error_message": (
                        ADMIN_FAVORITE_DELETE_MESSAGE
                        if outcome.error_code == "admin_favorite"
                        else None
                    ),
                }
                for outcome in result.outcomes
            ],
            "succeeded_count": result.succeeded_count,
            "failed_count": result.failed_count,
        }

    return router
