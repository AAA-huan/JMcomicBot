"""WebUI 漫画与任务只读查询服务。"""

from dataclasses import dataclass
from datetime import datetime
from math import ceil
from typing import Generic, Optional, TypeVar

from src.database.models import Manga, MangaFile, OperationTask
from src.database.repositories import (
    MangaRepository,
    MangaTagRepository,
    OperationTaskRepository,
)

T = TypeVar("T")


@dataclass(frozen=True)
class PageResult(Generic[T]):
    """统一分页结果。"""

    items: tuple[T, ...]
    page: int
    page_size: int
    total: int
    pages: int


@dataclass(frozen=True)
class MangaFileResult:
    """可安全返回浏览器的漫画文件摘要。"""

    id: int
    display_name: str
    file_size_bytes: int
    page_count: int
    status: str


@dataclass(frozen=True)
class MangaResult:  # pylint: disable=too-many-instance-attributes
    """可安全返回浏览器的漫画详情。"""

    id: str
    title: str
    author: str
    description: Optional[str]
    chapter_count: int
    page_count: int
    status: str
    downloaded_at: datetime
    updated_at: datetime
    tags: tuple[str, ...]
    files: tuple[MangaFileResult, ...]


@dataclass(frozen=True)
class OperationTaskResult:  # pylint: disable=too-many-instance-attributes
    """可安全返回浏览器的持久化任务详情。"""

    id: str
    task_type: str
    source: str
    status: str
    stage: str
    progress: Optional[int]
    manga_id: Optional[str]
    summary: str
    error_code: Optional[str]
    error_message: Optional[str]
    created_at: datetime
    started_at: Optional[datetime]
    updated_at: datetime
    finished_at: Optional[datetime]


class MangaQueryService:
    """提供漫画分页和详情只读查询。"""

    def __init__(
        self, manga_repository: MangaRepository, tag_repository: MangaTagRepository
    ) -> None:
        self.manga_repository = manga_repository
        self.tag_repository = tag_repository

    def _to_result(self, manga: Manga) -> MangaResult:
        return MangaResult(
            id=manga.id,
            title=manga.title,
            author=manga.author,
            description=manga.description,
            chapter_count=manga.chapter_count,
            page_count=manga.page_count,
            status=manga.status,
            downloaded_at=manga.downloaded_at,
            updated_at=manga.updated_at,
            tags=tuple(self.tag_repository.list_for_manga(manga.id)),
            files=tuple(self._file_to_result(item) for item in manga.files),
        )

    @staticmethod
    def _file_to_result(manga_file: MangaFile) -> MangaFileResult:
        return MangaFileResult(
            id=manga_file.id,
            display_name=manga_file.display_name,
            file_size_bytes=manga_file.file_size_bytes,
            page_count=manga_file.page_count,
            status=manga_file.status,
        )

    def list(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        page: int,
        page_size: int,
        search: Optional[str],
        status: Optional[str],
        tag: Optional[str],
        sort: str,
    ) -> PageResult[MangaResult]:
        """按受控条件分页查询漫画。"""
        mangas, total = self.manga_repository.search(
            page, page_size, search, status, tag, sort
        )
        return PageResult(
            items=tuple(self._to_result(manga) for manga in mangas),
            page=page,
            page_size=page_size,
            total=total,
            pages=ceil(total / page_size),
        )

    def get(self, manga_id: str) -> Optional[MangaResult]:
        """按漫画 ID 查询公开详情。"""
        manga = self.manga_repository.get(manga_id)
        return self._to_result(manga) if manga is not None else None


class TaskQueryService:
    """提供操作任务分页和详情只读查询。"""

    def __init__(self, task_repository: OperationTaskRepository) -> None:
        self.task_repository = task_repository

    @staticmethod
    def _to_result(task: OperationTask) -> OperationTaskResult:
        return OperationTaskResult(
            id=task.id,
            task_type=task.task_type,
            source=task.source,
            status=task.status,
            stage=task.stage,
            progress=task.progress,
            manga_id=task.manga_id,
            summary=task.summary,
            error_code=task.error_code,
            error_message=task.error_message,
            created_at=task.created_at,
            started_at=task.started_at,
            updated_at=task.updated_at,
            finished_at=task.finished_at,
        )

    def list(
        self,
        page: int,
        page_size: int,
        task_type: Optional[str],
        status: Optional[str],
        manga_id: Optional[str],
    ) -> PageResult[OperationTaskResult]:
        """按受控条件分页查询任务。"""
        tasks, total = self.task_repository.search(
            page, page_size, task_type, status, manga_id
        )
        return PageResult(
            items=tuple(self._to_result(task) for task in tasks),
            page=page,
            page_size=page_size,
            total=total,
            pages=ceil(total / page_size),
        )

    def get(self, task_id: str) -> Optional[OperationTaskResult]:
        """按任务 ID 查询公开详情。"""
        task = self.task_repository.get(task_id)
        return self._to_result(task) if task is not None else None
