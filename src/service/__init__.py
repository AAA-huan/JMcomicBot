"""应用服务层，协调文件系统、仓储和跨表业务流程。"""

from src.service.cleanup_service import CleanupService
from src.service.contracts import DownloadNotifier, DownloadService, TaskService
from src.service.data_migration_service import DataImportError, DataMigrationService
from src.service.download_service import DownloadQueueService
from src.service.manga_blacklist_service import MangaBlacklistService
from src.service.manga_service import MangaFileDownloadError, MangaService
from src.service.operation_context import OperationContext
from src.service.operation_task_service import OperationTaskService
from src.service.option_file_service import OptionFileService
from src.service.permission_service import (
    CachedGroup,
    CachedUser,
    PermissionService,
)
from src.service.reading_progress_service import (
    ReadingProgressFileNotFoundError,
    ReadingProgressService,
    ReadingProgressView,
)
from src.service.reading_setting_service import ReadingSettingService
from src.service.repair_service import RepairResult, RepairService
from src.service.results import (
    BlacklistBatchResult,
    BlacklistOutcome,
    DataExportResult,
    DownloadCancellationResult,
    DownloadRecoveryResult,
    ImportPreview,
    MangaBlacklistItem,
    MangaDeleteOutcome,
    MangaDeleteResult,
    TaskCancellationResult,
    TaskResult,
    VerifyResult,
)
from src.service.scan_service import ScanRunResult, ScanService
from src.service.settings_service import SettingsService
from src.service.verify_service import VerifyService

__all__ = [
    "BlacklistBatchResult",
    "BlacklistOutcome",
    "CachedGroup",
    "CachedUser",
    "CleanupService",
    "DataExportResult",
    "DataImportError",
    "DataMigrationService",
    "DownloadCancellationResult",
    "DownloadNotifier",
    "DownloadRecoveryResult",
    "DownloadQueueService",
    "ImportPreview",
    "DownloadService",
    "MangaBlacklistItem",
    "MangaBlacklistService",
    "MangaDeleteOutcome",
    "MangaDeleteResult",
    "MangaFileDownloadError",
    "MangaService",
    "OperationContext",
    "OperationTaskService",
    "OptionFileService",
    "PermissionService",
    "ReadingProgressFileNotFoundError",
    "ReadingProgressService",
    "ReadingProgressView",
    "ReadingSettingService",
    "RepairResult",
    "RepairService",
    "ScanRunResult",
    "ScanService",
    "SettingsService",
    "TaskCancellationResult",
    "TaskResult",
    "TaskService",
    "VerifyResult",
    "VerifyService",
]
