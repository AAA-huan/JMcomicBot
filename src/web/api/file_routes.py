"""漫画 PDF 文件下载与阅读进度 API。"""

from dataclasses import asdict
from typing import Annotated, Callable, Dict, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel

from src.service import (
    MangaFileDownloadError,
    ReadingProgressFileNotFoundError,
)
from src.service.web_auth_service import AuthenticatedSession
from src.web.dependencies import WebDependencies
from src.web.errors import ApiError

AuthenticateCallable = Callable[..., AuthenticatedSession]

# 下载失败原因到 HTTP 状态码的映射；未列出的统一按 404 处理
_ERROR_STATUS_CODES = {
    "FILE_PATH_INVALID": 500,
    "FILE_TYPE_INVALID": 415,
}


class FilePageCountRequest(BaseModel):
    """阅读器加载 PDF 后上报实际总页数。"""

    page_count: int


class ReadingProgressUpdateRequest(BaseModel):
    """阅读进度上报请求；取值范围由服务层校验并返回中文错误。"""

    page_number: int
    page_count: int


def create_file_router(
    dependencies: WebDependencies, authenticate: AuthenticateCallable
) -> APIRouter:
    """创建按资料库记录读取 PDF 与阅读进度的路由。"""
    router = APIRouter(tags=["文件"])

    @router.get("/files/{file_id}/content")
    def download_file_content(
        file_id: int,
        _authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
        disposition: Literal["inline", "attachment"] = "attachment",
    ) -> FileResponse:
        """读取已登记的 PDF；路径由数据库解析，不接受客户端指定。

        disposition=inline 供 PDF.js 在线阅读；范围请求由 FileResponse
        原生处理（206/416），不会把整本 PDF 读入内存。
        """
        try:
            path, display_name = dependencies.manga_service.resolve_file_for_download(
                file_id
            )
        except MangaFileDownloadError as error:
            status_code = _ERROR_STATUS_CODES.get(error.error_code, 404)
            raise ApiError(status_code, error.error_code, error.message) from error
        return FileResponse(
            path,
            media_type="application/pdf",
            filename=display_name,
            content_disposition_type=disposition,
            headers={"X-Content-Type-Options": "nosniff"},
        )

    @router.put("/files/{file_id}/page-count")
    def update_file_page_count(
        file_id: int,
        body: FilePageCountRequest,
        _authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> Dict[str, int]:
        """纠正实际页数，不改动阅读位置或阅读历史。"""
        try:
            dependencies.reading_progress_service.update_page_count(
                file_id, body.page_count
            )
        except ReadingProgressFileNotFoundError as error:
            raise ApiError(404, "FILE_NOT_FOUND", "未找到指定文件") from error
        except ValueError as error:
            raise ApiError(400, "INVALID_PAGE_COUNT", str(error)) from error
        return {"file_id": file_id, "page_count": body.page_count}

    @router.get("/files/{file_id}/progress")
    def get_reading_progress(
        file_id: int,
        _authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> dict[str, object]:
        """查询阅读进度；文件不存在 404，尚无记录返回默认视图。"""
        view = dependencies.reading_progress_service.get_view(file_id)
        if view is None:
            raise ApiError(404, "FILE_NOT_FOUND", "未找到指定文件")
        return asdict(view)

    @router.put("/files/{file_id}/progress")
    def update_reading_progress(
        file_id: int,
        body: ReadingProgressUpdateRequest,
        _authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> dict[str, object]:
        """上报阅读进度；页码校验失败返回 400，不做静默修正。"""
        try:
            dependencies.reading_progress_service.update(
                file_id, body.page_number, body.page_count
            )
        except ReadingProgressFileNotFoundError as error:
            raise ApiError(404, "FILE_NOT_FOUND", "未找到指定文件") from error
        except ValueError as error:
            raise ApiError(400, "INVALID_PROGRESS", str(error)) from error
        view = dependencies.reading_progress_service.get_view(file_id)
        if view is None:
            # 仅当文件在写入后被并发删除时发生；明确返回 404 而不是虚假成功
            raise ApiError(404, "FILE_NOT_FOUND", "未找到指定文件")
        return asdict(view)

    return router
