"""漫画 PDF 文件下载 API。"""

from typing import Annotated, Callable

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from src.service import MangaFileDownloadError
from src.service.web_auth_service import AuthenticatedSession
from src.web.dependencies import WebDependencies
from src.web.errors import ApiError

AuthenticateCallable = Callable[..., AuthenticatedSession]

# 下载失败原因到 HTTP 状态码的映射；未列出的统一按 404 处理
_ERROR_STATUS_CODES = {
    "FILE_PATH_INVALID": 500,
    "FILE_TYPE_INVALID": 415,
}


def create_file_router(
    dependencies: WebDependencies, authenticate: AuthenticateCallable
) -> APIRouter:
    """创建按资料库记录下载 PDF 的路由。"""
    router = APIRouter(tags=["文件"])

    @router.get("/files/{file_id}/content")
    def download_file_content(
        file_id: int,
        _authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> FileResponse:
        """下载已登记的 PDF；路径由数据库解析，不接受客户端指定。"""
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
            content_disposition_type="attachment",
            headers={"X-Content-Type-Options": "nosniff"},
        )

    return router
