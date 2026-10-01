"""WebUI 系统状态聚合与控制服务。"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from src.database.models import utc_now
from src.database.repositories import AuditEventRepository, MangaRepository
from src.service.operation_context import OperationContext


@dataclass(frozen=True)
class SystemStatusResult:
    """渠道无关的系统状态结果。"""

    version: str
    uptime_seconds: int
    napcat_connected: bool
    manga_count: int
    download_queue: dict[str, object]
    send_queue: dict[str, object]


class SystemService:  # pylint: disable=too-many-instance-attributes
    """聚合机器人版本、运行时间、连接和队列状态，并提供受控系统操作。"""

    def __init__(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        version: str,
        started_at: datetime,
        manga_repository: MangaRepository,
        connection_provider: Callable[[], bool],
        download_queue_provider: Callable[[], dict[str, object]],
        send_queue_provider: Callable[[], dict[str, object]],
        reconnect_requester: Callable[[], bool],
        shutdown_requester: Callable[[OperationContext], None],
        audit_repository: AuditEventRepository,
    ) -> None:
        self.version = version
        self.started_at = started_at
        self.manga_repository = manga_repository
        self.connection_provider = connection_provider
        self.download_queue_provider = download_queue_provider
        self.send_queue_provider = send_queue_provider
        self.reconnect_requester = reconnect_requester
        self.shutdown_requester = shutdown_requester
        self.audit_repository = audit_repository

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

    def request_reconnect(self, context: Optional[OperationContext] = None) -> bool:
        """请求 NapCat 重新连接并记录审计，返回请求是否被接受。"""
        operation_context = context or OperationContext.system()
        accepted = self.reconnect_requester()
        self.audit_repository.record(
            event_type="napcat.reconnect_requested",
            source=operation_context.source,
            result="accepted" if accepted else "failed",
            actor_user_id=operation_context.actor_user_id,
            actor_group_id=operation_context.actor_group_id,
            client_ip=operation_context.client_ip,
            target_type="napcat",
            target_id="connection",
        )
        return accepted

    def request_shutdown(self, context: Optional[OperationContext] = None) -> None:
        """请求安全关闭；调用方（MangaBot）负责记录审计并触发关闭。"""
        operation_context = context or OperationContext.system()
        self.shutdown_requester(operation_context)
