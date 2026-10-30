"""仅认证管理员可用的 JM 远程搜索、收藏入库与漫画概要 API。"""

from typing import Annotated, Callable, Dict, List, cast

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from src.service.jm_collect_service import COLLECT_REQUEST_LIMIT, JmCollectError
from src.service.jm_search_service import JmSearchError
from src.service.web_auth_service import AuthenticatedSession
from src.web.dependencies import WebDependencies
from src.web.errors import ApiError


class JmFavoriteAlbumsRequest(BaseModel):
    """批量收藏远程漫画，服务端按首次出现顺序去重。"""

    album_ids: List[str] = Field(min_length=1, max_length=COLLECT_REQUEST_LIMIT)


def create_jm_search_router(
    dependencies: WebDependencies, authenticate: Callable[..., AuthenticatedSession]
) -> APIRouter:
    """远程请求可能较慢，统一要求管理员会话，避免匿名触发站点访问。"""
    router = APIRouter(prefix="/jm", tags=["JM 搜索"])
    service = dependencies.jm_search_service
    collect_service = dependencies.jm_collect_service

    @router.get("/search/author")
    def search_author(
        authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
        author: Annotated[str, Query(max_length=255)] = "",
        page: Annotated[int, Query()] = 1,
    ) -> Dict[str, object]:
        """按作者搜索 JM 漫画；空作者和非法页码返回 400。"""
        del authenticated
        try:
            payload = service.search_author(author, page)
        except JmSearchError as error:
            raise ApiError(error.status, error.code, str(error)) from error
        results = cast(List[Dict[str, object]], payload["results"])
        statuses = collect_service.local_statuses(
            [str(item["album_id"]) for item in results]
        )
        for item in results:
            item["local"] = statuses[str(item["album_id"])]
        return payload

    @router.get("/album/{album_id}")
    def get_album_detail(
        album_id: str,
        authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> Dict[str, object]:
        """读取远程漫画概要，并附带本地存在、收藏与下载状态。"""
        del authenticated
        try:
            payload = service.get_album_detail(album_id)
        except JmSearchError as error:
            raise ApiError(error.status, error.code, str(error)) from error
        payload["local"] = collect_service.local_status(str(payload["album_id"]))
        return payload

    @router.post("/albums/favorite")
    def favorite_albums(
        body: JmFavoriteAlbumsRequest,
        authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> Dict[str, object]:
        """联网读取漫画信息并以收藏态入库，不下载漫画本体。"""
        try:
            return collect_service.collect_albums(
                body.album_ids, authenticated.admin_id
            )
        except JmCollectError as error:
            raise ApiError(error.status, error.code, str(error)) from error

    return router
