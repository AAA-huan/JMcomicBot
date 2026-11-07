"""自定义漫画文件夹 API。"""

from dataclasses import asdict
from typing import Annotated, Callable, List

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from src.service.folder_service import FOLDER_MEMBER_BATCH_LIMIT, FolderNameConflict
from src.service.web_auth_service import AuthenticatedSession
from src.web.dependencies import WebDependencies
from src.web.errors import ApiError

from .common import build_operation_context

AuthenticateCallable = Callable[..., AuthenticatedSession]

# 文件夹名称长度上限，与数据库字段保持一致
FOLDER_NAME_MAX_LENGTH = 64


class FolderCreateRequest(BaseModel):
    """新建文件夹请求。"""

    name: str = Field(min_length=1, max_length=FOLDER_NAME_MAX_LENGTH)


class FolderPatchRequest(BaseModel):
    """文件夹修改请求，重命名与排序至少提供一个。"""

    name: str | None = Field(
        default=None, min_length=1, max_length=FOLDER_NAME_MAX_LENGTH
    )
    sort_order: int | None = None


class FolderMembersRequest(BaseModel):
    """批量加入/移出请求。"""

    manga_ids: List[str] = Field(min_length=1, max_length=FOLDER_MEMBER_BATCH_LIMIT)


def create_folder_router(
    dependencies: WebDependencies, authenticate: AuthenticateCallable
) -> APIRouter:
    """创建文件夹路由；写操作全部记审计。"""
    router = APIRouter(tags=["文件夹"])
    folder_service = dependencies.folder_service

    @router.get("/folders")
    def list_folders(
        authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> list[dict[str, object]]:
        """列出全部文件夹与成员数。"""
        del authenticated
        return [asdict(item) for item in folder_service.list_folders()]

    @router.post("/folders", status_code=201)
    def create_folder(
        body: FolderCreateRequest,
        request: Request,
        authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> dict[str, object]:
        """新建文件夹；重名返回 409。"""
        context = build_operation_context(request, authenticated)
        try:
            folder = folder_service.create_folder(body.name, context)
        except FolderNameConflict as error:
            raise ApiError(409, "FOLDER_NAME_CONFLICT", str(error)) from error
        except ValueError as error:
            raise ApiError(400, "INVALID_FOLDER_REQUEST", str(error)) from error
        return asdict(folder)

    @router.patch("/folders/{folder_id}")
    def patch_folder(
        folder_id: int,
        body: FolderPatchRequest,
        request: Request,
        authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> dict[str, object]:
        """重命名或调整排序；文件夹不存在返回 404，重名返回 409。"""
        context = build_operation_context(request, authenticated)
        try:
            if body.name is not None:
                folder = folder_service.rename_folder(folder_id, body.name, context)
                if body.sort_order is not None:
                    folder = folder_service.set_folder_order(
                        folder_id, body.sort_order, context
                    )
            elif body.sort_order is not None:
                folder = folder_service.set_folder_order(
                    folder_id, body.sort_order, context
                )
            else:
                raise ApiError(400, "INVALID_FOLDER_REQUEST", "名称与排序至少提供一个")
        except FolderNameConflict as error:
            raise ApiError(409, "FOLDER_NAME_CONFLICT", str(error)) from error
        except LookupError as error:
            raise ApiError(404, "FOLDER_NOT_FOUND", str(error)) from error
        except ValueError as error:
            raise ApiError(400, "INVALID_FOLDER_REQUEST", str(error)) from error
        return asdict(folder)

    @router.delete("/folders/{folder_id}")
    def delete_folder(
        folder_id: int,
        request: Request,
        authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> dict[str, object]:
        """删除文件夹；成员漫画不受影响。"""
        context = build_operation_context(request, authenticated)
        try:
            folder_service.delete_folder(folder_id, context)
        except LookupError as error:
            raise ApiError(404, "FOLDER_NOT_FOUND", str(error)) from error
        return {"folder_id": folder_id, "deleted": True}

    @router.post("/folders/{folder_id}/mangas")
    def add_folder_mangas(
        folder_id: int,
        body: FolderMembersRequest,
        request: Request,
        authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> dict[str, object]:
        """批量加入文件夹；已在夹内的幂等跳过。"""
        context = build_operation_context(request, authenticated)
        try:
            result = folder_service.add_mangas(folder_id, list(body.manga_ids), context)
        except LookupError as error:
            raise ApiError(404, "FOLDER_NOT_FOUND", str(error)) from error
        except ValueError as error:
            raise ApiError(400, "INVALID_FOLDER_MEMBERS_REQUEST", str(error)) from error
        return {"folder_id": folder_id, **result}

    @router.delete("/folders/{folder_id}/mangas")
    def remove_folder_mangas(
        folder_id: int,
        body: FolderMembersRequest,
        request: Request,
        authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> dict[str, object]:
        """批量移出文件夹；不在夹内的幂等忽略。"""
        context = build_operation_context(request, authenticated)
        try:
            result = folder_service.remove_mangas(
                folder_id, list(body.manga_ids), context
            )
        except LookupError as error:
            raise ApiError(404, "FOLDER_NOT_FOUND", str(error)) from error
        except ValueError as error:
            raise ApiError(400, "INVALID_FOLDER_MEMBERS_REQUEST", str(error)) from error
        return {"folder_id": folder_id, **result}

    return router
