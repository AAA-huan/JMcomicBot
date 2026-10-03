"""维护操作 API：扫描、修复与数据库备份。"""

from dataclasses import asdict
from typing import Annotated, Callable, List, Optional

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from src.service import BackupConflictError, BackupDownloadError
from src.service.web_auth_service import AuthenticatedSession
from src.web.dependencies import WebDependencies
from src.web.errors import ApiError

from .common import build_operation_context

AuthenticateCallable = Callable[..., AuthenticatedSession]


class VerifyRequest(BaseModel):
    """受限的漫画校验请求，不接受客户端文件路径。"""

    manga_ids: List[Annotated[str, Field(pattern=r"^\d{1,32}$")]] = Field(
        min_length=1, max_length=100
    )


def create_maintenance_router(
    dependencies: WebDependencies, authenticate: AuthenticateCallable
) -> APIRouter:
    """创建扫描、修复与备份路由。"""
    router = APIRouter(tags=["维护"])

    @router.post("/maintenance/verify")
    def verify_library(
        body: VerifyRequest,
        request: Request,
        authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> dict[str, object]:
        """复用校验服务及持久化任务；文件 I/O 在工作线程和事务外执行。"""
        manga_ids = list(dict.fromkeys(body.manga_ids))
        for manga_id in manga_ids:
            if dependencies.manga_service.download_conflict_checker(
                manga_id
            ) or dependencies.manga_service.send_conflict_checker(manga_id):
                raise ApiError(409, "MANGA_BUSY", "漫画正在下载或发送，暂时无法校验")
        context = build_operation_context(request, authenticated)
        try:
            return asdict(dependencies.verify_service.verify(manga_ids, context))
        except ValueError as error:
            raise ApiError(400, "INVALID_VERIFY_REQUEST", str(error)) from error
        except FileNotFoundError as error:
            raise ApiError(
                500, "DOWNLOAD_DIRECTORY_MISSING", "下载目录不存在，请检查配置"
            ) from error

    @router.post("/maintenance/scan")
    def scan_library(
        request: Request,
        authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> dict[str, object]:
        """扫描下载目录并同步漫画记录。"""
        context = build_operation_context(request, authenticated)
        try:
            result = dependencies.scan_service.run(context)
        except FileNotFoundError as error:
            raise ApiError(
                500, "DOWNLOAD_DIRECTORY_MISSING", "下载目录不存在，请检查配置"
            ) from error
        return {
            "task_id": result.task_id,
            "scanned_files": result.scanned_files,
            "manga_count": result.manga_count,
            "new_count": result.new_count,
            "updated_count": result.updated_count,
            "marked_missing_count": result.marked_missing_count,
        }

    @router.post("/maintenance/repair")
    def repair_library(
        request: Request,
        authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> dict[str, object]:
        """清理数据库孤儿记录；危险操作确认由前端对话框承担。"""
        context = build_operation_context(request, authenticated)
        try:
            cleaned_count = dependencies.repair_service.repair(context)
        except FileNotFoundError as error:
            raise ApiError(
                500, "DOWNLOAD_DIRECTORY_MISSING", "下载目录不存在，请检查配置"
            ) from error
        return {"cleaned_count": cleaned_count}

    @router.get("/maintenance/backups")
    def list_backups(
        _authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
        backup_status: Annotated[Optional[str], Query(alias="status")] = None,
    ) -> dict[str, object]:
        """分页查询备份记录，不返回绝对路径。"""
        try:
            page_result = dependencies.database_maintenance_service.list_backups(
                page, page_size, backup_status
            )
        except ValueError as error:
            raise ApiError(400, "INVALID_QUERY", str(error)) from error
        return asdict(page_result)

    @router.get("/maintenance/backups/{backup_id}/download")
    def download_backup(
        backup_id: int,
        _authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> FileResponse:
        """下载已登记的备份文件；路径由数据库记录解析，不接受客户端路径。"""
        try:
            path = dependencies.database_maintenance_service.resolve_backup_file(
                backup_id
            )
        except BackupDownloadError as error:
            status_code = 500 if error.error_code == "BACKUP_PATH_INVALID" else 404
            raise ApiError(status_code, error.error_code, error.message) from error
        return FileResponse(
            path,
            media_type="application/octet-stream",
            filename=path.name,
            headers={"X-Content-Type-Options": "nosniff"},
        )

    @router.post("/maintenance/backups", status_code=status.HTTP_201_CREATED)
    def create_backup(
        request: Request,
        authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> dict[str, object]:
        """创建一致性数据库备份；危险操作确认由前端对话框承担。"""
        context = build_operation_context(request, authenticated)
        try:
            result = dependencies.database_maintenance_service.create_backup(context)
        except BackupConflictError as error:
            raise ApiError(409, "BACKUP_CONFLICT", str(error)) from error
        return {
            "task_id": result.task_id,
            "backup_id": result.backup_id,
            "filename": result.filename,
            "file_size_bytes": result.file_size_bytes,
        }

    return router
