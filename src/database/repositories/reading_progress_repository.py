"""PDF 阅读进度仓储，负责阅读位置的读写与最近阅读列表。"""

# 各仓储按资源定义查询参数，不要求抽象入口的可变参数签名。
# pylint: disable=arguments-differ

from datetime import datetime
from typing import List, Optional

from sqlalchemy import delete, select

from src.database.models import ReadingProgress, utc_now

from ._base import BaseRepository


class ReadingProgressRepository(BaseRepository):
    """阅读进度仓储，按 PDF 文件维护当前阅读位置。"""

    def get(self, manga_file_id: int) -> Optional[ReadingProgress]:
        """按 PDF 文件ID查询阅读进度。"""
        with self._get_session() as session:
            return session.get(ReadingProgress, manga_file_id)

    def list(self, page: int = 1, page_size: int = 50) -> List[ReadingProgress]:
        """按更新时间倒序分页查询阅读进度。"""
        with self._get_session() as session:
            statement = (
                select(ReadingProgress)
                .order_by(
                    ReadingProgress.updated_at.desc(), ReadingProgress.manga_file_id
                )
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            return list(session.scalars(statement).all())

    def list_recent(self, limit: int = 20) -> List[ReadingProgress]:
        """查询最近阅读的进度记录，供 WebUI「继续阅读」使用。"""
        if limit <= 0:
            raise ValueError("最近阅读数量必须大于 0")
        with self._get_session() as session:
            statement = (
                select(ReadingProgress)
                .order_by(
                    ReadingProgress.updated_at.desc(), ReadingProgress.manga_file_id
                )
                .limit(limit)
            )
            return list(session.scalars(statement).all())

    def upsert(
        self,
        manga_file_id: int,
        page_number: int,
        page_count: int,
        percent: float,
        updated_at: Optional[datetime] = None,
    ) -> ReadingProgress:
        """插入或更新阅读进度；页码范围校验由服务层负责。"""
        now = updated_at or utc_now()
        with self._get_session() as session:
            progress = session.get(ReadingProgress, manga_file_id)
            if progress is None:
                progress = ReadingProgress(manga_file_id=manga_file_id)
                session.add(progress)
            progress.page_number = page_number
            progress.page_count = page_count
            progress.percent = percent
            progress.updated_at = now
            session.commit()
            session.refresh(progress)
            return progress

    def delete_for_file(self, manga_file_id: int) -> bool:
        """删除指定 PDF 的阅读进度，返回是否删除了记录。"""
        with self._get_session() as session:
            result = session.execute(
                delete(ReadingProgress).where(
                    ReadingProgress.manga_file_id == manga_file_id
                )
            )
            session.commit()
            return bool(result.rowcount)
