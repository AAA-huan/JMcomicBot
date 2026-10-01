"""WebSocket 事件总线单元测试。"""

import asyncio
import threading

from src.web.events.bus import WebEventBus


def test_publish_from_thread_reaches_subscriber() -> None:
    """业务线程发布的事件应能到达事件循环中的订阅者。"""
    bus = WebEventBus()

    async def scenario() -> dict:
        subscriber = bus.subscribe()
        thread = threading.Thread(
            target=bus.publish, args=("queue.updated", {"download": {}})
        )
        thread.start()
        thread.join()
        return await asyncio.wait_for(subscriber.get(), timeout=1)

    event = asyncio.run(scenario())

    assert event["type"] == "queue.updated"
    assert event["data"] == {"download": {}}
    assert "occurred_at" in event


def test_queue_overflow_drops_oldest_event() -> None:
    """订阅队列满时应丢弃最旧事件而不是阻塞发布线程。"""
    bus = WebEventBus(max_queue_size=2)

    async def scenario() -> tuple:
        subscriber = bus.subscribe()
        for index in range(3):
            bus.publish("task.updated", {"index": index})
        await asyncio.sleep(0.01)
        first = await subscriber.get()
        second = await subscriber.get()
        return subscriber, first, second

    subscriber, first, second = asyncio.run(scenario())

    assert first["data"]["index"] == 1
    assert second["data"]["index"] == 2
    assert subscriber.dropped_count == 1


def test_unsubscribe_stops_delivery() -> None:
    """取消订阅后不再投递事件，订阅者数量归零。"""
    bus = WebEventBus()

    async def scenario() -> int:
        subscriber = bus.subscribe()
        bus.unsubscribe(subscriber)
        bus.publish("system.updated", {"version": "x"})
        await asyncio.sleep(0.01)
        return bus.subscriber_count

    assert asyncio.run(scenario()) == 0
