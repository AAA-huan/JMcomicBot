"""下载队列应用服务。"""

from typing import List

from src.service.contracts import DownloadQueueGateway
from src.service.results import DownloadCancellationResult


class DownloadQueueService:
    """提供与 QQ、Web 展示方式无关的下载队列操作。"""

    def __init__(self, download_queue: DownloadQueueGateway) -> None:
        self.download_queue = download_queue

    def cancel(self, manga_ids: List[str]) -> DownloadCancellationResult:
        """取消指定排队任务，并返回实际取消的漫画 ID。"""
        cancelled_ids = tuple(
            manga_id
            for manga_id in manga_ids
            if self.download_queue.cancel_download(manga_id)
        )
        return DownloadCancellationResult(
            cancelled_ids=cancelled_ids,
            cancelled_count=len(cancelled_ids),
        )

    def cancel_all(self) -> DownloadCancellationResult:
        """取消全部排队任务。"""
        cancelled_count = self.download_queue.cancel_all_downloads()
        return DownloadCancellationResult(
            cancelled_ids=(),
            cancelled_count=cancelled_count,
        )
