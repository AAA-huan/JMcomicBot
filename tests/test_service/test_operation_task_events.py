"""操作任务状态事件发布测试。"""

from typing import Any, Dict, List, Tuple

from src.database.repositories import (
    AuditEventRepository,
    OperationTaskRepository,
    TaskEventRepository,
)
from src.service import OperationContext, OperationTaskService


class _RecordingPublisher:
    """记录事件的服务发布器替身。"""

    def __init__(self) -> None:
        self.events: List[Tuple[str, Dict[str, Any]]] = []

    def publish(self, event_type: str, data: Dict[str, Any]) -> None:
        self.events.append((event_type, data))


def _build_service(db_manager, publisher: _RecordingPublisher) -> OperationTaskService:
    return OperationTaskService(
        OperationTaskRepository(db_manager),
        TaskEventRepository(db_manager),
        AuditEventRepository(db_manager),
        event_publisher=publisher,
    )


def test_task_lifecycle_publishes_updated_events(db_manager) -> None:
    """创建、开始、进度与完成都应发布 task.updated 事件。"""
    publisher = _RecordingPublisher()
    service = _build_service(db_manager, publisher)

    task = service.create("scan", OperationContext.web("1", "127.0.0.1"))
    service.start(task.id, "scanning")
    service.progress(task.id, "scanning", 50, metadata={"file_count": 1})
    service.succeed(task.id, metadata={"file_count": 1})

    assert [event_type for event_type, _data in publisher.events] == [
        "task.updated",
    ] * 4
    statuses = [data["status"] for _event_type, data in publisher.events]
    assert statuses == ["queued", "running", "running", "succeeded"]
    assert publisher.events[-1][1]["progress"] == 100
    assert publisher.events[-1][1]["id"] == task.id


def test_task_failure_and_cancel_publish_events(db_manager) -> None:
    """失败与取消同样发布状态事件，便于前端即时刷新。"""
    publisher = _RecordingPublisher()
    service = _build_service(db_manager, publisher)

    failed = service.create("download", OperationContext.qq("10001"), manga_id="100")
    service.start(failed.id, "downloading")
    service.fail(failed.id, "download_failed", "RuntimeError")
    cancelled = service.create("download", OperationContext.qq("10001"), manga_id="200")
    service.cancel(cancelled.id)

    statuses = [data["status"] for _event_type, data in publisher.events]
    assert statuses == ["queued", "running", "failed", "queued", "cancelled"]
