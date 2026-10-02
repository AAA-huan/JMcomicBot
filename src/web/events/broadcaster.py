"""系统状态采样广播器：只在状态变化时发布事件。"""

import asyncio
from time import monotonic
from typing import Callable, Optional

from src.logging.logger_config import logger
from src.service.system_service import SystemStatusResult
from src.web.events.bus import WebEventBus


class StatusBroadcaster:
    """周期性采样系统状态并发布队列、NapCat 与系统快照事件。"""

    def __init__(
        self,
        event_bus: WebEventBus,
        status_provider: Callable[[], SystemStatusResult],
        interval_seconds: float = 2.0,
        system_interval_seconds: float = 15.0,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("状态采样间隔必须大于 0")
        if system_interval_seconds < interval_seconds:
            raise ValueError("系统快照间隔不能小于状态采样间隔")
        self.event_bus = event_bus
        self.status_provider = status_provider
        self.interval_seconds = interval_seconds
        self.system_interval_seconds = system_interval_seconds

    async def run(self) -> None:
        """采样循环：无订阅者时休眠，不产生数据库查询。"""
        last_download: Optional[dict[str, object]] = None
        last_send: Optional[dict[str, object]] = None
        last_connected: Optional[bool] = None
        next_system_at = 0.0
        while True:
            if self.event_bus.subscriber_count == 0:
                await asyncio.sleep(self.interval_seconds)
                continue
            try:
                status = await asyncio.to_thread(self.status_provider)
            except Exception as error:  # pylint: disable=broad-exception-caught
                # 采样失败只记录并继续，不能悄悄终止整条推送链路
                logger.error(f"系统状态采样失败: {error}")
                await asyncio.sleep(self.interval_seconds)
                continue

            download_queue = dict(status.download_queue)
            send_queue = dict(status.send_queue)
            if download_queue != last_download or send_queue != last_send:
                self.event_bus.publish(
                    "queue.updated",
                    {"download": download_queue, "send": send_queue},
                )
                last_download = download_queue
                last_send = send_queue
            if status.napcat_connected != last_connected:
                self.event_bus.publish(
                    "napcat.updated", {"connected": status.napcat_connected}
                )
                last_connected = status.napcat_connected

            now = monotonic()
            if now >= next_system_at:
                self.event_bus.publish(
                    "system.updated",
                    {
                        "version": status.version,
                        "uptime_seconds": status.uptime_seconds,
                        "manga_count": status.manga_count,
                    },
                )
                next_system_at = now + self.system_interval_seconds

            await asyncio.sleep(self.interval_seconds)
