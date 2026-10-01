"""运行时配置仓储，负责 setting 表中动态键值配置的读写"""

# pylint: disable=arguments-differ

from typing import List, Optional

from src.database.database import DatabaseManager
from src.database.models import Setting
from src.database.repositories._base import BaseRepository


class SettingRepository(BaseRepository):
    """运行时配置仓储，提供键值配置的读写"""

    def __init__(self, db_manager: DatabaseManager) -> None:
        super().__init__(db_manager)

    def get(self, key: str, default: str = "") -> str:
        """读取指定键的配置值

        Args:
            key: 配置键
            default: 键不存在时的默认值

        Returns:
            str: 配置值
        """
        with self._get_session() as session:
            setting = session.get(Setting, key)
            return setting.value if setting else default

    def get_optional(self, key: str) -> Optional[str]:
        """读取指定键的配置值，未显式保存时返回 None（区别于空字符串）"""
        with self._get_session() as session:
            setting = session.get(Setting, key)
            return setting.value if setting else None

    def get_int(self, key: str, default: int = 0) -> int:
        """读取整型配置值，解析失败时回退到默认值"""
        value = self.get(key, "")
        try:
            return int(value)
        except ValueError:
            return default

    def get_bool(self, key: str, default: bool = False) -> bool:
        """读取布尔配置值，解析失败时回退到默认值"""
        value = self.get(key, "").lower()
        if value in ("true", "1", "yes", "on"):
            return True
        if value in ("false", "0", "no", "off"):
            return False
        return default

    def list(self) -> List[Setting]:
        """查询全部配置项"""
        with self._get_session() as session:
            return list(session.query(Setting).all())

    def set(self, key: str, value: str) -> Setting:
        """写入配置值，键已存在时更新

        Args:
            key: 配置键
            value: 配置值

        Returns:
            Setting: 已保存的配置记录
        """
        with self._get_session() as session:
            setting = session.get(Setting, key)
            if setting is None:
                setting = Setting(key=key)
                session.add(setting)
            setting.value = value
            session.commit()
            session.refresh(setting)
            return setting

    def delete(self, key: str) -> bool:
        """删除指定键的配置

        Args:
            key: 配置键

        Returns:
            bool: 是否实际删除了记录
        """
        with self._get_session() as session:
            setting = session.get(Setting, key)
            if setting is None:
                return False
            session.delete(setting)
            session.commit()
            return True
