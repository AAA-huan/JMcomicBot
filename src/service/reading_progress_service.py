"""阅读进度应用服务，校验页码并计算阅读百分比。"""

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from src.database.models import ReadingProgress
from src.database.repositories import MangaRepository, ReadingProgressRepository


class ReadingProgressFileNotFoundError(Exception):
    """PDF 文件记录不存在，无法读写阅读进度。"""


@dataclass(frozen=True)
class ReadingProgressView:
    """可安全返回浏览器的阅读进度视图。"""

    file_id: int
    page_number: int
    page_count: int
    percent: float
    updated_at: Optional[datetime]


class ReadingProgressService:
    """阅读进度服务，供 QQ 命令与 WebUI 共用。

    percent 一律由页码与总页数计算，不信任调用方传入的进度值。
    """

    def __init__(
        self,
        progress_repo: ReadingProgressRepository,
        manga_repository: MangaRepository,
    ) -> None:
        self.progress_repo = progress_repo
        self.manga_repository = manga_repository

    def get(self, manga_file_id: int) -> Optional[ReadingProgress]:
        """查询指定 PDF 的阅读进度记录。"""
        return self.progress_repo.get(manga_file_id)

    def get_view(self, manga_file_id: int) -> Optional[ReadingProgressView]:
        """查询阅读进度视图。

        文件记录不存在时返回 None；文件存在但尚无进度记录时返回默认
        视图（第 1 页、文件页数、0%），不创建无用记录。
        """
        manga_file = self.manga_repository.get_file(manga_file_id)
        if manga_file is None:
            return None
        progress = self.progress_repo.get(manga_file_id)
        if progress is None:
            return ReadingProgressView(
                file_id=manga_file_id,
                page_number=1,
                page_count=manga_file.page_count,
                percent=0.0,
                updated_at=None,
            )
        return self._to_view(progress)

    def update(
        self, manga_file_id: int, page_number: int, page_count: int
    ) -> ReadingProgress:
        """校验文件与页码范围并写入阅读进度。

        Args:
            manga_file_id: PDF 文件ID
            page_number: 当前页码，从 1 开始
            page_count: PDF 总页数，必须大于 0

        Returns:
            ReadingProgress: 已保存的阅读进度记录

        Raises:
            ReadingProgressFileNotFoundError: PDF 文件记录不存在
            ValueError: 页码或总页数非法
        """
        manga_file = self.manga_repository.get_file(manga_file_id)
        if manga_file is None:
            raise ReadingProgressFileNotFoundError(
                f"PDF文件记录不存在: {manga_file_id}"
            )
        if page_count <= 0:
            raise ValueError("PDF总页数必须大于 0")
        if not 1 <= page_number <= page_count:
            raise ValueError(f"页码必须位于 1 到 {page_count} 之间: {page_number}")
        progress = self.progress_repo.upsert(
            manga_file_id=manga_file_id,
            page_number=page_number,
            page_count=page_count,
            percent=page_number / page_count,
        )
        # 阅读器解析的实际页数纠正旧值，并同步漫画总页数。
        self.update_page_count(manga_file_id, page_count)
        return progress

    def update_page_count(self, manga_file_id: int, page_count: int) -> None:
        """仅同步 PDF 实际页数，不创建或覆盖阅读进度。"""
        if not self.manga_repository.update_page_count(manga_file_id, page_count):
            raise ReadingProgressFileNotFoundError(
                f"PDF文件记录不存在: {manga_file_id}"
            )

    def list_recent(self, limit: int = 20) -> List[ReadingProgress]:
        """查询最近阅读列表，为 WebUI「继续阅读」预留。"""
        return self.progress_repo.list_recent(limit)

    @staticmethod
    def _to_view(progress: ReadingProgress) -> ReadingProgressView:
        """把进度记录转换为接口层视图。"""
        return ReadingProgressView(
            file_id=progress.manga_file_id,
            page_number=progress.page_number,
            page_count=progress.page_count,
            percent=progress.percent,
            updated_at=progress.updated_at,
        )
