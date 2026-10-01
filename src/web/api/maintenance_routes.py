"""维护操作 API：扫描、修复与数据库备份。"""

from dataclasses import asdict
from typing import Annotated, Callable, Optional

from fastapi import APIRouter, Depends, Query, Request, status

from src.service import BackupConflictError
from src.service.web_auth_service import AuthenticatedSession
from src.web.api.common import build_operation_context
from src.web.dependencies import WebDependencies
from src.web.errors import ApiError

AuthenticateCallable = Callable[..., AuthenticatedSession]


def create_maintenance_router(
    dependencies: WebDependencies, authenticate: AuthenticateCallable
) -> APIRouter:
    """创建扫描、修复与备份路由。"""
    router = APIRouter(tags=["维护"])

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
