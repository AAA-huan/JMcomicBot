"""仓储层统一导出，便于外部以 from src.database.repositories import ... 方式引用"""

from src.database.repositories.audit_event_repository import AuditEventRepository
from src.database.repositories.manga_repository import MangaRepository
from src.database.repositories.manga_tag_repository import MangaTagRepository
from src.database.repositories.operation_task_repository import (
    OperationTaskRepository,
    TaskEventRepository,
)
from src.database.repositories.permission_repository import PermissionRepository
from src.database.repositories.setting_repository import SettingRepository
from src.database.repositories.task_log_repository import TaskLogRepository
from src.database.repositories.user_group_repository import UserGroupRepository

__all__ = [
    "AuditEventRepository",
    "MangaRepository",
    "MangaTagRepository",
    "OperationTaskRepository",
    "PermissionRepository",
    "SettingRepository",
    "TaskLogRepository",
    "TaskEventRepository",
    "UserGroupRepository",
]
