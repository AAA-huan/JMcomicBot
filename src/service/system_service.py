"""WebUI 系统状态聚合服务。"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from src.database.models import utc_now
from src.database.repositories import MangaRepository


@dataclass(frozen=True)
class SystemStatusResult:
    """渠道无关的系统状态结果。"""

    version: str
    uptime_seconds: int
    napcat_connected: bool
    manga_count: int
    download_queue: dict[str, object]
    send_queue: dict[str, object]


class SystemService:  # pylint: disable=too-few-public-methods
    """聚合机器人版本、运行时间、连接和队列状态。"""

    def __init__(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        version: str,
        started_at: datetime,
        manga_repository: MangaRepository,
        connection_provider: Callable[[], bool],
        download_queue_provider: Callable[[], dict[str, object]],
        send_queue_provider: Callable[[], dict[str, object]],
    ) -> None:
        self.version = version
        self.started_at = started_at
        self.manga_repository = manga_repository
        self.connection_provider = connection_provider
        self.download_queue_provider = download_queue_provider
        self.send_queue_provider = send_queue_provider

    def get_status(self) -> SystemStatusResult:
        """返回当前系统状态快照。"""
        uptime = max(0, int((utc_now() - self.started_at).total_seconds()))
        return SystemStatusResult(
            version=self.version,
            uptime_seconds=uptime,
            napcat_connected=self.connection_provider(),
            manga_count=self.manga_repository.count(),
            download_queue=self.download_queue_provider(),
            send_queue=self.send_queue_provider(),
        )
