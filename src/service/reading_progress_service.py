"""阅读进度应用服务，校验页码并计算阅读百分比。"""

from typing import List, Optional

from src.database.models import ReadingProgress
from src.database.repositories import ReadingProgressRepository


class ReadingProgressService:
    """阅读进度服务，供 QQ 命令与 WebUI 共用。

    percent 一律由页码与总页数计算，不信任调用方传入的进度值。
    """

    def __init__(self, progress_repo: ReadingProgressRepository) -> None:
        self.progress_repo = progress_repo

    def get(self, manga_file_id: int) -> Optional[ReadingProgress]:
        """查询指定 PDF 的阅读进度。"""
        return self.progress_repo.get(manga_file_id)

    def update(
        self, manga_file_id: int, page_number: int, page_count: int
    ) -> ReadingProgress:
        """校验页码范围并写入阅读进度。

        Args:
            manga_file_id: PDF 文件ID
            page_number: 当前页码，从 1 开始
            page_count: PDF 总页数，必须大于 0

        Returns:
            ReadingProgress: 已保存的阅读进度记录
        """
        if page_count <= 0:
            raise ValueError("PDF总页数必须大于 0")
        if not 1 <= page_number <= page_count:
            raise ValueError(f"页码必须位于 1 到 {page_count} 之间: {page_number}")
        return self.progress_repo.upsert(
            manga_file_id=manga_file_id,
            page_number=page_number,
            page_count=page_count,
            percent=page_number / page_count,
        )

    def list_recent(self, limit: int = 20) -> List[ReadingProgress]:
        """查询最近阅读列表，为 WebUI「继续阅读」预留。"""
        return self.progress_repo.list_recent(limit)
