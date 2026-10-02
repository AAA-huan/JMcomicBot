"""下载队列应用服务。"""

from typing import List, Optional

from src.service.contracts import DownloadNotifier, DownloadQueueGateway, TaskService
from src.service.operation_context import OperationContext
from src.service.results import (
    DownloadCancellationResult,
    DownloadRequestItem,
    DownloadRequestResult,
    TaskCancellationResult,
)

# 单次下载请求的漫画数量上限，防止一次提交过多任务
DOWNLOAD_REQUEST_LIMIT = 20


class DownloadQueueService:
    """提供与 QQ、Web 展示方式无关的下载队列操作。"""

    def __init__(
        self, download_queue: DownloadQueueGateway, task_service: TaskService
    ) -> None:
        self.download_queue = download_queue
        self.task_service = task_service

    def cancel(self, manga_ids: List[str]) -> DownloadCancellationResult:
        """取消指定漫画的排队任务，并返回实际取消的漫画 ID。"""
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

    def request(
        self,
        manga_ids: List[str],
        context: OperationContext,
        notifier: Optional[DownloadNotifier] = None,
    ) -> DownloadRequestResult:
        """校验、去重并请求下载，重复请求返回既有任务而不是重复建立。

        Args:
            manga_ids: 待下载漫画 ID 列表，允许重复，服务内保序去重
            context: 操作来源上下文，贯穿任务与审计
            notifier: 通知器；QQ 传适配器，Web/系统来源传 None 表示静默

        Returns:
            DownloadRequestResult: 每个漫画的入队结果

        Raises:
            ValueError: 数量超限或 ID 不是数字时
        """
        normalized_ids = self._normalize_manga_ids(manga_ids)
        items: List[DownloadRequestItem] = []
        for manga_id in normalized_ids:
            # 数据库中的活动任务优先：即使内存队列因重启丢失，也不能重复建任务
            active_task = self.task_service.find_active_download(manga_id)
            if active_task is not None:
                items.append(
                    DownloadRequestItem(
                        manga_id=manga_id,
                        status="duplicate",
                        task_id=active_task.id,
                    )
                )
                continue
            active_task_id = self.download_queue.find_active_download(manga_id)
            if active_task_id is not None:
                items.append(
                    DownloadRequestItem(
                        manga_id=manga_id,
                        status="duplicate",
                        task_id=active_task_id,
                    )
                )
                continue
            items.append(
                self.download_queue.request_download(manga_id, context, notifier)
            )
        return DownloadRequestResult(items=tuple(items))

    def cancel_task(self, task_id: str) -> TaskCancellationResult:
        """取消尚未开始的下载任务；重启后遗留的排队记录会被直接标记取消。"""
        task = self.task_service.get(task_id)
        if task is None:
            return TaskCancellationResult(task_id, "not_found")
        if task.task_type != "download":
            return TaskCancellationResult(task_id, "not_download")
        if task.status != "queued" or task.manga_id is None:
            return TaskCancellationResult(task_id, "not_queued")
        if not self.download_queue.cancel_download(task.manga_id):
            # 内存队列已无该任务（例如重启后的遗留排队记录），直接标记取消并写事件
            self.task_service.cancel(task_id)
        return TaskCancellationResult(task_id, "cancelled")

    def cancel_queued_tasks(self) -> int:
        """取消全部尚未开始的下载任务，并清理启动后遗留的排队记录。"""
        cancelled_count = self.download_queue.cancel_all_downloads()
        for task in self.task_service.list_active_downloads():
            if task.status == "queued":
                self.task_service.cancel(task.id)
                cancelled_count += 1
        return cancelled_count

    @staticmethod
    def _normalize_manga_ids(manga_ids: List[str]) -> List[str]:
        """校验数量与 ID 格式，并按首次出现顺序去重。"""
        if not manga_ids:
            raise ValueError("请至少提供一个漫画 ID")
        normalized_ids: List[str] = []
        seen: set[str] = set()
        for raw_manga_id in manga_ids:
            manga_id = raw_manga_id.strip()
            if not manga_id.isdigit():
                raise ValueError(f"漫画 ID 必须是数字: {raw_manga_id}")
            if manga_id in seen:
                continue
            seen.add(manga_id)
            normalized_ids.append(manga_id)
        if len(normalized_ids) > DOWNLOAD_REQUEST_LIMIT:
            raise ValueError(f"单次最多请求 {DOWNLOAD_REQUEST_LIMIT} 个漫画下载")
        return normalized_ids
