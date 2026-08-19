"""名称缓存模块，缓存 user_id → nickname 和 group_id → group_name 映射

从 OneBot 事件中提取的名称会被缓存，后续所有日志输出均可通过
NameCache.format_user / format_group 获取可读名称。
名称不可用时自动回退到原始 ID，保证日志不丢失关键信息。
"""

import threading
from typing import Dict, Optional


class NameCache:
    """线程安全的名称缓存（单例模式）"""

    _instance: Optional["NameCache"] = None
    _lock: threading.Lock = threading.Lock()

    def __init__(self) -> None:
        self._user_names: Dict[str, str] = {}
        self._group_names: Dict[str, str] = {}

    @classmethod
    def get_instance(cls) -> "NameCache":
        """获取 NameCache 单例实例"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def set_user_name(self, user_id: str, name: str) -> None:
        """缓存用户名称"""
        self._user_names[user_id] = name

    def set_group_name(self, group_id: str, name: str) -> None:
        """缓存群名称"""
        self._group_names[group_id] = name

    def get_user_name(self, user_id: str) -> Optional[str]:
        """获取用户名称，未缓存时返回 None"""
        return self._user_names.get(user_id)

    def get_group_name(self, group_id: str) -> Optional[str]:
        """获取群名称，未缓存时返回 None"""
        return self._group_names.get(group_id)

    def format_user(self, user_id: str) -> str:
        """格式化用户显示：有名称返回 '[昵称]'，否则回退到原始 ID"""
        name = self.get_user_name(user_id)
        return f"[{name}]" if name else user_id

    def format_group(self, group_id: str) -> str:
        """格式化群显示：有名称返回 '[群名]'，否则回退到原始 ID"""
        name = self.get_group_name(group_id)
        return f"[{name}]" if name else group_id
