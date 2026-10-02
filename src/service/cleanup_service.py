"""过期数据清理应用服务。"""

from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from src.database.models import BackupRecord, utc_now
from src.database.repositories import (
    AuditEventRepository,
    BackupRepository,
    OperationTaskRepository,
)
from src.logging.logger_config import logger

# 备份文件保留策略：保留最近 10 份且总占用不超过 512MB（常量，后续可配置化）
BACKUP_KEEP_COUNT = 10
BACKUP_MAX_TOTAL_BYTES = 512 * 1024 * 1024


class CleanupService:
    """按保留期清理过期任务、审计事件与备份文件，并记录清理审计。"""

    def __init__(
        self,
        task_repo: OperationTaskRepository,
        audit_repo: AuditEventRepository,
        backup_repo: BackupRepository,
        backup_dir: str,
        retention_days: int = 180,
        audit_retention_days: int = 365,
    ) -> None:
        self.task_repo = task_repo
        self.audit_repo = audit_repo
        self.backup_repo = backup_repo
        self.backup_dir = Path(backup_dir).resolve()
        self.retention_days = retention_days
        self.audit_retention_days = audit_retention_days

    def cleanup(self, now: Optional[datetime] = None) -> int:
        """清理过期任务、审计与备份文件，返回清理总数并记录清理审计。"""
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
        removed_backups = self._cleanup_backups()
        removed = removed_tasks + removed_audits + removed_backups
        logger.info(
            f"过期数据清理完成：已清理任务 {removed_tasks} 个、"
            f"审计 {removed_audits} 条、备份文件 {removed_backups} 份"
        )
        self.audit_repo.record(
            event_type="maintenance.cleanup_completed",
            source="system",
            result="succeeded",
            target_type="database",
            metadata={"cleaned_count": removed},
        )
        return removed

    def _cleanup_backups(self) -> int:
        """按数量与空间上限清理最旧的 ready 备份，永远保留最新一份。"""
        records = self.backup_repo.list_ready_oldest_first()
        if len(records) <= 1:
            return 0
        # 永远保留最新一份；其余从最旧开始按数量与空间上限挑出待删除项
        candidates = records[:-1]
        total_bytes = sum(record.file_size_bytes for record in records)
        remaining_count = len(records)
        to_delete: List[BackupRecord] = []
        for record in candidates:
            if (
                remaining_count <= BACKUP_KEEP_COUNT
                and total_bytes <= BACKUP_MAX_TOTAL_BYTES
            ):
                break
            to_delete.append(record)
            remaining_count -= 1
            total_bytes -= record.file_size_bytes
        if not to_delete:
            return 0

        logger.info(
            f"备份保留清理准备：现有 ready 备份 {len(records)} 份、"
            f"共 {sum(record.file_size_bytes for record in records)} 字节，"
            f"待清理 {len(to_delete)} 份"
            f"（{to_delete[0].created_at.isoformat()} 至 "
            f"{to_delete[-1].created_at.isoformat()}）"
        )
        for record in to_delete:
            self._delete_backup_file(record)
            if not self.backup_repo.mark_deleted(record.id):
                raise RuntimeError(f"备份记录不存在，无法标记删除: {record.id}")
        logger.info(f"备份保留清理完成：已标记删除 {len(to_delete)} 份")
        return len(to_delete)

    def _delete_backup_file(self, record: BackupRecord) -> None:
        """删除备份文件；路径必须位于备份目录内。"""
        path = (self.backup_dir / record.relative_path).resolve()
        try:
            path.relative_to(self.backup_dir)
        except ValueError as error:
            raise RuntimeError(
                f"备份记录路径越过备份目录，已停止清理: {record.relative_path}"
            ) from error
        if path.exists():
            path.unlink()
