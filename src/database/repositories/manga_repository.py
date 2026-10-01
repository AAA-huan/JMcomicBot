"""漫画与漫画文件仓储，负责已下载漫画元数据及 PDF 文件记录的读写"""

# pylint: disable=arguments-differ, too-many-positional-arguments

from datetime import datetime
from pathlib import Path
from typing import List, Optional

import os

from sqlalchemy import Select, delete, func, or_, select
from sqlalchemy.orm import selectinload

from src.database.database import DatabaseManager
from src.database.models import Manga, MangaFile, MangaTag, Tag, utc_now
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
                .order_by(Manga.downloaded_at.desc(), Manga.id)
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
                .order_by(Manga.downloaded_at.desc(), Manga.id)
            )
            return list(session.scalars(stmt).all())

    @staticmethod
    def _build_query(
        search: Optional[str], status: Optional[str], tag: Optional[str]
    ) -> Select[tuple[Manga]]:
        """构造仅使用固定字段的漫画筛选语句。"""
        statement = select(Manga)
        if search:
            pattern = f"%{search}%"
            statement = statement.where(
                or_(
                    Manga.id.like(pattern),
                    Manga.title.like(pattern),
                    Manga.author.like(pattern),
                )
            )
        if status:
            if status not in _VALID_MANGA_STATUSES:
                raise ValueError(f"不支持的漫画状态: {status}")
            statement = statement.where(Manga.status == status)
        if tag:
            normalized_tag = " ".join(tag.split()).casefold()
            tagged_mangas = (
                select(MangaTag.manga_id)
                .join(Tag, MangaTag.tag_id == Tag.id)
                .where(Tag.normalized_name == normalized_tag)
            )
            statement = statement.where(Manga.id.in_(tagged_mangas))
        return statement

    def search(
        self,
        page: int,
        page_size: int,
        search: Optional[str] = None,
        status: Optional[str] = None,
        tag: Optional[str] = None,
        sort: str = "downloaded_at_desc",
    ) -> tuple[List[Manga], int]:
        """按白名单条件分页查询漫画并返回总数。"""
        sort_columns = {
            "downloaded_at_desc": (Manga.downloaded_at.desc(), Manga.id),
            "downloaded_at_asc": (Manga.downloaded_at, Manga.id),
            "title_asc": (Manga.title, Manga.id),
            "title_desc": (Manga.title.desc(), Manga.id),
            "id_asc": (Manga.id,),
            "id_desc": (Manga.id.desc(),),
        }
        if sort not in sort_columns:
            raise ValueError(f"不支持的漫画排序方式: {sort}")
        base_statement = self._build_query(search, status, tag)
        with self._get_session() as session:
            total = session.scalar(
                select(func.count()).select_from(base_statement.subquery())
            )
            statement = (
                base_statement.options(selectinload(Manga.files))
                .order_by(*sort_columns[sort])
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            return list(session.scalars(statement).all()), int(total or 0)

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
                .order_by(Manga.downloaded_at.desc(), Manga.id)
            )
            return list(session.scalars(stmt).all())

    def upsert(  # pylint: disable=too-many-arguments
        self,
        manga_id: str,
        title: str,
        author: str,
        chapter_count: int,
        page_count: int,
        status: str = "downloaded",
    ) -> Manga:
        """插入或更新漫画元数据

        Args:
            manga_id: 漫画ID
            title: 漫画标题
            author: 漫画作者
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
                manga.created_at = utc_now()
            manga.title = title
            manga.author = author
            manga.chapter_count = chapter_count
            manga.page_count = page_count
            manga.status = status
            manga.updated_at = utc_now()
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

    def update_metadata(
        self,
        manga_id: str,
        title: Optional[str] = None,
        author: Optional[str] = None,
    ) -> bool:
        """更新漫画允许编辑的元数据字段

        Args:
            manga_id: 漫画ID
            title: 新标题，None 表示不修改
            author: 新作者，None 表示不修改

        Returns:
            bool: 是否找到并更新了漫画记录
        """
        with self._get_session() as session:
            manga = session.get(Manga, manga_id)
            if manga is None:
                return False
            if title is not None:
                manga.title = title
            if author is not None:
                manga.author = author
            manga.updated_at = utc_now()
            session.commit()
            return True

    def add_file(
        self,
        manga_id: str,
        file_path: str,
        page_count: Optional[int] = None,
        sha256: Optional[str] = None,
    ) -> MangaFile:
        """为指定漫画添加一条 PDF 文件记录

        Args:
            manga_id: 漫画ID
            file_path: PDF 文件绝对路径
            page_count: PDF页数，未知时使用0
            sha256: 已验证的文件摘要，未提供时清空旧摘要

        Returns:
            MangaFile: 已保存的文件记录
        """
        with self._get_session() as session:
            if self.download_root is None:
                raise ValueError("写入PDF文件前必须配置下载根目录")
            if session.get(Manga, manga_id) is None:
                raise ValueError(f"漫画记录不存在，无法写入文件: {manga_id}")
            resolved_path = Path(file_path).resolve()
            try:
                relative_path = str(resolved_path.relative_to(self.download_root))
            except ValueError as error:
                raise ValueError("PDF文件路径必须位于下载根目录内") from error
            if not resolved_path.is_file():
                raise FileNotFoundError(f"PDF文件不存在: {resolved_path}")
            file_size_bytes = resolved_path.stat().st_size
            existing = session.scalars(
                select(MangaFile).where(MangaFile.relative_path == relative_path)
            ).first()
            if existing is not None:
                if existing.manga_id != manga_id:
                    raise ValueError(
                        f"PDF相对路径已属于漫画 {existing.manga_id}: {relative_path}"
                    )
                existing.file_size_bytes = file_size_bytes
                existing.display_name = os.path.basename(file_path)
                existing.status = "ready"
                existing.updated_at = utc_now()
                existing.last_verified_at = None
                existing.sha256 = sha256
                if page_count is not None:
                    existing.page_count = page_count
                existing.relative_path = relative_path
                session.commit()
                session.refresh(existing)
                return existing
            existing_for_manga = session.scalars(
                select(MangaFile).where(MangaFile.manga_id == manga_id)
            ).first()
            if existing_for_manga is not None:
                existing_for_manga.display_name = os.path.basename(file_path)
                existing_for_manga.file_type = "pdf"
                existing_for_manga.mime_type = "application/pdf"
                existing_for_manga.file_size_bytes = file_size_bytes
                existing_for_manga.status = "ready"
                existing_for_manga.updated_at = utc_now()
                existing_for_manga.last_verified_at = None
                existing_for_manga.sha256 = sha256
                if page_count is not None:
                    existing_for_manga.page_count = page_count
                existing_for_manga.relative_path = relative_path
                session.commit()
                session.refresh(existing_for_manga)
                return existing_for_manga
            manga_file = MangaFile(
                manga_id=manga_id,
                display_name=os.path.basename(file_path),
                file_type="pdf",
                mime_type="application/pdf",
                file_size_bytes=file_size_bytes,
                page_count=page_count or 0,
                sha256=sha256,
                status="ready",
                updated_at=utc_now(),
                relative_path=relative_path,
            )
            session.add(manga_file)
            session.commit()
            session.refresh(manga_file)
            return manga_file

    def get_file(self, file_id: int) -> Optional[MangaFile]:
        """按主键查询 PDF 文件记录

        Args:
            file_id: 文件记录ID

        Returns:
            Optional[MangaFile]: 文件记录，不存在时返回 None
        """
        with self._get_session() as session:
            return session.get(MangaFile, file_id)

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

    def list_verifiable_files(self) -> List[MangaFile]:
        """查询参与校验的 PDF 文件记录（排除正在删除或已删除）。"""
        statuses = ("ready", "missing", "corrupted", "invalid_path")
        with self._get_session() as session:
            stmt = (
                select(MangaFile)
                .where(MangaFile.status.in_(statuses))
                .order_by(MangaFile.id)
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
            manga_file.updated_at = utc_now()
            session.commit()
            return True

    def apply_file_verification(  # pylint: disable=too-many-arguments
        self,
        file_id: int,
        status: str,
        file_size_bytes: int,
        file_mtime: Optional[datetime],
        sha256: Optional[str],
        verified_at: Optional[datetime],
    ) -> bool:
        """写入单次文件校验结果，返回是否找到目标文件。

        文件读取与哈希必须在调用本方法前完成，事务内不做文件 I/O。
        """
        if status not in _VALID_FILE_STATUSES:
            raise ValueError(f"不支持的文件状态: {status}")

        with self._get_session() as session:
            manga_file = session.get(MangaFile, file_id)
            if manga_file is None:
                return False
            manga_file.status = status
            manga_file.file_size_bytes = file_size_bytes
            manga_file.file_mtime = file_mtime
            manga_file.sha256 = sha256
            manga_file.last_verified_at = verified_at
            manga_file.updated_at = utc_now()
            # 校验通过且文件恢复时同步恢复漫画状态，避免文件正常但漫画仍标记缺失
            if status == "ready":
                manga = session.get(Manga, manga_file.manga_id)
                if manga is not None and manga.status == "missing_file":
                    manga.status = "downloaded"
                    manga.updated_at = utc_now()
            session.commit()
            return True

    def mark_manga_missing(self, manga_id: str) -> bool:
        """将漫画及其文件标记为缺失，不删除数据库记录。"""
        with self._get_session() as session:
            manga = session.get(Manga, manga_id)
            if manga is None:
                return False
            manga.status = "missing_file"
            manga.updated_at = utc_now()
            for manga_file in manga.files:
                manga_file.status = "missing"
                manga_file.updated_at = utc_now()
            session.commit()
            return True

    def mark_manga_deleting(self, manga_id: str) -> bool:
        """将漫画关联文件标记为删除中，表示删除流程已开始。

        删除流程先标记 deleting 再执行磁盘删除，便于并发方识别
        正在被删除的文件；标记不删除任何数据库记录。
        """
        with self._get_session() as session:
            manga = session.get(Manga, manga_id)
            if manga is None:
                return False
            for manga_file in manga.files:
                manga_file.status = "deleting"
                manga_file.updated_at = utc_now()
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
