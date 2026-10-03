"""漫画收藏仓储，所有查询显式限定归属。"""

# pylint: disable=arguments-differ

from typing import List, Optional, Set

from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert

from src.database.models import Manga, MangaFavorite, MangaFile, utc_now

from ._base import BaseRepository


class FavoriteRepository(BaseRepository):
    """基于联合主键提供幂等收藏操作。"""

    def get(
        self, owner_type: str, owner_id: str, manga_id: str
    ) -> Optional[MangaFavorite]:
        """按归属和漫画查询收藏。"""
        with self._get_session() as session:
            return session.get(MangaFavorite, (owner_type, owner_id, manga_id))

    def list(self, owner_type: str, owner_id: str) -> List[MangaFavorite]:
        """查询指定归属的收藏，按收藏时间与 ID 稳定排序。"""
        with self._get_session() as session:
            return list(
                session.scalars(
                    select(MangaFavorite)
                    .where(
                        MangaFavorite.owner_type == owner_type,
                        MangaFavorite.owner_id == owner_id,
                    )
                    .order_by(MangaFavorite.created_at.desc(), MangaFavorite.manga_id)
                ).all()
            )

    def ids_for_mangas(
        self, owner_type: str, owner_id: str, manga_ids: List[str]
    ) -> Set[str]:
        """一次查询当前页收藏状态，避免逐漫画查询。"""
        with self._get_session() as session:
            return set(
                session.scalars(
                    select(MangaFavorite.manga_id).where(
                        MangaFavorite.owner_type == owner_type,
                        MangaFavorite.owner_id == owner_id,
                        MangaFavorite.manga_id.in_(manga_ids),
                    )
                ).all()
            )

    def is_admin_favorite_file(self, relative_path: str) -> bool:
        """按登记路径检查文件所属漫画，不能靠文件名推断收藏保护。"""
        with self._get_session() as session:
            return (
                session.scalar(
                    select(MangaFile.id)
                    .join(MangaFavorite, MangaFavorite.manga_id == MangaFile.manga_id)
                    .where(
                        MangaFavorite.owner_type == "web_admin",
                        MangaFile.relative_path == relative_path,
                    )
                    .limit(1)
                )
                is not None
            )

    def has_admin_favorite(self, manga_id: str) -> bool:
        """任意管理员的收藏均保护漫画，QQ 用户收藏不授予删除保护。"""
        with self._get_session() as session:
            return (
                session.scalar(
                    select(MangaFavorite.manga_id)
                    .where(
                        MangaFavorite.owner_type == "web_admin",
                        MangaFavorite.manga_id == manga_id,
                    )
                    .limit(1)
                )
                is not None
            )

    def set_favorite(
        self, owner_type: str, owner_id: str, manga_id: str, favorite: bool
    ) -> bool:
        """原子插入或删除；仅目标联合主键冲突时视为已收藏。"""
        with self._get_session() as session:
            if session.get(Manga, manga_id) is None:
                raise LookupError("未找到指定漫画")
            if favorite:
                statement = (
                    insert(MangaFavorite)
                    .values(
                        owner_type=owner_type,
                        owner_id=owner_id,
                        manga_id=manga_id,
                        created_at=utc_now(),
                    )
                    .on_conflict_do_nothing(
                        index_elements=["owner_type", "owner_id", "manga_id"]
                    )
                )
            else:
                statement = delete(MangaFavorite).where(
                    MangaFavorite.owner_type == owner_type,
                    MangaFavorite.owner_id == owner_id,
                    MangaFavorite.manga_id == manga_id,
                )
            result = session.execute(statement)
            session.commit()
            return result.rowcount > 0
