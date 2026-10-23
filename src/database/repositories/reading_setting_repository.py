"""阅读器偏好设置仓储，按 Web 管理员账户维护一份设置。"""

# 各仓储按资源定义查询参数，不要求抽象入口的可变参数签名。
# pylint: disable=arguments-differ

from typing import List, Optional

from sqlalchemy import select

from src.database.models import ReadingSetting, utc_now

from ._base import BaseRepository


class ReadingSettingRepository(BaseRepository):
    """阅读器偏好设置仓储，一个管理员对应一条记录。"""

    def get(self, admin_id: int) -> Optional[ReadingSetting]:
        """按管理员账户ID查询阅读设置。"""
        with self._get_session() as session:
            return session.get(ReadingSetting, admin_id)

    def list(self) -> List[ReadingSetting]:
        """按管理员账户ID升序返回全部阅读设置。"""
        with self._get_session() as session:
            statement = select(ReadingSetting).order_by(ReadingSetting.admin_id)
            return list(session.scalars(statement).all())

    def exists(self, admin_id: int) -> bool:
        """判断管理员是否已保存过阅读设置。"""
        with self._get_session() as session:
            return session.get(ReadingSetting, admin_id) is not None

    def upsert(
        self,
        admin_id: int,
        reading_mode: str,
        continuous: bool,
        click_to_turn: bool,
        reverse_click: bool,
        dark_background: bool,
        prefetch_pages: int,
    ) -> ReadingSetting:
        """插入或整体更新阅读设置，返回已保存记录。"""
        with self._get_session() as session:
            setting = session.get(ReadingSetting, admin_id)
            if setting is None:
                setting = ReadingSetting(admin_id=admin_id)
                session.add(setting)
            setting.reading_mode = reading_mode
            setting.continuous = continuous
            setting.click_to_turn = click_to_turn
            setting.reverse_click = reverse_click
            setting.dark_background = dark_background
            setting.prefetch_pages = prefetch_pages
            setting.updated_at = utc_now()
            session.commit()
            session.refresh(setting)
            return setting
