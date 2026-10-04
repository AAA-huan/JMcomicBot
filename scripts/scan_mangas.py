"""漫画扫描入库脚本

扫描漫画下载目录内已下载的漫画PDF文件，将元数据与文件记录同步到SQLite数据库。

用法:
    uv run python scripts/scan_mangas.py              # 扫描并写入数据库
    uv run python scripts/scan_mangas.py --dry-run    # 仅预览将入库的内容，不写入
    uv run python scripts/scan_mangas.py --enrich     # 扫描后联网补全漫画详情与站点章节/页数
"""

from pathlib import Path

import argparse
import sys

# 直接运行时项目根不在 sys.path，先注入以便导入 src 包；包方式导入同样安全
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# pylint: disable=wrong-import-position
from src.config.manager import ConfigManager
from src.database.database import DatabaseManager
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
from src.service.scan_service import ScanRunResult, ScanService


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
        help="扫描后联网补全漫画详情与站点章节/页数",
    )
    parser.add_argument(
        "--read-pages", action="store_true", help="读取本地 PDF 实际页数，不渲染图片"
    )
    parser.add_argument(
        "--check-chapters",
        action="store_true",
        help="逐章查询在线图片数，需同时启用 --enrich",
    )
    args = parser.parse_args()
    if args.check_chapters and not args.enrich:
        parser.error("--check-chapters 需要同时启用 --enrich")
    return args


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
    if args.enrich and args.dry_run:
        logger.warning(
            "--enrich 与 --dry-run 同时使用时，联网补全仍会写入 entry（不入库）"
        )

    db_manager = DatabaseManager(db_path=db_path)
    db_manager.init_db()
    # 扫描入库流程与 WebUI 维护接口共用 ScanService，下载根目录必须传入
    scan_service = ScanService(
        MangaRepository(db_manager, download_root=download_path),
        MangaTagRepository(db_manager),
        ScanRecordRepository(db_manager),
        OperationTaskService(
            OperationTaskRepository(db_manager),
            TaskEventRepository(db_manager),
            AuditEventRepository(db_manager),
        ),
        download_root=download_path,
    )

    try:
        result = scan_service.run(
            context=OperationContext.system(),
            dry_run=args.dry_run,
            enrich=args.enrich,
            read_pages=args.read_pages,
            check_chapters=args.check_chapters,
        )
        _print_result(result)
    except FileNotFoundError as error:
        logger.error(str(error))
        sys.exit(1)
    except Exception as error:  # pylint: disable=broad-exception-caught
        logger.error(f"扫描失败: {error}")
        sys.exit(1)
    finally:
        db_manager.close()


def _print_result(result: ScanRunResult) -> None:
    """打印扫描同步结果统计

    Args:
        result: 扫描服务返回的结果对象
    """
    mode_desc = "预览：将新增" if result.dry_run else "完成：新增"
    lines = [
        f"📊 扫描同步{mode_desc}",
        f"  扫描到 PDF 文件: {result.scanned_files} 个",
        f"  聚合漫画: {result.manga_count} 本",
        f"  新增: {result.new_count} 本",
        f"  更新: {result.updated_count} 本，无需更新: {result.unchanged_count} 本",
        f"  重复文件漫画: {result.duplicate_count} 本，跳过: {result.skipped_count} 本",
        f"  联网详情成功/失败: {result.enrich_succeeded}/{result.enrich_failed}",
        f"  PDF 页数读取失败: {result.page_read_failed}，章节检查失败: {result.chapter_errors}",
    ]
    if result.dry_run:
        lines.append(f"  待清理残留: {result.pending_cleanup_count} 条")
    else:
        lines.append(f"  标记缺失: {result.marked_missing_count} 条")
    logger.info("\n".join(lines))
    for detail in result.details:
        logger.info(f"漫画 {detail['manga_id']}，最终文件: {detail['file']}")
        if result.dry_run:
            for change in detail["changes"]:
                logger.info(
                    f"  {change['label']}: {change['old']} → {change['new']}（{change['source']}）"
                )
        if detail["error"]:
            logger.error(f"  处理失败: {detail['error']}")
        for warning in detail["warnings"]:
            logger.warning(f"  {warning}")


if __name__ == "__main__":
    main()
