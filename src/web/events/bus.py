"""线程安全事件总线：业务线程发布，事件循环中的 WebSocket 连接订阅。"""

import asyncio
from datetime import timezone
from threading import Lock
from typing import Any, Dict, Set

from src.database.models import utc_now


def build_event(event_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """构造版本化的统一事件格式，时间使用带时区的 UTC ISO8601。"""
    occurred_at = utc_now().replace(tzinfo=timezone.utc).isoformat()
    return {"type": event_type, "occurred_at": occurred_at, "data": data}


class EventSubscriber:
    """单个 WebSocket 连接的订阅者，绑定创建它的事件循环。"""

    def __init__(
        self, loop: asyncio.AbstractEventLoop, max_queue_size: int = 200
    ) -> None:
        self._loop = loop
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=max_queue_size)
        self._closed = False
        self._dropped_count = 0

    @property
    def dropped_count(self) -> int:
        """返回因队列满而丢弃的事件数量。"""
        return self._dropped_count

    async def get(self) -> Dict[str, Any]:
        """等待下一条事件。"""
        return await self._queue.get()

    def _enqueue(self, event: Dict[str, Any]) -> None:
        """在事件循环内入队；队列满时丢弃最旧事件并计数。"""
        if self._closed:
            return
        if self._queue.full():
            try:
                self._queue.get_nowait()
                self._dropped_count += 1
            except asyncio.QueueEmpty:
                pass
        self._queue.put_nowait(event)

    def deliver(self, event: Dict[str, Any]) -> None:
        """从任意线程投递事件；事件循环已关闭时清理订阅。"""
        if self._closed:
            return
        try:
            self._loop.call_soon_threadsafe(self._enqueue, event)
        except RuntimeError:
            self.close()

    def close(self) -> None:
        """关闭订阅并清空未发送事件。"""
        self._closed = True
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break


class WebEventBus:
    """线程安全的事件发布/订阅中心，不持有任何业务对象。"""

    def __init__(self, max_queue_size: int = 200) -> None:
        self._max_queue_size = max_queue_size
        self._subscribers: Set[EventSubscriber] = set()
        self._lock = Lock()

    @property
    def subscriber_count(self) -> int:
        """当前订阅者数量，供广播器按需采样。"""
        with self._lock:
            return len(self._subscribers)

    def subscribe(self) -> EventSubscriber:
        """订阅事件；必须在事件循环内调用。"""
        loop = asyncio.get_running_loop()
        subscriber = EventSubscriber(loop, self._max_queue_size)
        with self._lock:
            self._subscribers.add(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: EventSubscriber) -> None:
        """取消订阅并释放队列。"""
        with self._lock:
            self._subscribers.discard(subscriber)
        subscriber.close()

    def publish(self, event_type: str, data: Dict[str, Any]) -> None:
        """发布事件；可在任意线程调用，不阻塞业务。"""
        event = build_event(event_type, data)
        with self._lock:
            subscribers = tuple(self._subscribers)
        for subscriber in subscribers:
            subscriber.deliver(event)
