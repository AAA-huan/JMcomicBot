"""下载管理器启动恢复（重启续传）逻辑测试。"""

from unittest.mock import Mock

import pytest

from src.database.repositories import (
    AuditEventRepository,
    OperationTaskRepository,
    TaskEventRepository,
)
from src.download.manager import DownloadManager, DownloadQueueItem
from src.service import (
    DownloadQueueService,
    OperationContext,
    OperationTaskService,
)
from src.service.results import DownloadRecoveryResult


@pytest.fixture()
def operation_task_service(db_manager) -> OperationTaskService:
    """基于临时数据库构造操作任务服务。"""
    return OperationTaskService(
        OperationTaskRepository(db_manager),
        TaskEventRepository(db_manager),
        AuditEventRepository(db_manager),
    )


@pytest.fixture()
def manager(
    db_manager, operation_task_service, monkeypatch, tmp_path
) -> DownloadManager:
    """构造不启动队列线程的下载管理器，便于断言内存队列。"""
    del db_manager
    monkeypatch.setattr(
        DownloadManager, "_start_download_queue_processor", lambda self: None
    )
    return DownloadManager(
        logger_instance=Mock(),
        config={
            "MANGA_DOWNLOAD_PATH": str(tmp_path / "downloads"),
            "LOW_MEMORY_MODE": False,
            "LOW_MEMORY_DELETE_DELAY": 3,
        },
        message_sender=Mock(),
        operation_task_service=operation_task_service,
    )


def _recover_startup(
    task_service: OperationTaskService, download_manager: DownloadManager
) -> DownloadRecoveryResult:
    """按 bot 启动顺序模拟：读取遗留任务 → 标记中断 → 重新入队。"""
    legacy_tasks = task_service.list_active_downloads()
    interrupted_tasks = task_service.recover_interrupted()
    interrupted_by_id = {task.id: task for task in interrupted_tasks}
    recovery_tasks = [interrupted_by_id.get(task.id, task) for task in legacy_tasks]
    return download_manager.recover_tasks(recovery_tasks)


def _set_status(db_manager, task, status: str) -> None:
    """测试辅助：直接改写任务状态，模拟上次进程遗留数据。"""
    with db_manager.get_session() as session:
        stored = session.get(type(task), task.id)
        stored.status = status
        session.commit()


def test_startup_recovers_queued_and_interrupted_downloads(
    db_manager, operation_task_service, manager
) -> None:
    """排队任务直接入队，运行中任务中断后复用原记录续传。"""
    repo = OperationTaskRepository(db_manager)
    context = OperationContext.web("admin", "127.0.0.1")
    queued = operation_task_service.create("download", context, manga_id="100")
    running = operation_task_service.create("download", context, manga_id="200")
    operation_task_service.start(running.id, "downloading")
    scan = operation_task_service.create("scan", OperationContext.system())
    operation_task_service.start(scan.id, "scanning")
    missing = repo.create("download", "system")
    _set_status(db_manager, missing, "running")
    blank = operation_task_service.create("download", context, manga_id="")

    result = _recover_startup(operation_task_service, manager)

    assert result == DownloadRecoveryResult(
        recovered_count=2,
        resumed_count=1,
        skipped_count=2,
    )
    assert set(manager.queued_tasks) == {"100", "200"}
    assert manager.operation_task_ids == {"100": queued.id, "200": running.id}
    assert manager.download_queue.qsize() == 2

    assert repo.get(queued.id).status == "queued"
    assert repo.get(running.id).status == "queued"
    assert repo.get(running.id).attempt_count == 1
    assert repo.get(missing.id).status == "interrupted"
    assert repo.get(scan.id).status == "interrupted"
    assert repo.get(blank.id).status == "queued"
    # 复用原任务记录，不产生重复行
    assert len(repo.list()) == 5

    event_repo = TaskEventRepository(db_manager)
    assert [event.event_type for event in event_repo.list(running.id)] == [
        "download.requested",
        "download.started",
        "download.interrupted",
        "download.requeued",
    ]
    assert [event.event_type for event in event_repo.list(queued.id)] == [
        "download.requested"
    ]
    audit_types = [
        event.event_type for event in AuditEventRepository(db_manager).list()
    ]
    assert "download.interrupted" in audit_types
    assert manager.logger.warning.call_count >= 2


def test_recovered_task_attempt_count_increments_on_next_start(
    db_manager, operation_task_service, manager
) -> None:
    """续传任务再次启动时 attempt_count 递增。"""
    repo = OperationTaskRepository(db_manager)
    task = operation_task_service.create(
        "download", OperationContext.qq("10001"), manga_id="210"
    )
    operation_task_service.start(task.id, "downloading")

    _recover_startup(operation_task_service, manager)
    operation_task_service.start(task.id, "downloading")

    stored = repo.get(task.id)
    assert stored.status == "running"
    assert stored.attempt_count == 2


def test_cancel_all_queued_also_cancels_recovered_tasks(
    db_manager, operation_task_service, manager
) -> None:
    """恢复进内存队列的任务仍可被“取消全部排队”取消。"""
    repo = OperationTaskRepository(db_manager)
    context = OperationContext.qq("10001")
    queued = operation_task_service.create("download", context, manga_id="300")
    running = operation_task_service.create("download", context, manga_id="301")
    operation_task_service.start(running.id, "downloading")

    _recover_startup(operation_task_service, manager)
    cancelled_count = DownloadQueueService(
        manager, operation_task_service
    ).cancel_queued_tasks()

    assert cancelled_count == 2
    assert manager.queued_tasks == {}
    assert repo.get(queued.id).status == "cancelled"
    assert repo.get(running.id).status == "cancelled"


def test_recover_skips_same_manga_conflict_without_duplicate_queue(
    db_manager, operation_task_service, manager
) -> None:
    """同漫画已有排队记录时，旧中断记录跳过且不重复入队。"""
    repo = OperationTaskRepository(db_manager)
    older = repo.create("download", "qq", "10001", manga_id="600")
    _set_status(db_manager, older, "running")
    newer = repo.create("download", "qq", "10001", manga_id="600")

    result = _recover_startup(operation_task_service, manager)

    assert result.recovered_count == 1
    assert result.resumed_count == 0
    assert result.skipped_count == 1
    assert manager.queued_tasks["600"].operation_task_id == newer.id
    assert repo.get(older.id).status == "interrupted"
    assert repo.get(newer.id).status == "queued"
    assert len(repo.list()) == 2


def test_recover_aborts_when_download_queue_stopped(
    db_manager, operation_task_service, manager
) -> None:
    """队列已停止时明确报错并中止恢复，不静默入队。"""
    del db_manager
    task = operation_task_service.create(
        "download", OperationContext.system(), manga_id="400"
    )
    manager.queue_running = False

    result = manager.recover_tasks([task])

    assert result == DownloadRecoveryResult(
        recovered_count=0,
        resumed_count=0,
        skipped_count=1,
        aborted=True,
    )
    assert manager.queued_tasks == {}
    manager.logger.error.assert_called_once()


def test_recover_skips_manga_already_active_in_memory(
    operation_task_service, manager
) -> None:
    """内存中已有同漫画活动任务时跳过数据库遗留记录。"""
    task = operation_task_service.create(
        "download", OperationContext.system(), manga_id="500"
    )
    manager.queued_tasks["500"] = DownloadQueueItem(
        manga_id="500",
        context=OperationContext.system(),
        operation_task_id="existing-task",
        notifier=None,
    )

    result = manager.recover_tasks([task])

    assert result == DownloadRecoveryResult(
        recovered_count=0,
        resumed_count=0,
        skipped_count=1,
    )
    assert manager.download_queue.qsize() == 0
