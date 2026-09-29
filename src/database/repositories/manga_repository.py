"""漫画与漫画文件仓储，负责已下载漫画元数据及 PDF 文件记录的读写"""

# pylint: disable=arguments-differ, too-many-positional-arguments

from datetime import datetime
from pathlib import Path
from typing import List, Optional

import os

from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from src.database.database import DatabaseManager
from src.database.models import Manga, MangaFile
from src.database.repositories._base import BaseRepository

_VALID_MANGA_STATUSES = {"downloaded", "missing_file", "invalid", "deleted"}
_VALID_FILE_STATUSES = {
    "ready",
    "missing",
    "corrupted",
    "deleting",
    "deleted",
    "invalid_path",
}


class MangaRepository(BaseRepository):
    """漫画元数据仓储，提供已下载漫画及相关 PDF 文件的增删改查"""

    def __init__(
        self, db_manager: DatabaseManager, download_root: Optional[str] = None
    ) -> None:
        super().__init__(db_manager)
        self.download_root = Path(download_root).resolve() if download_root else None

    def get(self, manga_id: str) -> Optional[Manga]:
        """按漫画ID查询漫画记录

        Args:
            manga_id: 漫画ID

        Returns:
            Optional[Manga]: 漫画记录，不存在时返回 None
        """
        with self._get_session() as session:
            stmt = (
                select(Manga)
                .where(Manga.id == manga_id)
                .options(selectinload(Manga.files))
            )
            return session.scalar(stmt)

    def list(self, page: int = 1, page_size: int = 50) -> List[Manga]:
        """分页查询漫画记录

        Args:
            page: 页码，从1开始
            page_size: 每页数量

        Returns:
            List[Manga]: 漫画记录列表
        """
        with self._get_session() as session:
            stmt = (
                select(Manga)
                .options(selectinload(Manga.files))
                .order_by(Manga.downloaded_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            return list(session.scalars(stmt).all())

    def get_all(self) -> List[Manga]:
        """查询全部漫画记录"""
        with self._get_session() as session:
            stmt = (
                select(Manga)
                .options(selectinload(Manga.files))
                .order_by(Manga.downloaded_at.desc())
            )
            return list(session.scalars(stmt).all())

    def find_by_author(self, author: str) -> List[Manga]:
        """按作者名模糊查询漫画（作者字段为逗号分隔的多作者）

        Args:
            author: 作者名

        Returns:
            List[Manga]: 该作者参与创作的漫画记录列表
        """
        with self._get_session() as session:
            stmt = (
                select(Manga)
                .where(Manga.author.like(f"%{author}%"))
                .options(selectinload(Manga.files))
                .order_by(Manga.downloaded_at.desc())
            )
            return list(session.scalars(stmt).all())

    def upsert(  # pylint: disable=too-many-arguments
        self,
        manga_id: str,
        title: str,
        author: str,
        tags: str,
        chapter_count: int,
        page_count: int,
        status: str = "downloaded",
    ) -> Manga:
        """插入或更新漫画元数据

        Args:
            manga_id: 漫画ID
            title: 漫画标题
            author: 漫画作者
            tags: 漫画类型标签(逗号分隔)
            chapter_count: 章节数
            page_count: 总页数
            status: 下载状态

        Returns:
            Manga: 已保存的漫画记录
        """
        if status not in _VALID_MANGA_STATUSES:
            raise ValueError(f"不支持的漫画状态: {status}")

        with self._get_session() as session:
            manga = session.get(Manga, manga_id)
            if manga is None:
                manga = Manga(id=manga_id)
                session.add(manga)
                manga.created_at = datetime.now()
            manga.title = title
            manga.author = author
            manga.tags = tags
            manga.chapter_count = chapter_count
            manga.page_count = page_count
            manga.status = status
            manga.updated_at = datetime.now()
            session.commit()
            session.refresh(manga)
            return manga

    def delete(self, manga_id: str) -> bool:
        """按漫画ID删除漫画记录及其关联文件记录

        Args:
            manga_id: 漫画ID

        Returns:
            bool: 是否删除了记录
        """
        with self._get_session() as session:
            manga = session.get(Manga, manga_id)
            if manga is None:
                return False
            session.delete(manga)
            session.commit()
            return True

    def add_file(self, manga_id: str, file_path: str, file_size_mb: float) -> MangaFile:
        """为指定漫画添加一条 PDF 文件记录

        Args:
            manga_id: 漫画ID
            file_path: PDF 文件绝对路径
            file_size_mb: 文件大小(MB)

        Returns:
            MangaFile: 已保存的文件记录
        """
        with self._get_session() as session:
            existing = session.scalars(
                select(MangaFile).where(MangaFile.file_path == file_path)
            ).first()
            file_size_bytes = (
                os.path.getsize(file_path)
                if os.path.isfile(file_path)
                else int(file_size_mb * 1024 * 1024)
            )
            relative_path = None
            if self.download_root is not None:
                resolved_path = Path(file_path).resolve()
                try:
                    relative_path = str(resolved_path.relative_to(self.download_root))
                except ValueError as error:
                    raise ValueError("PDF文件路径必须位于下载根目录内") from error
            if existing is not None:
                existing.file_size_mb = file_size_mb
                existing.file_size_bytes = file_size_bytes
                existing.display_name = os.path.basename(file_path)
                existing.status = "ready"
                existing.updated_at = datetime.now()
                existing.relative_path = relative_path
                session.commit()
                session.refresh(existing)
                return existing
            manga_file = MangaFile(
                manga_id=manga_id,
                file_path=file_path,
                file_size_mb=file_size_mb,
                display_name=os.path.basename(file_path),
                file_type="pdf",
                mime_type="application/pdf",
                file_size_bytes=file_size_bytes,
                status="ready",
                updated_at=datetime.now(),
                relative_path=relative_path,
            )
            session.add(manga_file)
            session.commit()
            session.refresh(manga_file)
            return manga_file

    def list_files(self, manga_id: str) -> List[MangaFile]:
        """查询指定漫画的 PDF 文件记录列表

        Args:
            manga_id: 漫画ID

        Returns:
            List[MangaFile]: 文件记录列表
        """
        with self._get_session() as session:
            stmt = (
                select(MangaFile)
                .where(MangaFile.manga_id == manga_id)
                .order_by(MangaFile.created_at)
            )
            return list(session.scalars(stmt).all())

    def update_file_status(self, file_id: int, status: str) -> bool:
        """更新 PDF 文件状态并返回是否找到目标文件。"""
        if status not in _VALID_FILE_STATUSES:
            raise ValueError(f"不支持的文件状态: {status}")

        with self._get_session() as session:
            manga_file = session.get(MangaFile, file_id)
            if manga_file is None:
                return False
            manga_file.status = status
            manga_file.updated_at = datetime.now()
            session.commit()
            return True

    def mark_manga_missing(self, manga_id: str) -> bool:
        """将漫画及其文件标记为缺失，不删除数据库记录。"""
        with self._get_session() as session:
            manga = session.get(Manga, manga_id)
            if manga is None:
                return False
            manga.status = "missing_file"
            manga.updated_at = datetime.now()
            for manga_file in manga.files:
                manga_file.status = "missing"
                manga_file.updated_at = datetime.now()
            session.commit()
            return True

    def resolve_file_path(self, file_id: int, download_root: str) -> Path:
        """解析登记文件路径并校验其位于下载根目录内。"""
        root = Path(download_root).resolve()
        with self._get_session() as session:
            manga_file = session.get(MangaFile, file_id)
            if manga_file is None or not manga_file.relative_path:
                raise ValueError("文件未登记相对路径")
            resolved_path = (root / manga_file.relative_path).resolve()
            try:
                resolved_path.relative_to(root)
            except ValueError as error:
                raise ValueError("文件路径超出下载根目录") from error
            if not resolved_path.is_file():
                raise FileNotFoundError(f"文件不存在: {resolved_path}")
            return resolved_path

    def delete_files(self, manga_id: str) -> int:
        """删除指定漫画的全部 PDF 文件记录

        Args:
            manga_id: 漫画ID

        Returns:
            int: 删除的记录数量
        """
        with self._get_session() as session:
            result = session.execute(
                delete(MangaFile).where(MangaFile.manga_id == manga_id)
            )
            session.commit()
            return result.rowcount or 0

    def count(self) -> int:
        """统计漫画记录总数"""
        with self._get_session() as session:
            return len(list(session.scalars(select(Manga)).all()))
