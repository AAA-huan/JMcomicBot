"""操作任务状态事件发布测试。"""

from typing import Any, Dict, List, Tuple

import json

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


def test_recover_interrupted_publishes_events_and_returns_downloads(db_manager) -> None:
    """启动中断应逐条记录事件与审计，并只返回下载任务供队列恢复。"""
    publisher = _RecordingPublisher()
    service = _build_service(db_manager, publisher)

    download = service.create(
        "download", OperationContext.web("admin", "127.0.0.1"), manga_id="800"
    )
    service.start(download.id, "downloading")
    scan = service.create("scan", OperationContext.system())
    service.start(scan.id, "scanning")

    interrupted = service.recover_interrupted()

    assert [task.id for task in interrupted] == [download.id]
    assert interrupted[0].status == "interrupted"
    assert [data["status"] for _event_type, data in publisher.events] == [
        "queued",
        "running",
        "queued",
        "running",
        "interrupted",
        "interrupted",
    ]

    task_repo = OperationTaskRepository(db_manager)
    assert task_repo.get(download.id).status == "interrupted"
    assert task_repo.get(scan.id).status == "interrupted"

    event_repo = TaskEventRepository(db_manager)
    download_events = event_repo.list(download.id)
    assert [event.event_type for event in download_events] == [
        "download.requested",
        "download.started",
        "download.interrupted",
    ]
    assert json.loads(download_events[-1].metadata_json) == {
        "previous_status": "running",
        "reason": "startup_recovery",
    }
    assert [event.event_type for event in event_repo.list(scan.id)][-1] == (
        "scan.interrupted"
    )

    audit_types = [
        event.event_type for event in AuditEventRepository(db_manager).list()
    ]
    assert "download.interrupted" in audit_types


def test_requeue_publishes_previous_status_and_reason(db_manager) -> None:
    """重新入队事件应保留原状态与重试原因。"""
    publisher = _RecordingPublisher()
    service = _build_service(db_manager, publisher)
    context = OperationContext.qq("10001")
    task = service.create("download", context, manga_id="900")
    service.start(task.id, "downloading")
    service.fail(task.id, "download_failed", "TimeoutError", context=context)

    service.requeue(task.id, reason="manual_retry")

    event = TaskEventRepository(db_manager).list(task.id)[-1]
    assert event.event_type == "download.requeued"
    assert json.loads(event.metadata_json) == {
        "previous_status": "failed",
        "reason": "manual_retry",
    }
    assert publisher.events[-1][1]["status"] == "queued"


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
