"""数据库维护应用服务。"""

from pathlib import Path

from src.database.database import DatabaseManager
from src.database.migrations import backup_database
from src.service.operation_context import OperationContext
from src.service.operation_task_service import OperationTaskService


class DatabaseMaintenanceService:
    """执行带任务记录的一致性数据库备份。"""

    def __init__(
        self,
        db_manager: DatabaseManager,
        operation_task_service: OperationTaskService,
    ) -> None:
        self.db_manager = db_manager
        self.operation_task_service = operation_task_service

    def create_backup(
        self,
        destination: str,
        context: OperationContext | None = None,
    ) -> Path:
        """创建一致性备份，并持久化任务状态、事件和审计。"""
        operation_context = context or OperationContext.system()
        task = self.operation_task_service.create("backup", operation_context)
        self.operation_task_service.start(task.id, "backing_up")
        backup_path = Path(destination).resolve()
        try:
            backup_database(self.db_manager.engine, str(backup_path))
            self.operation_task_service.succeed(
                task.id, metadata={"file_count": 1}, context=operation_context
            )
            return backup_path
        except Exception as error:
            self.operation_task_service.fail(
                task.id,
                "backup_failed",
                type(error).__name__,
                context=operation_context,
            )
            raise
