"""过期数据清理应用服务。"""

from datetime import datetime, timedelta
from typing import Optional

from src.database.models import utc_now
from src.database.repositories import (
    AuditEventRepository,
    OperationTaskRepository,
)
from src.logging.logger_config import logger


class CleanupService:
    """按保留期清理过期任务与审计事件，并记录清理审计。"""

    def __init__(
        self,
        task_repo: OperationTaskRepository,
        audit_repo: AuditEventRepository,
        retention_days: int = 180,
        audit_retention_days: int = 365,
    ) -> None:
        self.task_repo = task_repo
        self.audit_repo = audit_repo
        self.retention_days = retention_days
        self.audit_retention_days = audit_retention_days

    def cleanup(self, now: Optional[datetime] = None) -> int:
        """清理过期任务与审计事件，返回清理总数并记录清理审计。"""
        current = now or utc_now()
        task_cutoff = current - timedelta(days=self.retention_days)
        audit_cutoff = current - timedelta(days=self.audit_retention_days)
        # 清理前记录数量与范围，避免静默删除
        pending_tasks = self.task_repo.count_expired(current, self.retention_days)
        pending_audits = self.audit_repo.count_expired(
            current, self.audit_retention_days
        )
        logger.info(
            f"过期数据清理准备：待清理任务 {pending_tasks} 个"
            f"（完成时间早于 {task_cutoff.isoformat()}），"
            f"待清理审计 {pending_audits} 条（早于 {audit_cutoff.isoformat()}）"
        )
        removed_tasks = self.task_repo.delete_expired(current, self.retention_days)
        removed_audits = self.audit_repo.delete_expired(
            current, self.audit_retention_days
        )
        removed = removed_tasks + removed_audits
        logger.info(
            f"过期数据清理完成：已清理任务 {removed_tasks} 个、审计 {removed_audits} 条"
        )
        self.audit_repo.record(
            event_type="maintenance.cleanup_completed",
            source="system",
            result="succeeded",
            target_type="database",
            metadata={"cleaned_count": removed},
        )
        return removed
