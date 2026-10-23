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

    def find_active_downloads(self, manga_ids: List[str]) -> Dict[str, SimpleNamespace]:
        return {
            manga_id: SimpleNamespace(id=self.active_task_ids[manga_id])
            for manga_id in manga_ids
            if manga_id in self.active_task_ids
        }

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

    def requeue(self, task_id: str, reason: str = "") -> SimpleNamespace:
        """模拟重新入队：状态校验与同漫画活动任务冲突。"""
        del reason
        snapshot = self.task_snapshots.get(task_id)
        if snapshot is None:
            raise ValueError(f"任务不存在: {task_id}")
        if snapshot.task_type != "download":
            raise ValueError(f"非下载任务不支持重新入队: {task_id}")
        if snapshot.status not in ("failed", "interrupted"):
            raise ValueError(f"任务状态 {snapshot.status} 不允许重新入队")
        # 同漫画活动任务冲突校验
        for other in self.task_snapshots.values():
            if (
                other.id != task_id
                and other.manga_id == snapshot.manga_id
                and other.status in ("queued", "running")
            ):
                raise ValueError(f"漫画 {snapshot.manga_id} 已有活动任务 {other.id}")
        snapshot.status = "queued"
        return snapshot


class _BlacklistService:
    """提供黑名单命中检查的测试替身。"""

    def __init__(self, blacklisted_ids: Optional[List[str]] = None) -> None:
        self.blacklisted_ids = set(blacklisted_ids or [])
        self.checked_ids: List[str] = []

    def is_blacklisted(self, manga_id: str) -> bool:
        self.checked_ids.append(manga_id)
        return manga_id in self.blacklisted_ids


class _DownloadQueue:
    """记录取消与入队调用的测试队列。"""

    def __init__(self, queued_manga_ids: List[str]) -> None:
        self.queued_manga_ids = set(queued_manga_ids)
        self.requested_manga_ids: List[str] = []
        self.paused = False

    def pause(self) -> bool:
        if self.paused:
            return False
        self.paused = True
        return True

    def resume(self) -> bool:
        if not self.paused:
            return False
        self.paused = False
        return True

    def is_paused(self) -> bool:
        return self.paused

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

    def enqueue_existing_task(self, manga_id: str, task_id: str, context=None) -> bool:
        if manga_id in self.queued_manga_ids:
            return False
        self.queued_manga_ids.add(manga_id)
        return True

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
    blacklist_service: Optional[_BlacklistService] = None,
) -> DownloadQueueService:
    """构造绑定测试队列与测试任务服务的下载服务。"""
    return DownloadQueueService(
        download_queue,
        task_service=task_service or _TaskService(),  # type: ignore[arg-type]
        blacklist_service=blacklist_service,  # type: ignore[arg-type]
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


def test_request_skips_blacklisted_before_queueing() -> None:
    """命中的黑名单 ID 只回传跳过列表，不进入活动任务或入队流程。"""
    download_queue = _DownloadQueue([])
    blacklist = _BlacklistService(["100"])
    service = _build_service(download_queue, blacklist_service=blacklist)

    result = service.request(["100", "101", "100"], OperationContext.qq("10001"))

    assert result.skipped_blacklisted == ("100",)
    assert result.skipped_count == 1
    assert [item.manga_id for item in result.items] == ["101"]
    assert download_queue.requested_manga_ids == ["101"]
    assert blacklist.checked_ids == ["100", "101"]


def test_request_blacklist_precedes_active_download_dedup() -> None:
    """黑名单优先于数据库活动任务与内存队列去重。"""
    download_queue = _DownloadQueue(["100"])
    task_service = _TaskService(active_task_ids={"100": "active-100"})
    service = _build_service(
        download_queue,
        task_service,
        blacklist_service=_BlacklistService(["100"]),
    )

    result = service.request(["100"], OperationContext.qq("10001"))

    assert result.items == ()
    assert result.skipped_blacklisted == ("100",)
    assert download_queue.requested_manga_ids == []


def test_request_without_blacklist_service_keeps_behavior() -> None:
    """未注入黑名单服务时保持原有入队行为。"""
    download_queue = _DownloadQueue([])
    service = _build_service(download_queue)

    result = service.request(["100"], OperationContext.qq("10001"))

    assert result.skipped_blacklisted == ()
    assert download_queue.requested_manga_ids == ["100"]


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


def test_prepare_returns_pending_duplicates_and_blacklisted() -> None:
    """预检批量查询活动任务，返回待入队、重复与黑名单跳过三类结果。"""
    download_queue = _DownloadQueue(["300"])
    task_service = _TaskService(active_task_ids={"200": "active-200"})
    service = _build_service(
        download_queue,
        task_service,
        blacklist_service=_BlacklistService(["400"]),
    )

    result = service.prepare(["100", "200", "300", "400", "100"])

    assert result.pending_ids == ("100",)
    assert result.accepted_count == 1
    assert result.duplicate_count == 2
    assert result.skipped_blacklisted == ("400",)
    assert [(item.manga_id, item.status) for item in result.items] == [
        ("100", "accepted"),
        ("200", "duplicate"),
        ("300", "duplicate"),
    ]
    assert result.duplicate_items[0].task_id == "active-200"
    assert result.duplicate_items[1].task_id == "memory-300"
    assert download_queue.requested_manga_ids == []


def test_enqueue_pending_requests_each_manga_in_order() -> None:
    """后台入队按预检顺序逐个请求下载。"""
    download_queue = _DownloadQueue([])
    service = _build_service(download_queue)

    result = service.enqueue_pending(
        ["100", "101"], OperationContext.web("1", "127.0.0.1")
    )

    assert download_queue.requested_manga_ids == ["100", "101"]
    assert result.queued_count == 2


def test_pause_resume_are_forwarded_and_idempotent() -> None:
    """暂停/恢复转发到队列网关，重复调用返回 False。"""
    download_queue = _DownloadQueue([])
    service = _build_service(download_queue)

    assert service.is_paused() is False
    assert service.pause() is True
    assert service.pause() is False
    assert service.is_paused() is True
    assert service.resume() is True
    assert service.resume() is False
    assert service.is_paused() is False


def test_request_rejects_invalid_id() -> None:
    """非数字漫画 ID 应明确报错，而不是发起下载。"""
    service = _build_service(_DownloadQueue([]))

    with pytest.raises(ValueError, match="必须是数字"):
        service.request(["100", "abc"], OperationContext.qq("10001"))


def test_request_rejects_over_limit() -> None:
    """单次超过 100 个漫画 ID 应明确报错。"""
    service = _build_service(_DownloadQueue([]))
    manga_ids = [str(100000 + index) for index in range(101)]

    with pytest.raises(ValueError, match="最多请求 100 个"):
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


def test_cancel_tasks_returns_per_item_status() -> None:
    """批量取消逐项返回 cancelled/not_queued/not_found，去重保序。"""
    task_service = _TaskService()
    task_service.add_task("task-queued", "download", "queued", "100")
    task_service.add_task("task-running", "download", "running", "200")
    service = _build_service(_DownloadQueue(["100"]), task_service)

    result = service.cancel_tasks(
        ["task-queued", "task-running", "task-missing", "task-queued"]
    )

    statuses = [(item.task_id, item.status) for item in result.items]
    # 去重后 3 项，保序
    assert statuses == [
        ("task-queued", "cancelled"),
        ("task-running", "not_queued"),
        ("task-missing", "not_found"),
    ]
    assert result.succeeded_count == 1
    assert result.failed_count == 2


def test_retry_tasks_requeues_failed_and_interrupted() -> None:
    """批量重试：failed/interrupted 转回 queued 并装入内存队列。"""
    task_service = _TaskService()
    task_service.add_task("task-failed", "download", "failed", "100")
    task_service.add_task("task-interrupted", "download", "interrupted", "200")
    download_queue = _DownloadQueue([])
    service = _build_service(download_queue, task_service)

    result = service.retry_tasks(
        ["task-failed", "task-interrupted"], OperationContext.web("1", "127.0.0.1")
    )

    statuses = [(item.task_id, item.status, item.manga_id) for item in result.items]
    assert statuses == [
        ("task-failed", "requeued", "100"),
        ("task-interrupted", "requeued", "200"),
    ]
    assert result.succeeded_count == 2
    # 内存队列应已装入两个任务
    assert "100" in download_queue.queued_manga_ids
    assert "200" in download_queue.queued_manga_ids


def test_retry_tasks_rejects_wrong_status_and_not_found() -> None:
    """批量重试：非 failed/interrupted 状态返回 not_retryable，不存在返回 not_found。"""
    task_service = _TaskService()
    task_service.add_task("task-queued", "download", "queued", "100")
    task_service.add_task("task-succeeded", "download", "succeeded", "200")
    task_service.add_task("task-scan", "scan", "failed", "300")
    service = _build_service(_DownloadQueue([]), task_service)

    result = service.retry_tasks(
        ["task-queued", "task-succeeded", "task-scan", "task-missing"],
        OperationContext.web("1", "127.0.0.1"),
    )

    statuses = {item.task_id: item.status for item in result.items}
    assert statuses == {
        "task-queued": "not_retryable",
        "task-succeeded": "not_retryable",
        "task-scan": "not_retryable",  # 非下载任务
        "task-missing": "not_found",
    }
    assert result.succeeded_count == 0


def test_retry_tasks_returns_duplicate_on_active_conflict() -> None:
    """批量重试：同漫画已有活动任务时返回 duplicate。"""
    task_service = _TaskService()
    task_service.add_task("task-failed", "download", "failed", "100")
    task_service.add_task("task-active", "download", "queued", "100")
    service = _build_service(_DownloadQueue([]), task_service)

    result = service.retry_tasks(
        ["task-failed"], OperationContext.web("1", "127.0.0.1")
    )

    assert result.items[0].status == "duplicate"
    assert result.succeeded_count == 0
