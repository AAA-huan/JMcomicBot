"""下载管理器请求入队逻辑的测试"""

from threading import Lock
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.download.manager import DownloadManager, DownloadQueueItem
from src.service import OperationContext
from src.service.results import DownloadRequestItem


def _make_manager() -> DownloadManager:
    """构造只具备入队所需属性的管理器替身，不启动队列线程。"""
    manager = object.__new__(DownloadManager)
    manager.logger = Mock()
    manager.queued_tasks = {}
    manager.downloading_mangas = {}
    manager.operation_task_ids = {}
    manager.operation_task_service = None
    manager._queue_state_lock = Lock()
    manager.queue_running = True
    manager.download_queue = Mock()
    manager.download_queue.put = Mock()
    return manager


def test_request_download_enqueues_item_with_notifier() -> None:
    """请求下载应把结构化队列项放入队列并返回稳定任务结果。"""
    manager = _make_manager()
    context = OperationContext.qq("10001")
    notifier = Mock()

    result = manager.request_download("100", context, notifier)

    assert result == DownloadRequestItem(manga_id="100", status="queued", task_id=None)
    queued_item = manager.queued_tasks["100"]
    assert queued_item.manga_id == "100"
    assert queued_item.context is context
    assert queued_item.notifier is notifier
    manager.download_queue.put.assert_called_once_with(queued_item)


def test_request_download_returns_existing_active_task() -> None:
    """已在排队或下载中的漫画返回既有任务 ID，不重复入队。"""
    manager = _make_manager()
    manager.queued_tasks["100"] = DownloadQueueItem(
        manga_id="100",
        context=OperationContext.qq("10001"),
        operation_task_id="task-100",
        notifier=None,
    )
    manager.operation_task_ids["100"] = "task-100"

    result = manager.request_download("100", OperationContext.qq("10001"), None)

    assert result.status == "duplicate"
    assert result.task_id == "task-100"
    manager.download_queue.put.assert_not_called()


def test_request_download_creates_web_task_with_operation_context() -> None:
    """Web 来源请求应创建 source=web 的任务并记录上下文。"""
    manager = _make_manager()
    task_service = Mock()
    task_service.create.return_value = SimpleNamespace(id="task-web")
    manager.operation_task_service = task_service
    context = OperationContext.web("1", "127.0.0.1")

    result = manager.request_download("300", context, None)

    assert result == DownloadRequestItem(
        manga_id="300", status="queued", task_id="task-web"
    )
    task_service.create.assert_called_once_with(
        task_type="download", context=context, manga_id="300"
    )
    assert manager.operation_task_ids["300"] == "task-web"
    assert manager.queued_tasks["300"].context is context


def test_request_download_rejects_stopped_queue() -> None:
    """队列停止后请求下载必须明确报错。"""
    manager = _make_manager()
    manager.queue_running = False

    with pytest.raises(RuntimeError, match="下载队列已停止"):
        manager.request_download("100", OperationContext.qq("10001"), None)


def test_queue_status_counts_active_download() -> None:
    """下载队列任务总数应包含正在下载的任务。"""
    manager = _make_manager()
    manager.download_queue.qsize = Mock(return_value=2)
    manager.downloading_mangas["100"] = True

    status = manager.get_queue_status()

    assert status["queue_size"] == 3
    assert status["pending_count"] == 2
    assert status["current_manga_id"] == "100"
    assert status["running"] is True


def test_queue_status_without_active_download() -> None:
    """没有正在下载的任务时总数等于排队数。"""
    manager = _make_manager()
    manager.download_queue.qsize = Mock(return_value=1)

    status = manager.get_queue_status()

    assert status["queue_size"] == 1
    assert status["pending_count"] == 1
    assert status["current_manga_id"] is None
