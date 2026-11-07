"""本地自定义漫画文件夹仓储，提供文件夹 CRUD 与成员管理。"""

# 文件夹仓储按资源定义专用查询方法，不要求与基类抽象入口签名一致。
# pylint: disable=arguments-differ

from typing import List, Optional, Set, Tuple

from sqlalchemy import delete, func, select, update

from src.database.models import Manga, MangaFolder, MangaFolderMember, utc_now

from ._base import BaseRepository


class FolderRepository(BaseRepository):
    """文件夹读写仓储；成员关系由联合主键保证幂等。"""

    def get(self, folder_id: int) -> Optional[MangaFolder]:
        """按主键查询文件夹。"""
        with self._get_session() as session:
            return session.get(MangaFolder, folder_id)

    def list(self) -> List[Tuple[MangaFolder, int]]:
        """查询全部文件夹及成员数，按排序值与 ID 稳定排列。"""
        with self._get_session() as session:
            # pylint: disable=not-callable
            rows = session.execute(
                select(MangaFolder, func.count(MangaFolderMember.manga_id))
                .outerjoin(
                    MangaFolderMember,
                    MangaFolderMember.folder_id == MangaFolder.id,
                )
                .group_by(MangaFolder.id)
                .order_by(MangaFolder.sort_order, MangaFolder.id)
            ).all()
            # pylint: enable=not-callable
            return [(folder, int(count)) for folder, count in rows]

    def get_by_name(self, name: str) -> Optional[MangaFolder]:
        """按名称精确查询文件夹，用于重名校验。"""
        with self._get_session() as session:
            return session.scalar(select(MangaFolder).where(MangaFolder.name == name))

    def create(self, name: str) -> MangaFolder:
        """创建文件夹，重名校验由服务层负责。"""
        with self._get_session() as session:
            folder = MangaFolder(name=name, created_at=utc_now(), updated_at=utc_now())
            session.add(folder)
            session.commit()
            session.refresh(folder)
            return folder

    def rename(self, folder_id: int, name: str) -> Optional[MangaFolder]:
        """重命名文件夹并刷新更新时间；文件夹不存在时返回 None。"""
        with self._get_session() as session:
            folder = session.get(MangaFolder, folder_id)
            if folder is None:
                return None
            folder.name = name
            folder.updated_at = utc_now()
            session.commit()
            session.refresh(folder)
            return folder

    def set_sort_order(self, folder_id: int, sort_order: int) -> Optional[MangaFolder]:
        """更新排序值并刷新更新时间；文件夹不存在时返回 None。"""
        with self._get_session() as session:
            folder = session.get(MangaFolder, folder_id)
            if folder is None:
                return None
            folder.sort_order = sort_order
            folder.updated_at = utc_now()
            session.commit()
            session.refresh(folder)
            return folder

    def delete(self, folder_id: int) -> bool:
        """删除文件夹；成员关系由外键级联清理，只删分组不删漫画。"""
        with self._get_session() as session:
            folder = session.get(MangaFolder, folder_id)
            if folder is None:
                return False
            session.delete(folder)
            session.commit()
            return True

    def member_ids(self, folder_id: int) -> List[str]:
        """查询文件夹内漫画 ID，按加入时间与 ID 稳定排列。"""
        with self._get_session() as session:
            return list(
                session.scalars(
                    select(MangaFolderMember.manga_id)
                    .where(MangaFolderMember.folder_id == folder_id)
                    .order_by(
                        MangaFolderMember.added_at.desc(), MangaFolderMember.manga_id
                    )
                ).all()
            )

    def folders_for_manga(self, manga_id: str) -> List[int]:
        """查询漫画所在的全部文件夹 ID。"""
        with self._get_session() as session:
            return list(
                session.scalars(
                    select(MangaFolderMember.folder_id)
                    .where(MangaFolderMember.manga_id == manga_id)
                    .order_by(MangaFolderMember.folder_id)
                ).all()
            )

    def existing_ids(self, manga_ids: List[str]) -> Set[str]:
        """一次查询存在的漫画 ID，未登记或已删除的漫画不能加入文件夹。"""
        if not manga_ids:
            return set()
        with self._get_session() as session:
            return set(
                session.scalars(
                    select(Manga.id).where(
                        Manga.id.in_(manga_ids), Manga.status != "deleted"
                    )
                ).all()
            )

    def members_in_folder(self, folder_id: int, manga_ids: List[str]) -> Set[str]:
        """返回给定漫画中已在文件夹内的集合，用于幂等加入统计。"""
        if not manga_ids:
            return set()
        with self._get_session() as session:
            return set(
                session.scalars(
                    select(MangaFolderMember.manga_id).where(
                        MangaFolderMember.folder_id == folder_id,
                        MangaFolderMember.manga_id.in_(manga_ids),
                    )
                ).all()
            )

    def add_members(self, folder_id: int, manga_ids: List[str]) -> int:
        """批量写入成员关系（调用方已过滤已在夹内的漫画）并刷新文件夹时间。"""
        if not manga_ids:
            return 0
        added_at = utc_now()
        with self._get_session() as session:
            session.add_all(
                [
                    MangaFolderMember(
                        folder_id=folder_id, manga_id=manga_id, added_at=added_at
                    )
                    for manga_id in manga_ids
                ]
            )
            session.execute(
                update(MangaFolder)
                .where(MangaFolder.id == folder_id)
                .values(updated_at=added_at)
            )
            session.commit()
            return len(manga_ids)

    def remove_members(self, folder_id: int, manga_ids: List[str]) -> int:
        """批量移出成员关系并刷新文件夹时间，返回实际删除行数。"""
        if not manga_ids:
            return 0
        with self._get_session() as session:
            result = session.execute(
                delete(MangaFolderMember).where(
                    MangaFolderMember.folder_id == folder_id,
                    MangaFolderMember.manga_id.in_(manga_ids),
                )
            )
            if result.rowcount > 0:
                session.execute(
                    update(MangaFolder)
                    .where(MangaFolder.id == folder_id)
                    .values(updated_at=utc_now())
                )
            session.commit()
            return int(result.rowcount)
