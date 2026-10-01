"""应用服务层，协调文件系统、仓储和跨表业务流程。"""

from src.service.cleanup_service import CleanupService
from src.service.contracts import DownloadNotifier, DownloadService, TaskService
from src.service.database_maintenance_service import DatabaseMaintenanceService
from src.service.download_service import DownloadQueueService
from src.service.manga_service import MangaService
from src.service.operation_context import OperationContext
from src.service.operation_task_service import OperationTaskService
from src.service.permission_service import PermissionService
from src.service.reading_progress_service import ReadingProgressService
from src.service.repair_service import RepairService
from src.service.results import (
    BackupResult,
    DownloadCancellationResult,
    MangaDeleteOutcome,
    MangaDeleteResult,
    TaskResult,
    VerifyResult,
)
from src.service.settings_service import SettingsService
from src.service.verify_service import VerifyService

__all__ = [
    "BackupResult",
    "CleanupService",
    "DatabaseMaintenanceService",
    "DownloadCancellationResult",
    "DownloadNotifier",
    "DownloadQueueService",
    "DownloadService",
    "MangaDeleteOutcome",
    "MangaDeleteResult",
    "MangaService",
    "OperationContext",
    "OperationTaskService",
    "PermissionService",
    "ReadingProgressService",
    "RepairService",
    "SettingsService",
    "TaskResult",
    "TaskService",
    "VerifyResult",
    "VerifyService",
]
