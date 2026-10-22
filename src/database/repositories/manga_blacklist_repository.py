"""漫画黑名单仓储，负责按漫画 ID 读写拉黑记录。"""

# 各仓储按资源定义查询参数，不要求抽象入口的可变参数签名。
# pylint: disable=arguments-differ

from datetime import datetime
from typing import List, Optional, Tuple

from sqlalchemy import Integer, cast, func, or_, select

from src.database.models import Manga, MangaBlacklist, utc_now

from ._base import BaseRepository

BlacklistRow = Tuple[MangaBlacklist, Optional[str]]


class MangaBlacklistRepository(BaseRepository):
    """漫画黑名单仓储，不依赖 manga 表存在对应元数据。"""

    def get(self, manga_id: str) -> Optional[MangaBlacklist]:
        """按漫画 ID 查询黑名单记录。"""
        with self._get_session() as session:
            return session.get(MangaBlacklist, manga_id)

    def list(self, page: int = 1, page_size: int = 50) -> List[MangaBlacklist]:
        """按拉黑时间倒序分页查询黑名单记录。"""
        with self._get_session() as session:
            statement = (
                select(MangaBlacklist)
                .order_by(
                    MangaBlacklist.blacklisted_at.desc(),
                    cast(MangaBlacklist.manga_id, Integer),
                )
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            return list(session.scalars(statement).all())

    def exists(self, manga_id: str) -> bool:
        """判断漫画是否已被拉黑，用于下载入口的快速命中检查。"""
        with self._get_session() as session:
            statement = select(MangaBlacklist.manga_id).where(
                MangaBlacklist.manga_id == manga_id
            )
            return session.scalar(statement) is not None

    def ids_for_mangas(self, manga_ids: List[str]) -> set[str]:
        """批量查询给定漫画中已被拉黑的 ID 集合。"""
        if not manga_ids:
            return set()
        with self._get_session() as session:
            statement = select(MangaBlacklist.manga_id).where(
                MangaBlacklist.manga_id.in_(manga_ids)
            )
            return set(session.scalars(statement).all())

    def add(
        self,
        manga_id: str,
        reason: Optional[str],
        requested_by: Optional[str],
        source: str,
        operation_task_id: Optional[str],
        blacklisted_at: Optional[datetime] = None,
    ) -> bool:
        """写入拉黑记录；主键已存在时不修改并返回 False。"""
        with self._get_session() as session:
            if session.get(MangaBlacklist, manga_id) is not None:
                return False
            session.add(
                MangaBlacklist(
                    manga_id=manga_id,
                    reason=reason,
                    requested_by=requested_by,
                    source=source,
                    blacklisted_at=blacklisted_at or utc_now(),
                    operation_task_id=operation_task_id,
                )
            )
            session.commit()
            return True

    def remove(self, manga_id: str) -> bool:
        """删除拉黑记录，返回是否实际删除。"""
        with self._get_session() as session:
            record = session.get(MangaBlacklist, manga_id)
            if record is None:
                return False
            session.delete(record)
            session.commit()
            return True

    def search(
        self, page: int, page_size: int, search: Optional[str] = None
    ) -> Tuple[List[BlacklistRow], int]:
        """分页查询黑名单，并 LEFT JOIN 漫画表补充可选标题。"""
        statement = select(MangaBlacklist).outerjoin(
            Manga, Manga.id == MangaBlacklist.manga_id
        )
        if search:
            pattern = f"%{search}%"
            statement = statement.where(
                or_(
                    MangaBlacklist.manga_id.like(pattern),
                    Manga.title.like(pattern),
                )
            )
        with self._get_session() as session:
            total = session.scalar(
                select(func.count()).select_from(  # pylint: disable=not-callable
                    statement.subquery()
                )
            )
            rows = session.execute(
                statement.add_columns(Manga.title)
                .order_by(
                    MangaBlacklist.blacklisted_at.desc(),
                    cast(MangaBlacklist.manga_id, Integer),
                )
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).all()
            return [(row[0], row[1]) for row in rows], int(total or 0)

    def count(self) -> int:
        """统计黑名单记录总数。"""
        with self._get_session() as session:
            total = session.scalar(
                select(func.count()).select_from(  # pylint: disable=not-callable
                    MangaBlacklist
                )
            )
            return int(total or 0)
