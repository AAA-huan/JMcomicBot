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
