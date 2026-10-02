"""仓储层统一导出，便于外部以 from src.database.repositories import ... 方式引用"""

from src.database.repositories.audit_event_repository import AuditEventRepository
from src.database.repositories.backup_repository import BackupRepository
from src.database.repositories.manga_repository import MangaRepository
from src.database.repositories.manga_tag_repository import MangaTagRepository
from src.database.repositories.operation_task_repository import (
    OperationTaskRepository,
    TaskEventRepository,
)
from src.database.repositories.permission_repository import PermissionRepository
from src.database.repositories.reading_progress_repository import (
    ReadingProgressRepository,
)
from src.database.repositories.scan_record_repository import ScanRecordRepository
from src.database.repositories.setting_history_repository import (
    SettingHistoryRepository,
)
from src.database.repositories.setting_repository import SettingRepository
from src.database.repositories.task_log_repository import TaskLogRepository
from src.database.repositories.user_group_repository import UserGroupRepository
from src.database.repositories.web_auth_repository import (
    WebAdminRepository,
    WebSessionRepository,
)

__all__ = [
    "AuditEventRepository",
    "BackupRepository",
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
