"""数据库维护应用服务，负责带任务与备份记录的一致性备份。"""

from dataclasses import dataclass
from datetime import datetime
from math import ceil
from pathlib import Path
from threading import Lock
from typing import Optional

import os

from src.database.database import DatabaseManager
from src.database.migrations import backup_database, get_schema_revision
from src.database.models import utc_now
from src.database.repositories import BackupRepository
from src.service.contracts import TaskService
from src.service.operation_context import OperationContext
from src.service.query_service import PageResult
from src.service.results import BackupResult
from src.utils.file_hash import sha256_of


class BackupConflictError(Exception):
    """同一秒内已存在同名备份时抛出，供接口层返回冲突。"""


class BackupDownloadError(Exception):
    """备份不可下载时抛出；error_code 供接口层映射为稳定错误码。"""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message


@dataclass(frozen=True)
class BackupView:  # pylint: disable=too-many-instance-attributes
    """可安全返回浏览器的备份记录视图，不包含绝对路径。"""

    id: int
    filename: str
    file_size_bytes: int
    sha256: Optional[str]
    schema_version: str
    status: str
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime]


class DatabaseMaintenanceService:
    """执行带任务记录和备份登记的一致性数据库备份。"""

    def __init__(
        self,
        db_manager: DatabaseManager,
        operation_task_service: TaskService,
        backup_repo: BackupRepository,
        backup_dir: str,
    ) -> None:
        self.db_manager = db_manager
        self.operation_task_service = operation_task_service
        self.backup_repo = backup_repo
        self.backup_dir = Path(backup_dir).resolve()
        # 串行化备份创建，避免同一秒并发提交触发相对路径唯一约束
        self._backup_lock = Lock()

    def create_backup(
        self,
        context: Optional[OperationContext] = None,
    ) -> BackupResult:
        """创建一致性备份并持久化任务、备份记录与审计。

        文件名由服务生成；同一秒重复提交返回 BackupConflictError，不产生
        半完成记录。任一步失败都会把备份记录置 failed 并让任务失败，
        不返回虚假成功。
        """
        operation_context = context or OperationContext.system()
        with self._backup_lock:
            schema_version = get_schema_revision(self.db_manager.engine)
            os.makedirs(self.backup_dir, exist_ok=True)
            filename = f"main-{utc_now():%Y%m%d-%H%M%S}-{schema_version}.db"
            if (
                self.backup_repo.exists_relative_path(filename)
                or (self.backup_dir / filename).exists()
            ):
                raise BackupConflictError("同一秒的备份已存在，请稍后重试")

            task = self.operation_task_service.create("backup", operation_context)
            self.operation_task_service.start(task.id, "backing_up")
            try:
                record = self.backup_repo.create(
                    filename=filename,
                    relative_path=filename,
                    schema_version=schema_version,
                )
                destination = self.backup_dir / filename
                try:
                    backup_database(self.db_manager.engine, str(destination))
                    file_size_bytes = destination.stat().st_size
                    sha256 = sha256_of(destination)
                except Exception:
                    self.backup_repo.mark_failed(record.id)
                    raise
                self.backup_repo.mark_ready(
                    record.id, file_size_bytes=file_size_bytes, sha256=sha256
                )
                self.operation_task_service.succeed(
                    task.id, metadata={"file_count": 1}, context=operation_context
                )
                return BackupResult(
                    task_id=task.id,
                    path=destination,
                    file_count=1,
                    backup_id=record.id,
                    filename=filename,
                    file_size_bytes=file_size_bytes,
                )
            except Exception as error:
                self.operation_task_service.fail(
                    task.id,
                    "backup_failed",
                    type(error).__name__,
                    context=operation_context,
                )
                raise

    def list_backups(
        self, page: int = 1, page_size: int = 50, status: Optional[str] = None
    ) -> PageResult[BackupView]:
        """分页查询备份记录视图，不暴露绝对路径。"""
        if page < 1 or page_size < 1:
            raise ValueError("页码与每页数量必须大于 0")
        records = self.backup_repo.list(page, page_size, status)
        total = self.backup_repo.count(status)
        return PageResult(
            items=tuple(self._to_view(record) for record in records),
            page=page,
            page_size=page_size,
            total=total,
            pages=ceil(total / page_size),
        )

    @staticmethod
    def _to_view(record) -> BackupView:
        return BackupView(
            id=record.id,
            filename=record.filename,
            file_size_bytes=record.file_size_bytes,
            sha256=record.sha256,
            schema_version=record.schema_version,
            status=record.status,
            created_at=record.created_at,
            updated_at=record.updated_at,
            deleted_at=record.deleted_at,
        )

    def resolve_backup_file(self, backup_id: int) -> Path:
        """解析可下载的备份文件路径。

        只接受数据库中的备份记录：路径必须解析后仍位于备份目录内且是
        普通文件，符号链接逃逸、目录与未登记文件一律拒绝。

        Raises:
            BackupDownloadError: 记录不存在、状态不可下载、文件缺失或路径越界。
        """
        record = self.backup_repo.get(backup_id)
        if record is None or record.status != "ready":
            raise BackupDownloadError("BACKUP_NOT_FOUND", "未找到指定备份")
        candidate = (self.backup_dir / record.relative_path).resolve()
        if not candidate.is_relative_to(self.backup_dir):
            raise BackupDownloadError("BACKUP_PATH_INVALID", "备份文件路径非法")
        if not candidate.is_file():
            raise BackupDownloadError("BACKUP_FILE_MISSING", "备份文件不存在")
        return candidate
