"""漫画资料修复应用服务，执行孤儿记录清理。"""

from dataclasses import dataclass
from typing import Optional

from src.database.repositories import MangaRepository, MangaTagRepository
from src.service.contracts import TaskService
from src.service.operation_context import OperationContext
from src.utils.manga_scanner import scan_download_dir


@dataclass(frozen=True)
class RepairDiff:
    """修复差异清单，供执行前预览与确认。"""

    orphan_manga_ids: tuple[str, ...]
    orphan_tag_names: tuple[str, ...]


class RepairService:
    """基于磁盘扫描差异执行孤儿清理的修复服务。

    repair 只做孤儿清理（标记缺失漫画 + 删除孤儿标签），不做补登；
    磁盘新文件的补登归扫描任务。任务、事件与审计由 operation_task_service
    统一记录（library.repair_*）。
    """

    def __init__(
        self,
        manga_repo: MangaRepository,
        tag_repo: MangaTagRepository,
        operation_task_service: TaskService,
    ) -> None:
        self.manga_repo = manga_repo
        self.tag_repo = tag_repo
        self.operation_task_service = operation_task_service

    def preview(self, download_path: str) -> RepairDiff:
        """扫描数据库与磁盘差异，返回待修复清单且不写入任何数据。"""
        disk_ids = self._scan_disk_ids(download_path)
        db_ids = {manga.id for manga in self.manga_repo.get_all()}
        return RepairDiff(
            orphan_manga_ids=tuple(sorted(db_ids - disk_ids)),
            orphan_tag_names=tuple(self.tag_repo.list_orphan_tags()),
        )

    def repair(
        self,
        download_path: str,
        context: Optional[OperationContext] = None,
    ) -> int:
        """执行孤儿清理，返回处理的孤儿数量。"""
        operation_context = context or OperationContext.system()
        task = self.operation_task_service.create("repair", operation_context)
        self.operation_task_service.start(task.id, "repairing")
        try:
            diff = self.preview(download_path)
            for manga_id in diff.orphan_manga_ids:
                self.manga_repo.mark_manga_missing(manga_id)
            cleaned_tags = self.tag_repo.delete_orphan_tags()
            cleaned_count = len(diff.orphan_manga_ids) + cleaned_tags
            self.operation_task_service.succeed(
                task.id,
                metadata={"cleaned_count": cleaned_count},
                context=operation_context,
            )
            return cleaned_count
        except Exception as error:
            self.operation_task_service.fail(
                task.id,
                "repair_failed",
                type(error).__name__,
                context=operation_context,
            )
            raise

    @staticmethod
    def _scan_disk_ids(download_path: str) -> set[str]:
        """扫描下载目录顶层的 PDF，返回漫画 ID 集合。"""
        entries = scan_download_dir(download_path)
        return {entry.manga_id for entry in entries}
