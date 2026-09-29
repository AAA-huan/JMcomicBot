"""下载队列应用服务测试。"""

from typing import List

from src.service import DownloadQueueService


class _DownloadQueue:
    """记录取消调用的测试队列。"""

    def __init__(self, queued_ids: List[str]) -> None:
        self.queued_ids = set(queued_ids)

    def cancel_download(self, manga_id: str) -> bool:
        if manga_id not in self.queued_ids:
            return False
        self.queued_ids.remove(manga_id)
        return True

    def cancel_all_downloads(self) -> int:
        cancelled_count = len(self.queued_ids)
        self.queued_ids.clear()
        return cancelled_count


def test_cancel_returns_only_tasks_actually_cancelled() -> None:
    """服务结果应保持请求顺序，并排除不存在的任务。"""
    service = DownloadQueueService(_DownloadQueue(["100", "102"]))

    result = service.cancel(["100", "101", "102"])

    assert result.cancelled_ids == ("100", "102")
    assert result.cancelled_count == 2


def test_cancel_all_returns_cancelled_count() -> None:
    """批量取消结果不依赖 QQ 文案或 Web schema。"""
    service = DownloadQueueService(_DownloadQueue(["100", "101"]))

    result = service.cancel_all()

    assert result.cancelled_ids == ()
    assert result.cancelled_count == 2
