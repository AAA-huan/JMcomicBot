"""重要操作审计事件仓储。"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import select

from src.database.models import AuditEvent
from src.database.repositories._base import BaseRepository
from src.database.repositories.operation_task_repository import serialize_metadata

_AUDIT_SOURCES = {"qq", "web", "system"}

# 长期保留的审计事件前缀：删除、权限、配置、安全、迁移类
_LONG_RETENTION_PREFIXES = (
    "manga.deleted",
    "manga.delete_",
    "permission.changed",
    "setting.changed",
    "bot.shutdown_",
    "migrat",
)


def _is_long_retention(event_type: str) -> bool:
    """判断审计事件类型是否应长期保留。"""
    return any(event_type.startswith(prefix) for prefix in _LONG_RETENTION_PREFIXES)


_AUDIT_METADATA_KEYS = {
    "changed_fields",
    "cleaned_count",
    "duration_ms",
    "file_count",
    "new_count",
    "page_count",
    "reason",
    "retry_count",
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
            return event

    def delete_expired(self, now: datetime, retention_days: int) -> int:
        """删除超过保留期的普通审计事件，长期保留类型除外。

        Args:
            now: 当前时间
            retention_days: 保留天数

        Returns:
            int: 删除的审计事件数量
        """
        cutoff = now - timedelta(days=retention_days)
        with self._get_session() as session:
            candidates = session.scalars(
                select(AuditEvent).where(AuditEvent.created_at < cutoff)
            ).all()
            removed = [
                event
                for event in candidates
                if not _is_long_retention(event.event_type)
            ]
            for event in removed:
                session.delete(event)
            session.commit()
            return len(removed)
