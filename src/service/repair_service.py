"""漫画资料修复应用服务，执行孤儿记录清理。"""

from typing import Optional

from src.database.repositories import MangaRepository, MangaTagRepository
from src.service.contracts import TaskService
from src.service.operation_context import OperationContext
from src.utils.manga_scanner import scan_download_dir


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
            cleaned_count = self._repair(download_path)
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

    def _repair(self, download_path: str) -> int:
        """标记孤儿漫画为缺失，并删除无关联的孤儿标签。"""
        disk_ids = self._scan_disk_ids(download_path)
        db_ids = {manga.id for manga in self.manga_repo.get_all()}
        orphan_manga_ids = db_ids - disk_ids
        for manga_id in sorted(orphan_manga_ids):
            self.manga_repo.mark_manga_missing(manga_id)
        cleaned_tags = self.tag_repo.delete_orphan_tags()
        return len(orphan_manga_ids) + cleaned_tags

    @staticmethod
    def _scan_disk_ids(download_path: str) -> set[str]:
        """扫描下载目录顶层的 PDF，返回漫画 ID 集合。"""
        entries = scan_download_dir(download_path)
        return {entry.manga_id for entry in entries}
