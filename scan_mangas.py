"""漫画扫描入库脚本

扫描漫画下载目录内已下载的漫画PDF文件，将元数据与文件记录同步到SQLite数据库。

用法:
    uv run python scan_mangas.py              # 扫描并写入数据库
    uv run python scan_mangas.py --dry-run    # 仅预览将入库的内容，不写入
    uv run python scan_mangas.py --enrich     # 扫描后联网补全作者/标签等元数据
"""

import argparse
import sys

from src.config.manager import ConfigManager
from src.database.database import DatabaseManager
from src.database.models import ScanRecord
from src.database.repositories import (
    AuditEventRepository,
    MangaRepository,
    MangaTagRepository,
    OperationTaskRepository,
    ScanRecordRepository,
    TaskEventRepository,
)
from src.logging.logger_config import logger
from src.service import OperationContext, OperationTaskService
from src.utils.manga_scanner import (
    DOWNLOAD_PATH_LABEL,
    ScanResult,
    enrich_metadata_from_jmcomic,
    scan_download_dir,
    sync_scanned_to_db,
)


def parse_args() -> argparse.Namespace:
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description="扫描漫画下载目录并将元数据写入数据库")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅预览将入库的漫画，不实际写入数据库",
    )
    parser.add_argument(
        "--enrich",
        action="store_true",
        help="扫描后联网补全作者/标签等元数据",
    )
    return parser.parse_args()


def record_scan_result(
    scan_record_repo: ScanRecordRepository, task_id: str, result: ScanResult
) -> ScanRecord:
    """将扫描结果统计写入 scan_record，path_label 只保存配置名称。"""
    return scan_record_repo.create(
        task_id=task_id,
        task_type="scan",
        path_label=DOWNLOAD_PATH_LABEL,
        file_count=result.scanned_files,
        new_count=result.new_count,
        updated_count=result.updated_count,
        missing_count=result.marked_missing_count,
    )


def main() -> None:
    """扫描漫画并将元数据同步到数据库的主入口"""
    args = parse_args()

    # 加载配置，读取下载路径与数据库路径
    config_manager = ConfigManager()
    config_manager.load_config()
    download_path = str(config_manager.get("MANGA_DOWNLOAD_PATH"))
    db_path = str(config_manager.get("DB_PATH"))

    logger.info(f"下载目录: {download_path}")
    if args.dry_run:
        logger.info("当前为预览模式(--dry-run)，不会写入数据库")

    try:
        entries = scan_download_dir(download_path)
    except FileNotFoundError as e:
        logger.error(str(e))
        sys.exit(1)

    if not entries:
        logger.info("没有扫描到漫画，无需同步")
        sys.exit(0)

    # 可选：联网补全作者/标签等元数据
    if args.enrich:
        if args.dry_run:
            logger.warning(
                "--enrich 与 --dry-run 同时使用时，联网补全仍会写入 entry（不入库）"
            )
        logger.info("正在联网补全漫画元数据，请稍候……")
        enriched = enrich_metadata_from_jmcomic(entries)
        logger.info(f"联网补全元数据完成：成功补全 {enriched} 个漫画")

    # 初始化数据库并同步
    db_manager = DatabaseManager(db_path=db_path)
    db_manager.init_db()
    repo = MangaRepository(db_manager)
    tag_repo = MangaTagRepository(db_manager)
    scan_record_repo = ScanRecordRepository(db_manager)
    task_service = OperationTaskService(
        OperationTaskRepository(db_manager),
        TaskEventRepository(db_manager),
        AuditEventRepository(db_manager),
    )
    operation_context = OperationContext.system()
    operation_task = (
        None if args.dry_run else task_service.create("scan", operation_context)
    )

    try:
        if operation_task is not None:
            task_service.start(operation_task.id, "scanning")
        result = sync_scanned_to_db(
            repo, entries, dry_run=args.dry_run, tag_repo=tag_repo
        )
        if operation_task is not None:
            # 正式统计落表：path_label 只保存配置名称，不保存绝对路径
            record_scan_result(scan_record_repo, operation_task.id, result)
            task_service.succeed(
                operation_task.id,
                metadata={
                    "file_count": result.scanned_files,
                    "new_count": result.new_count,
                    "updated_count": result.updated_count,
                    "missing_count": result.marked_missing_count,
                },
                context=operation_context,
            )
        _print_result(result, dry_run=args.dry_run)
    except Exception as error:
        if operation_task is not None:
            task_service.fail(
                operation_task.id,
                "scan_failed",
                type(error).__name__,
                context=operation_context,
            )
        raise
    finally:
        db_manager.close()


def _print_result(result, dry_run: bool) -> None:
    """打印扫描同步结果统计

    Args:
        result: 扫描同步结果
        dry_run: 是否为预览模式
    """
    mode_desc = "预览：将新增" if dry_run else "完成：新增"
    lines = [
        f"📊 扫描同步{mode_desc}",
        f"  扫描到 PDF 文件: {result.scanned_files} 个",
        f"  聚合漫画: {result.manga_count} 本",
        f"  新增: {result.new_count} 本",
        f"  更新: {result.updated_count} 本",
    ]
    if dry_run:
        lines.append(f"  待清理残留: {result.pending_cleanup_count} 条")
    else:
        lines.append(f"  标记缺失: {result.marked_missing_count} 条")
    logger.info("\n".join(lines))


if __name__ == "__main__":
    main()
