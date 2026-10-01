"""目录扫描应用服务，供维护脚本与 WebUI 共用扫描入库流程。"""

from dataclasses import dataclass
from typing import Optional

from src.database.repositories import (
    MangaRepository,
    MangaTagRepository,
    ScanRecordRepository,
)
from src.logging.logger_config import logger
from src.service.contracts import TaskService
from src.service.operation_context import OperationContext
from src.utils.manga_scanner import (
    enrich_metadata_from_jmcomic,
    record_scan_result,
    scan_download_dir,
    sync_scanned_to_db,
)


@dataclass(frozen=True)
class ScanRunResult:  # pylint: disable=too-many-instance-attributes
    """扫描运行的渠道无关结果。"""

    task_id: Optional[str]
    scanned_files: int
    manga_count: int
    new_count: int
    updated_count: int
    marked_missing_count: int
    pending_cleanup_count: int
    dry_run: bool


class ScanService:  # pylint: disable=too-few-public-methods
    """执行下载目录扫描、入库同步与扫描统计记录。"""

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

    def run(
        self,
        context: Optional[OperationContext] = None,
        dry_run: bool = False,
        enrich: bool = False,
    ) -> ScanRunResult:
        """扫描下载目录并同步入库；dry_run 只预览不创建任务也不写库。

        Args:
            context: 操作来源上下文，缺省按系统来源记录
            dry_run: 仅统计将入库的内容，不创建任务、不写数据库
            enrich: 扫描后联网补全作者与标签（WebUI 第一版不开放）

        Returns:
            ScanRunResult: 扫描与同步统计

        Raises:
            FileNotFoundError: 下载目录不存在时
        """
        operation_context = context or OperationContext.system()
        task = (
            None
            if dry_run
            else self.operation_task_service.create("scan", operation_context)
        )
        task_id = task.id if task is not None else None
        try:
            if task_id is not None:
                self.operation_task_service.start(task_id, "scanning")
            entries = scan_download_dir(self.download_root)
            if not entries:
                # 空目录不执行缺失标记：目录为空可能是配置错误，交由 repair 处理孤儿
                logger.info("没有扫描到漫画，无需同步")
                if task_id is not None:
                    self.operation_task_service.succeed(
                        task_id,
                        metadata={"file_count": 0},
                        context=operation_context,
                    )
                return ScanRunResult(
                    task_id=task_id,
                    scanned_files=0,
                    manga_count=0,
                    new_count=0,
                    updated_count=0,
                    marked_missing_count=0,
                    pending_cleanup_count=0,
                    dry_run=dry_run,
                )
            if enrich:
                logger.info("正在联网补全漫画元数据，请稍候……")
                enriched_count = enrich_metadata_from_jmcomic(entries)
                logger.info(f"联网补全元数据完成：成功补全 {enriched_count} 个漫画")
            result = sync_scanned_to_db(
                self.manga_repo, entries, dry_run=dry_run, tag_repo=self.tag_repo
            )
            if task_id is not None:
                # 正式统计落表：path_label 只保存配置名称，不保存绝对路径
                record_scan_result(self.scan_record_repo, task_id, result)
                self.operation_task_service.succeed(
                    task_id,
                    metadata={
                        "file_count": result.scanned_files,
                        "new_count": result.new_count,
                        "updated_count": result.updated_count,
                        "missing_count": result.marked_missing_count,
                    },
                    context=operation_context,
                )
            return ScanRunResult(
                task_id=task_id,
                scanned_files=result.scanned_files,
                manga_count=result.manga_count,
                new_count=result.new_count,
                updated_count=result.updated_count,
                marked_missing_count=result.marked_missing_count,
                pending_cleanup_count=result.pending_cleanup_count,
                dry_run=dry_run,
            )
        except Exception as error:
            if task_id is not None:
                self.operation_task_service.fail(
                    task_id,
                    "scan_failed",
                    type(error).__name__,
                    context=operation_context,
                )
            raise
