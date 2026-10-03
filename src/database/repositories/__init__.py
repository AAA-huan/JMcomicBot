"""仓储层统一导出，便于外部以 from src.database.repositories import ... 方式引用"""

from .audit_event_repository import AuditEventRepository
from .backup_repository import BackupRepository
from .favorite_repository import FavoriteRepository
from .manga_repository import MangaRepository
from .manga_tag_repository import MangaTagRepository
from .operation_task_repository import (
    OperationTaskRepository,
    TaskEventRepository,
)
from .permission_repository import PermissionRepository
from .reading_progress_repository import (
    ReadingProgressRepository,
)
from .scan_record_repository import ScanRecordRepository
from .setting_history_repository import (
    SettingHistoryRepository,
)
from .setting_repository import SettingRepository
from .task_log_repository import TaskLogRepository
from .user_group_repository import UserGroupRepository
from .web_auth_repository import (
    WebAdminRepository,
    WebSessionRepository,
)

__all__ = [
    "AuditEventRepository",
    "BackupRepository",
    "FavoriteRepository",
    "MangaRepository",
    "MangaTagRepository",
    "OperationTaskRepository",
    "PermissionRepository",
    "ReadingProgressRepository",
    "ScanRecordRepository",
    "SettingHistoryRepository",
    "SettingRepository",
    "TaskLogRepository",
    "TaskEventRepository",
    "UserGroupRepository",
    "WebAdminRepository",
    "WebSessionRepository",
]
