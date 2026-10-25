"""仅认证管理员可用的 JM 远程搜索与漫画概要 API。"""

from typing import Annotated, Callable, Dict

from fastapi import APIRouter, Depends, Query

from src.service.jm_search_service import JmSearchError
from src.service.web_auth_service import AuthenticatedSession
from src.web.dependencies import WebDependencies
from src.web.errors import ApiError


def create_jm_search_router(
    dependencies: WebDependencies, authenticate: Callable[..., AuthenticatedSession]
) -> APIRouter:
    """远程请求可能较慢，统一要求管理员会话，避免匿名触发站点访问。"""
    router = APIRouter(prefix="/jm", tags=["JM 搜索"])
    service = dependencies.jm_search_service

    @router.get("/search/author")
    def search_author(
        authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
        author: Annotated[str, Query(max_length=255)] = "",
        page: Annotated[int, Query()] = 1,
    ) -> Dict[str, object]:
        """按作者搜索 JM 漫画；空作者和非法页码返回 400。"""
        del authenticated
        try:
            return service.search_author(author, page)
        except JmSearchError as error:
            raise ApiError(error.status, error.code, str(error)) from error

    @router.get("/album/{album_id}")
    def get_album_detail(
        album_id: str,
        authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> Dict[str, object]:
        """读取远程漫画概要，不下载、不入库。"""
        del authenticated
        try:
            return service.get_album_detail(album_id)
        except JmSearchError as error:
            raise ApiError(error.status, error.code, str(error)) from error

    return router
