"""维护操作 API：扫描、修复、数据库备份与数据迁移。"""

from dataclasses import asdict
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Annotated, Callable, List, Optional

import shutil

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from src.service import BackupConflictError, BackupDownloadError, DataImportError
from src.service.web_auth_service import AuthenticatedSession
from src.web.dependencies import WebDependencies
from src.web.errors import ApiError

from .common import build_operation_context

AuthenticateCallable = Callable[..., AuthenticatedSession]


class ScanRequest(BaseModel):
    """扫描参数与命令行脚本保持一致。"""

    dry_run: bool = False
    enrich: bool = False
    read_pages: bool = False
    check_chapters: bool = False


class RepairRequest(BaseModel):
    """修复支持只读差异预览。"""

    dry_run: bool = False


class VerifyRequest(BaseModel):
    """受限的漫画校验请求，不接受客户端文件路径。"""

    manga_ids: Optional[List[Annotated[str, Field(pattern=r"^\d{1,32}$")]]] = Field(
        default=None, min_length=1, max_length=100
    )


def _save_upload(file: UploadFile) -> Path:
    """把上传的 zip 流式写入系统临时文件，避免整包读入内存。"""
    with NamedTemporaryFile(
        prefix="jmbot-data-import-upload-", suffix=".zip", delete=False
    ) as temporary:
        shutil.copyfileobj(file.file, temporary)
        return Path(temporary.name)


def create_maintenance_router(
    dependencies: WebDependencies, authenticate: AuthenticateCallable
) -> APIRouter:
    """创建扫描、修复、备份与数据迁移路由。"""
    router = APIRouter(tags=["维护"])

    @router.post("/maintenance/verify")
    def verify_library(
        body: VerifyRequest,
        request: Request,
        authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> dict[str, object]:
        """复用校验服务及持久化任务；文件 I/O 在工作线程和事务外执行。"""
        manga_ids = (
            list(dict.fromkeys(body.manga_ids)) if body.manga_ids is not None else None
        )
        # 全部校验也检查活动下载与发送，避免绕过指定漫画模式的冲突检查。
        target_ids = (
            manga_ids
            if manga_ids is not None
            else {
                file.manga_id
                for file in dependencies.manga_service.manga_repository.list_verifiable_files()
            }
        )
        for manga_id in target_ids:
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
        body: ScanRequest = ScanRequest(),
    ) -> dict[str, object]:
        """扫描下载目录并同步漫画记录。"""
        context = build_operation_context(request, authenticated)
        try:
            result = dependencies.scan_service.run(
                context,
                dry_run=body.dry_run,
                enrich=body.enrich,
                read_pages=body.read_pages,
                check_chapters=body.check_chapters,
            )
        except FileNotFoundError as error:
            raise ApiError(
                500, "DOWNLOAD_DIRECTORY_MISSING", "下载目录不存在，请检查配置"
            ) from error
        except ValueError as error:
            raise ApiError(400, "INVALID_SCAN_REQUEST", str(error)) from error
        return asdict(result)

    @router.post("/maintenance/repair")
    def repair_library(
        request: Request,
        authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
        body: RepairRequest = RepairRequest(),
    ) -> dict[str, object]:
        """清理数据库孤儿记录；危险操作确认由前端对话框承担。"""
        context = build_operation_context(request, authenticated)
        try:
            if body.dry_run:
                diff = dependencies.repair_service.preview()
                return {"dry_run": True, "cleaned_count": 0, **asdict(diff)}
            cleaned_count = dependencies.repair_service.repair(context)
        except FileNotFoundError as error:
            raise ApiError(
                500, "DOWNLOAD_DIRECTORY_MISSING", "下载目录不存在，请检查配置"
            ) from error
        return {
            "cleaned_count": cleaned_count,
            "dry_run": False,
            "orphan_manga_ids": [],
            "orphan_tag_names": [],
        }

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

    @router.post("/maintenance/data-export")
    def export_data(
        request: Request,
        authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> FileResponse:
        """生成一次性数据导出包并流式下载，下载结束后清理临时目录。"""
        context = build_operation_context(request, authenticated)
        result = dependencies.data_migration_service.export_data(context)
        return FileResponse(
            result.path,
            media_type="application/zip",
            filename=result.filename,
            headers={"X-Content-Type-Options": "nosniff"},
            # 无论下载成功与否，响应结束后删除整个临时导出目录
            background=BackgroundTask(
                shutil.rmtree, result.path.parent, ignore_errors=True
            ),
        )

    @router.post("/maintenance/data-import/validate")
    def validate_data_import(
        file: Annotated[UploadFile, File()],
        _authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> dict[str, object]:
        """上传数据包并返回预览，不替换文件、不写审计。"""
        upload_path = _save_upload(file)
        try:
            preview = dependencies.data_migration_service.validate_import(upload_path)
        except DataImportError as error:
            raise ApiError(
                error.status_code, error.error_code, error.message
            ) from error
        finally:
            upload_path.unlink(missing_ok=True)
        return asdict(preview)

    @router.post("/maintenance/data-import", status_code=status.HTTP_202_ACCEPTED)
    def apply_data_import(
        request: Request,
        background_tasks: BackgroundTasks,
        file: Annotated[UploadFile, File()],
        authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
        confirm: Annotated[bool, Query()] = False,
    ) -> dict[str, bool]:
        """重新校验并替换整库，响应发出后由后台任务触发优雅重启。"""
        if not confirm:
            raise ApiError(
                400, "DATA_IMPORT_CONFIRM_REQUIRED", "导入数据需要确认参数 confirm=1"
            )
        context = build_operation_context(request, authenticated)
        upload_path = _save_upload(file)
        try:
            dependencies.data_migration_service.apply_import(upload_path, context)
        except DataImportError as error:
            raise ApiError(
                error.status_code, error.error_code, error.message
            ) from error
        finally:
            upload_path.unlink(missing_ok=True)
        # 复用系统重启机制：先返回 202，响应发送后再收尾并 execv
        background_tasks.add_task(dependencies.system_service.request_restart, context)
        return {"restart": True}

    return router
