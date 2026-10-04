"""仅认证管理员可用的 JM 账号与收藏导入 API。"""

from dataclasses import asdict
from typing import Annotated, Callable, Dict, List

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field, SecretStr

from src.database.repositories.jm_favorite_repository import import_view
from src.service.jm_favorite_service import JmFavoriteError
from src.service.web_auth_service import AuthenticatedSession
from src.web.dependencies import WebDependencies
from src.web.errors import ApiError

from .common import build_operation_context
from .task_routes import DownloadRequest


class JmLoginRequest(BaseModel):
    """秘密字段不会出现在模型的字符串表示中。"""

    username: str = Field(min_length=1, max_length=128)
    password: SecretStr = Field(min_length=1, max_length=1024)


class JmImportRequest(BaseModel):
    """显式选择收藏夹，重复编号在服务端去重。"""

    folder_ids: List[str] = Field(min_length=1, max_length=100)


def create_jm_favorite_router(
    dependencies: WebDependencies, authenticate: Callable[..., AuthenticatedSession]
) -> APIRouter:
    """会话身份来自 Cookie，禁止由请求参数指定管理员归属。"""
    router = APIRouter(prefix="/jm-favorites", tags=["JM 收藏导入"])
    service = dependencies.jm_favorite_service

    @router.get("/account")
    def account(
        authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> Dict[str, object]:
        return service.account_status(authenticated)

    @router.post("/account/login")
    def login(
        body: JmLoginRequest,
        authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> Dict[str, object]:
        try:
            return service.login(
                authenticated, body.username, body.password.get_secret_value()
            )
        except JmFavoriteError as error:
            raise ApiError(error.status, error.code, str(error)) from error

    @router.post("/account/logout")
    def logout(
        authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> Dict[str, bool]:
        service.logout(authenticated.session_id)
        return {"connected": False}

    @router.post("/imports", status_code=202)
    def start_import(
        body: JmImportRequest,
        authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> Dict[str, object]:
        try:
            return service.start_import(authenticated, body.folder_ids)
        except JmFavoriteError as error:
            raise ApiError(error.status, error.code, str(error)) from error

    @router.get("/imports")
    def list_imports(
        authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> Dict[str, object]:
        return {
            "items": [
                import_view(job)
                for job in service.repository.list(authenticated.admin_id)
            ]
        }

    @router.get("/imports/{job_id}")
    def get_import(
        job_id: str,
        authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> Dict[str, object]:
        job = service.repository.get(authenticated.admin_id, job_id)
        if job is None:
            raise ApiError(404, "JM_IMPORT_NOT_FOUND", "导入任务不存在")
        return import_view(job)

    @router.get("")
    def list_favorites(
        authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
        search: Annotated[str, Query(max_length=255)] = "",
        username: Annotated[str, Query(max_length=128)] = "",
        folder_id: Annotated[str, Query(pattern=r"^([0-9]{1,32})?$")] = "",
        download_status: Annotated[
            str, Query(pattern=r"^(downloaded|not_downloaded)?$")
        ] = "",
    ) -> Dict[str, object]:
        return service.repository.list_favorites(
            authenticated.admin_id,
            page,
            page_size,
            search.strip(),
            username,
            folder_id,
            download_status,
        )

    @router.post("/downloads", status_code=202)
    def download_favorites(
        body: DownloadRequest,
        request: Request,
        authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> Dict[str, object]:
        manga_ids = list(dict.fromkeys(body.manga_ids))
        if any(
            not manga_id.isascii() or not manga_id.isdecimal() or len(manga_id) > 32
            for manga_id in manga_ids
        ):
            raise ApiError(
                400, "INVALID_DOWNLOAD_REQUEST", "漫画编号必须为数字且不超过 32 位"
            )
        try:
            service.repository.prepare_download(authenticated.admin_id, manga_ids)
            result = dependencies.download_service.request(
                manga_ids, build_operation_context(request, authenticated), None
            )
        except LookupError as error:
            raise ApiError(404, "JM_FAVORITE_NOT_FOUND", str(error)) from error
        except ValueError as error:
            raise ApiError(400, "INVALID_DOWNLOAD_REQUEST", str(error)) from error
        return {
            "items": [asdict(item) for item in result.items],
            "queued_count": result.queued_count,
            "duplicate_count": result.duplicate_count,
        }

    return router
