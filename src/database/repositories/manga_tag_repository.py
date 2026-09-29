"""漫画标签仓储，负责按标签查询对应漫画的 PDF 文件记录"""

import os
from typing import List, Optional, Set

from sqlalchemy import delete, select

from src.database.database import DatabaseManager
from src.database.models import Manga, MangaTag, Tag
from src.database.repositories._base import BaseRepository

# pylint: disable=arguments-differ


class MangaTagRepository(BaseRepository):
    """漫画标签仓储，提供标签与漫画PDF文件之间关系的增删查"""

    def __init__(self, db_manager: DatabaseManager) -> None:
        super().__init__(db_manager)

    def get(self, record_id: int) -> Optional[MangaTag]:
        """按主键查询单条标签记录

        Args:
            record_id: 记录主键 ID

        Returns:
            Optional[MangaTag]: 标签记录，不存在时返回 None
        """
        with self._get_session() as session:
            return session.get(MangaTag, record_id)

    def list(self, page: int = 1, page_size: int = 50) -> List[MangaTag]:
        """分页查询标签记录

        Args:
            page: 页码，从1开始
            page_size: 每页数量

        Returns:
            List[MangaTag]: 标签记录列表
        """
        with self._get_session() as session:
            stmt = (
                select(MangaTag)
                .order_by(MangaTag.tag, MangaTag.manga_id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            return list(session.scalars(stmt).all())

    def add(self, tag: str, manga_id: str, pdf_name: str) -> None:
        """添加一条标签-漫画关系记录（已存在时忽略）

        Args:
            tag: 标签名
            manga_id: 漫画ID
            pdf_name: 漫画PDF文件名
        """
        with self._get_session() as session:
            normalized_name = " ".join(tag.split()).casefold()
            tag_definition = session.scalar(
                select(Tag).where(Tag.normalized_name == normalized_name)
            )
            if tag_definition is None:
                tag_definition = Tag(name=tag.strip(), normalized_name=normalized_name)
                session.add(tag_definition)
                session.flush()
            existing = session.scalar(
                select(MangaTag).where(
                    MangaTag.tag_id == tag_definition.id,
                    MangaTag.manga_id == manga_id,
                )
            )
            if existing is None:
                session.add(
                    MangaTag(
                        tag=tag,
                        tag_id=tag_definition.id,
                        manga_id=manga_id,
                        pdf_name=pdf_name,
                    )
                )
            else:
                existing.tag_id = tag_definition.id
            session.commit()

    def add_for_existing_manga(self, tag: str, manga_id: str, pdf_name: str) -> None:
        """仅为已存在的漫画写入标签关系。"""
        with self._get_session() as session:
            if session.get(Manga, manga_id) is None:
                raise ValueError(f"漫画记录不存在，无法写入标签: {manga_id}")
        self.add(tag, manga_id, pdf_name)

    def get_by_tag(self, tag: str) -> List[MangaTag]:
        """按标签查询其下的漫画PDF记录

        Args:
            tag: 标签名

        Returns:
            List[MangaTag]: 标签对应的漫画记录列表
        """
        with self._get_session() as session:
            normalized_name = " ".join(tag.split()).casefold()
            stmt = (
                select(MangaTag)
                .join(Tag, MangaTag.tag_id == Tag.id)
                .where(Tag.normalized_name == normalized_name)
                .order_by(MangaTag.pdf_name)
            )
            return list(session.scalars(stmt).all())

    def list_all_tags(self) -> List[str]:
        """列出数据库中所有标签名（去重）"""
        with self._get_session() as session:
            rows = session.execute(select(Tag.name).order_by(Tag.normalized_name)).all()
            return [tag for (tag,) in rows]

    def delete_by_manga_id(self, manga_id: str) -> int:
        """删除指定漫画的全部标签记录

        Args:
            manga_id: 漫画ID

        Returns:
            int: 删除的记录数量
        """
        with self._get_session() as session:
            result = session.execute(
                delete(MangaTag).where(MangaTag.manga_id == manga_id)
            )
            session.commit()
            return result.rowcount or 0

    def get_manga_ids_by_tags(self, tags: List[str]) -> Set[str]:
        """查询同时包含全部指定标签的漫画ID集合（多标签联合查询，取交集）

        Args:
            tags: 标签名列表

        Returns:
            Set[str]: 同时命中所有标签的漫画ID集合
        """
        if not tags:
            return set()

        manga_ids: Set[str] = {record.manga_id for record in self.get_by_tag(tags[0])}
        for tag in tags[1:]:
            tagged_ids = {record.manga_id for record in self.get_by_tag(tag)}
            manga_ids &= tagged_ids
            if not manga_ids:
                break
        return manga_ids

    def sync_from_manga(self) -> int:
        """将漫画表中的标签批量回填到标签表（幂等）

        遍历漫画记录，拆分其 tags 字段（逗号分隔），并结合该漫画的 PDF 文件记录，
        将缺失的 标签-漫画-pdf名 关系补充到标签表。

        Returns:
            int: 本次新增的标签关系记录数量
        """
        added_count = 0
        with self._get_session() as session:
            mangas = list(session.scalars(select(Manga)).all())
            for manga in mangas:
                tags = [tag.strip() for tag in manga.tags.split(",") if tag.strip()]
                if not tags:
                    continue
                pdf_names = [
                    os.path.basename(file_entry.file_path) for file_entry in manga.files
                ]
                pdf_name = pdf_names[0] if pdf_names else ""
                for tag in tags:
                    existing = session.scalar(
                        select(MangaTag).where(
                            MangaTag.tag == tag, MangaTag.manga_id == manga.id
                        )
                    )
                    if existing is None:
                        normalized_name = " ".join(tag.split()).casefold()
                        tag_definition = session.scalar(
                            select(Tag).where(
                                Tag.normalized_name == normalized_name
                            )
                        )
                        if tag_definition is None:
                            tag_definition = Tag(
                                name=tag,
                                normalized_name=normalized_name,
                            )
                            session.add(tag_definition)
                            session.flush()
                        session.add(
                            MangaTag(
                                tag=tag,
                                tag_id=tag_definition.id,
                                manga_id=manga.id,
                                pdf_name=pdf_name,
                            )
                        )
                        added_count += 1
            session.commit()
        return added_count
