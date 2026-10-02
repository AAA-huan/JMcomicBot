"""下载队列应用服务测试。"""

from types import SimpleNamespace
from typing import Dict, List, Optional

import pytest

from src.service import DownloadQueueService, OperationContext
from src.service.results import DownloadRequestItem


class _TaskService:
    """模拟任务服务：提供活动任务查询与取消记录。"""

    def __init__(self, active_task_ids: Optional[Dict[str, str]] = None) -> None:
        # manga_id -> 活动任务 ID
        self.active_task_ids = dict(active_task_ids or {})
        self.cancelled_task_ids: List[str] = []
        self.task_snapshots: Dict[str, SimpleNamespace] = {}

    def add_task(
        self, task_id: str, task_type: str, status: str, manga_id: str
    ) -> None:
        self.task_snapshots[task_id] = SimpleNamespace(
            id=task_id, task_type=task_type, status=status, manga_id=manga_id
        )

    def find_active_download(self, manga_id: str) -> Optional[SimpleNamespace]:
        task_id = self.active_task_ids.get(manga_id)
        if task_id is None:
            return None
        return SimpleNamespace(id=task_id)

    def get(self, task_id: str) -> Optional[SimpleNamespace]:
        return self.task_snapshots.get(task_id)

    def list_active_downloads(self) -> List[SimpleNamespace]:
        return [
            snapshot
            for snapshot in self.task_snapshots.values()
            if snapshot.status in ("queued", "running")
        ]

    def cancel(self, task_id: str) -> None:
        self.cancelled_task_ids.append(task_id)
        snapshot = self.task_snapshots.get(task_id)
        if snapshot is not None:
            snapshot.status = "cancelled"


class _DownloadQueue:
    """记录取消与入队调用的测试队列。"""

    def __init__(self, queued_manga_ids: List[str]) -> None:
        self.queued_manga_ids = set(queued_manga_ids)
        self.requested_manga_ids: List[str] = []

    def cancel_download(self, manga_id: str) -> bool:
        if manga_id not in self.queued_manga_ids:
            return False
        self.queued_manga_ids.remove(manga_id)
        return True

    def cancel_all_downloads(self) -> int:
        cancelled_count = len(self.queued_manga_ids)
        self.queued_manga_ids.clear()
        return cancelled_count

    def find_active_download(self, manga_id: str) -> Optional[str]:
        if manga_id not in self.queued_manga_ids:
            return None
        return f"memory-{manga_id}"

    def request_download(
        self,
        manga_id: str,
        context: OperationContext,
        notifier: Optional[object],
    ) -> DownloadRequestItem:
        del context, notifier
        self.requested_manga_ids.append(manga_id)
        return DownloadRequestItem(
            manga_id=manga_id, status="queued", task_id=f"task-{manga_id}"
        )


def _build_service(
    download_queue: _DownloadQueue,
    task_service: Optional[_TaskService] = None,
) -> DownloadQueueService:
    """构造绑定测试队列与测试任务服务的下载服务。"""
    return DownloadQueueService(
        download_queue,
        task_service=task_service or _TaskService(),  # type: ignore[arg-type]
    )


def test_cancel_returns_only_tasks_actually_cancelled() -> None:
    """服务结果应保持请求顺序，并排除不存在的任务。"""
    service = _build_service(_DownloadQueue(["100", "102"]))

    result = service.cancel(["100", "101", "102"])

    assert result.cancelled_ids == ("100", "102")
    assert result.cancelled_count == 2


def test_cancel_all_returns_cancelled_count() -> None:
    """批量取消结果不依赖 QQ 文案或 Web schema。"""
    service = _build_service(_DownloadQueue(["100", "101"]))

    result = service.cancel_all()

    assert result.cancelled_ids == ()
    assert result.cancelled_count == 2


def test_request_deduplicates_and_keeps_order() -> None:
    """请求下载应保序去重，重复 ID 只入队一次。"""
    download_queue = _DownloadQueue([])
    service = _build_service(download_queue)

    result = service.request(["100", "100", "101"], OperationContext.qq("10001"))

    assert [item.manga_id for item in result.queued_items] == ["100", "101"]
    assert download_queue.requested_manga_ids == ["100", "101"]
    assert result.queued_count == 2
    assert result.duplicate_count == 0


def test_request_returns_existing_task_for_active_download() -> None:
    """数据库已有活动任务时应返回既有任务，不再重复建任务。"""
    download_queue = _DownloadQueue([])
    service = _build_service(
        download_queue, _TaskService(active_task_ids={"100": "active-100"})
    )

    result = service.request(["100", "101"], OperationContext.qq("10001"))

    assert result.items[0].status == "duplicate"
    assert result.items[0].task_id == "active-100"
    assert download_queue.requested_manga_ids == ["101"]


def test_request_returns_in_memory_duplicate_status() -> None:
    """内存队列已有活动任务时由网关返回 duplicate，不重复入队。"""
    download_queue = _DownloadQueue(["200"])
    service = _build_service(download_queue)

    result = service.request(["200"], OperationContext.qq("10001"))

    assert result.items[0].status == "duplicate"
    assert result.items[0].task_id == "memory-200"
    assert download_queue.requested_manga_ids == []


def test_request_rejects_invalid_id() -> None:
    """非数字漫画 ID 应明确报错，而不是发起下载。"""
    service = _build_service(_DownloadQueue([]))

    with pytest.raises(ValueError, match="必须是数字"):
        service.request(["100", "abc"], OperationContext.qq("10001"))


def test_request_rejects_over_limit() -> None:
    """单次超过 20 个漫画 ID 应明确报错。"""
    service = _build_service(_DownloadQueue([]))
    manga_ids = [str(100000 + index) for index in range(21)]

    with pytest.raises(ValueError, match="最多请求 20 个"):
        service.request(manga_ids, OperationContext.qq("10001"))


def test_cancel_task_rejects_unknown_and_invalid_tasks() -> None:
    """不存在、非下载、已开始的任务应返回明确状态而不误取消。"""
    task_service = _TaskService()
    task_service.add_task("task-scan", "scan", "queued", "100")
    task_service.add_task("task-running", "download", "running", "200")
    service = _build_service(_DownloadQueue([]), task_service)

    assert service.cancel_task("missing").status == "not_found"
    assert service.cancel_task("task-scan").status == "not_download"
    assert service.cancel_task("task-running").status == "not_queued"
    assert task_service.cancelled_task_ids == []


def test_cancel_task_cancels_memory_queue_item() -> None:
    """排队中的任务由下载队列取消，不再重复标记任务。"""
    task_service = _TaskService()
    task_service.add_task("task-100", "download", "queued", "100")
    service = _build_service(_DownloadQueue(["100"]), task_service)

    result = service.cancel_task("task-100")

    assert result.status == "cancelled"
    assert task_service.cancelled_task_ids == []


def test_cancel_task_reconciles_stale_queued_record() -> None:
    """内存队列已无记录的重启遗留任务应直接标记取消并写事件。"""
    task_service = _TaskService()
    task_service.add_task("task-100", "download", "queued", "100")
    service = _build_service(_DownloadQueue([]), task_service)

    result = service.cancel_task("task-100")

    assert result.status == "cancelled"
    assert task_service.cancelled_task_ids == ["task-100"]


def test_cancel_queued_tasks_reconciles_stale_records() -> None:
    """取消全部排队任务时应同时清理内存队列与遗留排队记录。"""
    task_service = _TaskService()
    task_service.add_task("task-stale", "download", "queued", "300")
    task_service.add_task("task-running", "download", "running", "400")
    service = _build_service(_DownloadQueue(["100", "200"]), task_service)

    cancelled_count = service.cancel_queued_tasks()

    assert cancelled_count == 3
    assert task_service.cancelled_task_ids == ["task-stale"]
