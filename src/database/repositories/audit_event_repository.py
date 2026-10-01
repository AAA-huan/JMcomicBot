"""重要操作审计事件仓储。"""

from typing import Any, Dict, List, Optional

from sqlalchemy import select

from src.database.models import AuditEvent
from src.database.repositories._base import BaseRepository
from src.database.repositories.operation_task_repository import serialize_metadata

_AUDIT_SOURCES = {"qq", "web", "system"}
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
