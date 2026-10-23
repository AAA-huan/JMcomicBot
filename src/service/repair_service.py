"""漫画资料修复应用服务，执行孤儿记录清理。"""

from dataclasses import dataclass
from typing import Optional

from src.database.repositories import (
    MangaRepository,
    MangaTagRepository,
    ScanRecordRepository,
)
from src.service.contracts import TaskService
from src.service.operation_context import OperationContext
from src.utils.manga_scanner import DOWNLOAD_PATH_LABEL, scan_download_dir


@dataclass(frozen=True)
class RepairDiff:
    """修复差异清单，供执行前预览与确认。"""

    orphan_manga_ids: tuple[str, ...]
    orphan_tag_names: tuple[str, ...]


@dataclass(frozen=True)
class RepairResult:
    """修复执行结果，记录已处理的孤儿漫画与标签。"""

    cleaned_count: int
    processed_manga_ids: list[str]
    removed_tag_names: list[str]


class RepairService:
    """基于磁盘扫描差异执行孤儿清理的修复服务。

    repair 只做孤儿清理（标记缺失漫画 + 删除孤儿标签），不做补登；
    磁盘新文件的补登归扫描任务。任务、事件与审计由 operation_task_service
    统一记录（library.repair_*）。
    """

    def __init__(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        manga_repo: MangaRepository,
        tag_repo: MangaTagRepository,
        scan_record_repo: ScanRecordRepository,
        operation_task_service: TaskService,
        download_root: str,
    ) -> None:
        self.manga_repo = manga_repo
        self.tag_repo = tag_repo
        self.scan_record_repo = scan_record_repo
        self.operation_task_service = operation_task_service
        self.download_root = download_root

    def preview(self) -> RepairDiff:
        """扫描数据库与磁盘差异，返回待修复清单且不写入任何数据。"""
        disk_ids = self._scan_disk_ids(self.download_root)
        # favorited 漫画尚未下载，预期没有文件，不参与孤儿判定
        db_ids = {manga.id for manga in self.manga_repo.list_with_expected_files()}
        return RepairDiff(
            orphan_manga_ids=tuple(sorted(db_ids - disk_ids)),
            orphan_tag_names=tuple(self.tag_repo.list_orphan_tags()),
        )

    def repair(self, context: Optional[OperationContext] = None) -> RepairResult:
        """执行孤儿清理，返回清理数量与实际处理的孤儿项。"""
        operation_context = context or OperationContext.system()
        task = self.operation_task_service.create("repair", operation_context)
        self.operation_task_service.start(task.id, "repairing")
        try:
            diff = self.preview()
            processed_manga_ids = list(diff.orphan_manga_ids)
            removed_tag_names = list(diff.orphan_tag_names)
            for manga_id in processed_manga_ids:
                self.manga_repo.mark_manga_missing(manga_id)
            cleaned_tags = self.tag_repo.delete_orphan_tags()
            cleaned_count = len(processed_manga_ids) + cleaned_tags
            # 正式统计落表：missing_count 为标记缺失的漫画数，
            # repaired_count 为清理条目总数（孤儿漫画 + 孤儿标签）
            self.scan_record_repo.create(
                task_id=task.id,
                task_type="repair",
                path_label=DOWNLOAD_PATH_LABEL,
                missing_count=len(processed_manga_ids),
                repaired_count=cleaned_count,
            )
            self.operation_task_service.succeed(
                task.id,
                metadata={"cleaned_count": cleaned_count},
                context=operation_context,
            )
            return RepairResult(
                cleaned_count=cleaned_count,
                processed_manga_ids=processed_manga_ids,
                removed_tag_names=removed_tag_names,
            )
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
