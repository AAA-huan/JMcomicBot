"""下载队列应用服务测试。"""

from typing import List, Optional

import pytest

from src.service import DownloadQueueService, OperationContext
from src.service.results import DownloadRequestItem


class _ActiveTask:
    """模拟活动任务记录的最小对象。"""

    def __init__(self, manga_id: str) -> None:
        self.id = f"active-{manga_id}"


class _TaskRepository:
    """模拟活动下载任务查询的测试仓储。"""

    def __init__(self, active_ids: Optional[List[str]] = None) -> None:
        self.active_ids = set(active_ids or [])

    def find_active_download(self, manga_id: str) -> Optional[_ActiveTask]:
        if manga_id not in self.active_ids:
            return None
        return _ActiveTask(manga_id)


class _DownloadQueue:
    """记录取消与入队调用的测试队列。"""

    def __init__(self, queued_ids: List[str]) -> None:
        self.queued_ids = set(queued_ids)
        self.requested_ids: List[str] = []
        self.in_memory_active: Optional[str] = None

    def cancel_download(self, manga_id: str) -> bool:
        if manga_id not in self.queued_ids:
            return False
        self.queued_ids.remove(manga_id)
        return True

    def cancel_all_downloads(self) -> int:
        cancelled_count = len(self.queued_ids)
        self.queued_ids.clear()
        return cancelled_count

    def find_active_download(self, manga_id: str) -> Optional[str]:
        del manga_id
        return self.in_memory_active

    def request_download(
        self,
        manga_id: str,
        context: OperationContext,
        notifier: Optional[object],
    ) -> DownloadRequestItem:
        del context, notifier
        self.requested_ids.append(manga_id)
        return DownloadRequestItem(
            manga_id=manga_id, status="queued", task_id=f"task-{manga_id}"
        )


def _build_service(
    download_queue: _DownloadQueue, active_ids: Optional[List[str]] = None
) -> DownloadQueueService:
    """构造绑定测试队列与测试仓储的下载服务。"""
    return DownloadQueueService(
        download_queue,
        task_repository=_TaskRepository(active_ids),  # type: ignore[arg-type]
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
    assert download_queue.requested_ids == ["100", "101"]
    assert result.queued_count == 2
    assert result.duplicate_count == 0


def test_request_returns_existing_task_for_active_download() -> None:
    """数据库已有活动任务时应返回既有任务，不再重复建任务。"""
    download_queue = _DownloadQueue([])
    service = _build_service(download_queue, active_ids=["100"])

    result = service.request(["100", "101"], OperationContext.qq("10001"))

    assert result.duplicate_items == (result.items[0],)
    assert result.items[0].status == "duplicate"
    assert result.items[0].task_id == "active-100"
    assert download_queue.requested_ids == ["101"]


def test_request_returns_in_memory_duplicate_status() -> None:
    """内存队列已有活动任务时由网关返回 duplicate，不重复入队。"""
    download_queue = _DownloadQueue(["200"])
    download_queue.in_memory_active = "task-200"
    service = _build_service(download_queue)

    result = service.request(["200"], OperationContext.qq("10001"))

    assert result.items[0].status == "duplicate"
    assert result.items[0].task_id == "task-200"
    assert download_queue.requested_ids == []


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
