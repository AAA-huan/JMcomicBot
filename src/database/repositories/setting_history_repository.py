"""运行时配置修改历史仓储，只保存脱敏后的前后值"""

# pylint: disable=arguments-differ

from typing import List, Optional

from sqlalchemy import select

from src.database.database import DatabaseManager
from src.database.models import SettingHistory, utc_now
from src.database.repositories._base import BaseRepository


class SettingHistoryRepository(BaseRepository):
    """配置修改历史仓储，提供脱敏历史的追加与查询"""

    def __init__(self, db_manager: DatabaseManager) -> None:
        super().__init__(db_manager)

    def get(self, history_id: int) -> Optional[SettingHistory]:
        """按记录 ID 查询单条配置修改历史"""
        with self._get_session() as session:
            return session.get(SettingHistory, history_id)

    def list(
        self, key: Optional[str] = None, page: int = 1, page_size: int = 50
    ) -> List[SettingHistory]:
        """按配置键分页查询修改历史（新记录在前）"""
        statement = select(SettingHistory)
        if key is not None:
            statement = statement.where(SettingHistory.key == key)
        with self._get_session() as session:
            statement = (
                statement.order_by(
                    SettingHistory.changed_at.desc(), SettingHistory.id.desc()
                )
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            return list(session.scalars(statement).all())

    def record(
        self,
        key: str,
        old_value_masked: str,
        new_value_masked: str,
        source: str,
        changed_by: str = "",
    ) -> SettingHistory:
        """追加一条脱敏后的配置修改历史，调用方必须已完成脱敏"""
        history = SettingHistory(
            key=key,
            old_value_masked=old_value_masked,
            new_value_masked=new_value_masked,
            source=source,
            changed_by=changed_by,
            changed_at=utc_now(),
        )
        with self._get_session() as session:
            session.add(history)
            session.commit()
            session.refresh(history)
            return history
