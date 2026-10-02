"""应用服务事件发布协议与空实现。"""

from typing import Any, Dict, Protocol


class EventPublisher(Protocol):
    """应用服务向外发布状态事件的协议，实现必须线程安全。"""

    def publish(self, event_type: str, data: Dict[str, Any]) -> None:
        """发布一条事件，不阻塞调用线程。"""
        raise NotImplementedError


class NullEventPublisher:
    """无 WebUI 场景下的空事件发布器，不产生任何副作用。"""

    def publish(self, event_type: str, data: Dict[str, Any]) -> None:
        """忽略事件。"""
        del event_type, data


# 供脚本与测试复用的无副作用默认实现
NULL_EVENT_PUBLISHER = NullEventPublisher()
