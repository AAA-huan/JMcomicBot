"""重要操作审计事件仓储。"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import delete, func, select

from src.database.models import AuditEvent
from src.database.repositories._base import BaseRepository
from src.database.repositories.operation_task_repository import serialize_metadata
from src.logging.audit_messages import format_audit_message
from src.logging.logger_config import logger

_AUDIT_SOURCES = {"qq", "web", "system"}

# 长期保留的审计事件前缀：删除、权限、配置、安全、迁移类
_LONG_RETENTION_PREFIXES = (
    "manga.deleted",
    "manga.delete_",
    "permission.changed",
    "setting.changed",
    "bot.shutdown_",
    "web.login_",
    "migrat",
)


_AUDIT_METADATA_KEYS = {
    "action",
    "changed_fields",
    "cleaned_count",
    "corrupted_count",
    "duration_ms",
    "failed_count",
    "file_count",
    "missing_count",
    "new_count",
    "page_count",
    "reason",
    "retry_count",
    "scope",
    "updated_count",
}


class AuditEventRepository(BaseRepository):
    """审计事件仓储。"""

    def get(self, event_id: int) -> Optional[AuditEvent]:
        with self._get_session() as session:
            return session.get(AuditEvent, event_id)

    def list(self, page: int = 1, page_size: int = 100) -> List[AuditEvent]:
        with self._get_session() as session:
            statement = (
                select(AuditEvent)
                .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            return list(session.scalars(statement).all())

    def record(
        self,
        event_type: str,
        source: str,
        result: str,
        actor_user_id: Optional[str] = None,
        actor_group_id: Optional[str] = None,
        client_ip: Optional[str] = None,
        target_type: Optional[str] = None,
        target_id: Optional[str] = None,
        error_code: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AuditEvent:
        """记录一条不包含原始请求内容的审计事件。"""
        if source not in _AUDIT_SOURCES:
            raise ValueError(f"不支持的审计来源: {source}")
        event = AuditEvent(
            event_type=event_type,
            source=source,
            actor_user_id=actor_user_id,
            actor_group_id=actor_group_id,
            client_ip=client_ip,
            target_type=target_type,
            target_id=target_id,
            result=result,
            error_code=error_code,
            metadata_json=serialize_metadata(metadata, _AUDIT_METADATA_KEYS),
        )
        with self._get_session() as session:
            session.add(event)
            session.commit()
            session.refresh(event)
        # WebUI 操作在控制台输出一条业务语义日志，便于直观看到完成情况；
        # QQ 与系统来源沿用各自模块的既有日志，避免重复刷屏。
        if source == "web":
            logger.info(
                format_audit_message(
                    event_type=event_type,
                    source=source,
                    result=result,
                    target_type=target_type,
                    target_id=target_id,
                    client_ip=client_ip,
                    error_code=error_code,
                )
            )
        return event

    @staticmethod
    def _expired_condition(now: datetime, retention_days: int):
        """构造超过保留期且不属长期保留类型的过滤条件。"""
        cutoff = now - timedelta(days=retention_days)
        return (
            AuditEvent.created_at < cutoff,
            *(
                ~AuditEvent.event_type.startswith(prefix, autoescape=True)
                for prefix in _LONG_RETENTION_PREFIXES
            ),
        )

    def count_expired(self, now: datetime, retention_days: int) -> int:
        """统计达到保留期且不属长期保留类型的审计事件数量。

        Args:
            now: 当前时间
            retention_days: 保留天数

        Returns:
            int: 待清理的审计事件数量
        """
        with self._get_session() as session:
            return int(
                session.scalar(
                    select(func.count())  # pylint: disable=not-callable
                    .select_from(AuditEvent)
                    .where(*self._expired_condition(now, retention_days))
                )
                or 0
            )

    def delete_expired(
        self, now: datetime, retention_days: int, batch_size: int = 200
    ) -> int:
        """分批删除超过保留期的普通审计事件，长期保留类型除外。

        Args:
            now: 当前时间
            retention_days: 保留天数
            batch_size: 每批删除的审计事件数量，必须大于 0

        Returns:
            int: 删除的审计事件数量
        """
        if batch_size <= 0:
            raise ValueError("清理批次大小必须大于 0")
        removed_total = 0
        while True:
            with self._get_session() as session:
                event_ids = session.scalars(
                    select(AuditEvent.id)
                    .where(*self._expired_condition(now, retention_days))
                    .limit(batch_size)
                ).all()
                if not event_ids:
                    return removed_total
                result = session.execute(
                    delete(AuditEvent).where(AuditEvent.id.in_(event_ids))
                )
                session.commit()
                removed_total += result.rowcount or 0
