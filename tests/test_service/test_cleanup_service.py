"""过期数据清理应用服务测试。"""

from datetime import timedelta

from sqlalchemy import update

from src.database.models import AuditEvent, utc_now
from src.database.repositories import AuditEventRepository, OperationTaskRepository
from src.service import CleanupService


def test_cleanup_removes_expired_and_records_audit(db_manager) -> None:
    """cleanup 应清理过期任务与审计，并记录清理审计。"""
    task_repo = OperationTaskRepository(db_manager)
    audit_repo = AuditEventRepository(db_manager)
    service = CleanupService(task_repo, audit_repo)

    old_task = task_repo.create("download", "qq", "10001")
    with db_manager.get_session() as session:
        stored = session.get(type(old_task), old_task.id)
        stored.status = "succeeded"
        stored.finished_at = utc_now() - timedelta(days=200)
        session.commit()
    audit_repo.record(event_type="download.completed", source="qq", result="succeeded")
    with db_manager.get_session() as session:
        session.execute(
            update(AuditEvent).values(created_at=utc_now() - timedelta(days=400))
        )
        session.commit()

    removed = service.cleanup(now=utc_now())

    assert removed == 2
    assert task_repo.get(old_task.id) is None
    remaining_types = {event.event_type for event in audit_repo.list()}
    assert "maintenance.cleanup_completed" in remaining_types
