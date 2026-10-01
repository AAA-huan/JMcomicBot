"""QQ 命令与未来 Web API 共用的应用服务协议。"""

from typing import Any, Dict, List, Optional, Protocol

from src.service.operation_context import OperationContext
from src.service.results import (
    DownloadCancellationResult,
    DownloadRequestItem,
    DownloadRequestResult,
    TaskResult,
)


class DownloadNotifier(Protocol):
    """下载过程通知回调；不传表示静默（Web/系统来源）。"""

    def message(self, text: str) -> None:
        """发送一条文本通知。"""
        raise NotImplementedError

    def file(self, file_path: str) -> None:
        """发送一个文件通知。"""
        raise NotImplementedError


class DownloadQueueGateway(Protocol):
    """下载应用服务依赖的最小队列能力。"""

    def cancel_download(self, manga_id: str) -> bool:
        """取消单个排队任务。"""
        raise NotImplementedError

    def cancel_all_downloads(self) -> int:
        """取消全部排队任务。"""
        raise NotImplementedError

    def find_active_download(self, manga_id: str) -> Optional[str]:
        """返回内存中活动下载任务的 ID，无活动任务时返回 None。"""
        raise NotImplementedError

    def request_download(
        self,
        manga_id: str,
        context: OperationContext,
        notifier: Optional[DownloadNotifier],
    ) -> DownloadRequestItem:
        """请求下载单个漫画并返回入队结果。"""
        raise NotImplementedError


class DownloadService(Protocol):
    """下载任务应用服务接口。"""

    def cancel(self, manga_ids: List[str]) -> DownloadCancellationResult:
        """取消指定漫画的排队任务。"""
        raise NotImplementedError

    def cancel_all(self) -> DownloadCancellationResult:
        """取消全部排队任务。"""
        raise NotImplementedError

    def request(
        self,
        manga_ids: List[str],
        context: OperationContext,
        notifier: Optional[DownloadNotifier] = None,
    ) -> DownloadRequestResult:
        """校验、去重并请求下载。"""
        raise NotImplementedError


class TaskService(Protocol):
    """持久化操作任务的应用服务接口。"""

    def create(
        self,
        task_type: str,
        context: OperationContext,
        manga_id: Optional[str] = None,
    ) -> TaskResult:
        """创建任务并返回稳定任务快照。"""
        raise NotImplementedError

    def start(self, task_id: str, stage: str) -> TaskResult:
        """开始任务。"""
        raise NotImplementedError

    def progress(
        self,
        task_id: str,
        stage: str,
        progress: Optional[int],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TaskResult:
        """更新任务进度。"""
        raise NotImplementedError

    def succeed(
        self,
        task_id: str,
        metadata: Optional[Dict[str, Any]] = None,
        context: Optional[OperationContext] = None,
    ) -> TaskResult:
        """完成任务。"""
        raise NotImplementedError

    def fail(
        self,
        task_id: str,
        error_code: str,
        error_message: str,
        context: Optional[OperationContext] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TaskResult:
        """标记任务失败。"""
        raise NotImplementedError

    def cancel(self, task_id: str) -> TaskResult:
        """取消尚未开始的任务。"""
        raise NotImplementedError

    def recover_interrupted(self) -> int:
        """中断遗留的运行中任务。"""
        raise NotImplementedError
