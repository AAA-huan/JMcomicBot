"""数据库维护应用服务，负责带任务与备份记录的一致性备份。"""

from pathlib import Path
from typing import Optional

import os

from src.database.database import DatabaseManager
from src.database.migrations import backup_database, get_schema_revision
from src.database.models import utc_now
from src.database.repositories import BackupRepository
from src.service.contracts import TaskService
from src.service.operation_context import OperationContext
from src.service.results import BackupResult
from src.utils.file_hash import sha256_of


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

    def create_backup(
        self,
        context: Optional[OperationContext] = None,
    ) -> BackupResult:
        """创建一致性备份并持久化任务、备份记录与审计。

        文件名由服务生成；任一步失败都会把备份记录置 failed 并让任务失败，
        不返回虚假成功。
        """
        operation_context = context or OperationContext.system()
        task = self.operation_task_service.create("backup", operation_context)
        self.operation_task_service.start(task.id, "backing_up")
        try:
            schema_version = get_schema_revision(self.db_manager.engine)
            os.makedirs(self.backup_dir, exist_ok=True)
            filename = f"main-{utc_now():%Y%m%d-%H%M%S}-{schema_version}.db"
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
            return BackupResult(task_id=task.id, path=destination, file_count=1)
        except Exception as error:
            self.operation_task_service.fail(
                task.id,
                "backup_failed",
                type(error).__name__,
                context=operation_context,
            )
            raise
