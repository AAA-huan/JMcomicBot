"""应用服务对外返回的渠道无关结果对象。"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple


@dataclass(frozen=True)
class TaskResult:  # pylint: disable=too-many-instance-attributes
    """任务服务的稳定返回值，不向调用方暴露 ORM 会话对象。"""

    id: str
    task_type: str
    source: str
    status: str
    stage: str
    progress: Optional[int]
    manga_id: Optional[str]
    summary: str
    error_code: Optional[str]
    error_message: Optional[str]


@dataclass(frozen=True)
class BackupResult:
    """一致性数据库备份结果。"""

    task_id: str
    path: Path
    file_count: int
    backup_id: int
    filename: str
    file_size_bytes: int


@dataclass(frozen=True)
class DownloadCancellationResult:
    """取消下载请求的汇总结果。"""

    cancelled_ids: Tuple[str, ...]
    cancelled_count: int


@dataclass(frozen=True)
class VerifyResult:
    """文件校验任务的汇总结果。"""

    task_id: str
    file_count: int
    ready_count: int
    missing_count: int
    corrupted_count: int
    invalid_path_count: int
    error_count: int


@dataclass(frozen=True)
class DownloadRequestItem:
    """单个漫画的下载请求结果。"""

    manga_id: str
    status: str
    task_id: Optional[str]


@dataclass(frozen=True)
class DownloadRequestResult:
    """批量下载请求的汇总结果，保持请求顺序且已去重。"""

    items: Tuple[DownloadRequestItem, ...]

    @property
    def queued_items(self) -> Tuple[DownloadRequestItem, ...]:
        """实际进入下载队列的条目。"""
        return tuple(item for item in self.items if item.status == "queued")

    @property
    def duplicate_items(self) -> Tuple[DownloadRequestItem, ...]:
        """因已存在活动任务而未重复入队的条目。"""
        return tuple(item for item in self.items if item.status == "duplicate")

    @property
    def queued_count(self) -> int:
        """实际入队的请求数量。"""
        return len(self.queued_items)

    @property
    def duplicate_count(self) -> int:
        """已有活动任务的请求数量。"""
        return len(self.duplicate_items)


@dataclass(frozen=True)
class DownloadRecoveryResult:
    """启动恢复下载任务的汇总结果。

    recovered_count 为成功重新入队的任务数，resumed_count 为其中由运行中
    中断后继续的任务数，skipped_count 为数据异常、状态不合法或冲突跳过的
    任务数；aborted 表示下载队列已停止，恢复流程提前终止。
    """

    recovered_count: int
    resumed_count: int
    skipped_count: int
    aborted: bool = False


@dataclass(frozen=True)
class MangaDeleteOutcome:
    """单个漫画的删除结果。"""

    manga_id: str
    succeeded: bool
    error_code: Optional[str]
    deleted_file_count: int
    error_message: Optional[str] = None


@dataclass(frozen=True)
class MangaDeleteResult:
    """批量删除的渠道无关结果，全部成功才算整体成功。"""

    task_id: str
    outcomes: Tuple[MangaDeleteOutcome, ...]

    @property
    def succeeded_count(self) -> int:
        """删除成功的漫画数量。"""
        return sum(1 for outcome in self.outcomes if outcome.succeeded)

    @property
    def failed_count(self) -> int:
        """删除失败的漫画数量。"""
        return len(self.outcomes) - self.succeeded_count

    @property
    def all_succeeded(self) -> bool:
        """批量删除是否全部成功。"""
        return self.failed_count == 0

    @property
    def deleted_file_count(self) -> int:
        """实际删除的文件总数。"""
        return sum(outcome.deleted_file_count for outcome in self.outcomes)


@dataclass(frozen=True)
class TaskCancellationResult:
    """单个任务取消结果，status 为 cancelled/not_found/not_download/not_queued。"""

    task_id: str
    status: str


@dataclass(frozen=True)
class BatchTaskItem:
    """批量任务操作的单项结果，status 取决于操作类型。

    cancel: cancelled / not_queued / not_found
    retry: requeued / duplicate / not_retryable / not_found
    """

    task_id: str
    status: str
    manga_id: Optional[str] = None


@dataclass(frozen=True)
class BatchTaskResult:
    """批量任务操作汇总结果。"""

    items: Tuple[BatchTaskItem, ...]

    @property
    def succeeded_count(self) -> int:
        """实际成功（cancelled 或 requeued）的数量。"""
        return sum(1 for item in self.items if item.status in ("cancelled", "requeued"))

    @property
    def failed_count(self) -> int:
        """失败或不可操作的数量。"""
        return len(self.items) - self.succeeded_count
