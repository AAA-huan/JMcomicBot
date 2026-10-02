"""名称缓存模块，缓存 user_id → nickname 和 group_id → group_name 映射

从 OneBot 事件中提取的名称会被缓存，后续所有日志输出均可通过
NameCache.format_user / format_group 获取可读名称。
名称不可用时自动回退到原始 ID，保证日志不丢失关键信息。

缓存为 内存 + SQLite 双层结构：优先查内存，未命中时回查数据库，
写操作同步落库，确保机器人重启后昵称/群名不丢失。
"""

import threading
from typing import Dict, Optional

from src.database.repositories import UserGroupRepository
from src.logging.logger_config import logger


class NameCache:
    """线程安全的名称缓存（单例模式），内存 + SQLite 双层持久化"""

    _instance: Optional["NameCache"] = None
    _lock: threading.Lock = threading.Lock()

    def __init__(self) -> None:
        self._user_names: Dict[str, str] = {}
        self._group_names: Dict[str, str] = {}
        self._io_lock: threading.Lock = threading.Lock()
        self._repository: Optional[UserGroupRepository] = None

    @classmethod
    def get_instance(cls) -> "NameCache":
        """获取 NameCache 单例实例"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def attach_user_group_repo(self, repo: Optional[UserGroupRepository]) -> None:
        """挂载用户/群组信息仓储，实现缓存持久化

        Args:
            repo: 用户/群组信息仓储，未接入数据库时传 None
        """
        self._repository = repo
        if repo is not None:
            self._load_from_db()

    def _load_from_db(self) -> None:
        """启动时将数据库内已缓存的昵称与群名加载进内存"""
        repo = self._repository
        if repo is None:
            return
        try:
            for record in repo.list():
                if hasattr(record, "nickname"):
                    self._user_names[record.id] = record.nickname
                elif hasattr(record, "group_name"):
                    self._group_names[record.id] = record.group_name
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error(f"从数据库加载名称缓存失败: {e}")

    def set_user_name(self, user_id: str, name: str) -> None:
        """缓存用户名称，并落库

        Args:
            user_id: 用户ID
            name: 用户名称
        """
        with self._io_lock:
            if name is not None and name.strip():
                self._user_names[user_id] = name
                repo = self._repository
                if repo is not None:
                    try:
                        repo.upsert_user(user_id=user_id, nickname=name)
                    except Exception as e:  # pylint: disable=broad-exception-caught
                        logger.error(f"用户名称落库失败: {e}")

    def set_group_name(self, group_id: str, name: str) -> None:
        """缓存群名称，并落库

        Args:
            group_id: 群组ID
            name: 群名称
        """
        with self._io_lock:
            if name is not None and name.strip():
                self._group_names[group_id] = name
                repo = self._repository
                if repo is not None:
                    try:
                        repo.upsert_group(group_id=group_id, group_name=name)
                    except Exception as e:  # pylint: disable=broad-exception-caught
                        logger.error(f"群名称落库失败: {e}")

    def get_user_name(self, user_id: str) -> Optional[str]:
        """获取用户名称，内存未命中时回查数据库

        Args:
            user_id: 用户ID

        Returns:
            Optional[str]: 用户名称，未缓存时返回 None
        """
        name = self._user_names.get(user_id)
        if name:
            return name
        repo = self._repository
        if repo is not None:
            record = repo.get_user(user_id)
            if record is not None and record.nickname:
                with self._io_lock:
                    self._user_names[user_id] = record.nickname
                return record.nickname
        return None

    def get_group_name(self, group_id: str) -> Optional[str]:
        """获取群名称，内存未命中时回查数据库

        Args:
            group_id: 群组ID

        Returns:
            Optional[str]: 群名称，未缓存时返回 None
        """
        name = self._group_names.get(group_id)
        if name:
            return name
        repo = self._repository
        if repo is not None:
            record = repo.get_group(group_id)
            if record is not None and record.group_name:
                with self._io_lock:
                    self._group_names[group_id] = record.group_name
                return record.group_name
        return None

    def format_user(self, user_id: str) -> str:
        """格式化用户显示：有名称返回 '[昵称]'，否则回退到原始 ID"""
        name = self.get_user_name(user_id)
        return f"[{name}]" if name else user_id

    def format_group(self, group_id: str) -> str:
        """格式化群显示：有名称返回 '[群名]'，否则回退到原始 ID"""
        name = self.get_group_name(group_id)
        return f"[{name}]" if name else group_id
