"""漫画资料修复脚本

扫描下载目录与数据库差异，标记孤儿漫画为缺失并删除无关联的孤儿标签。
修复前建议先使用 --dry-run 查看差异清单，确认后再执行。

用法:
    uv run python repair_mangas.py --dry-run   # 仅预览差异，不执行任何写入
    uv run python repair_mangas.py             # 确认后执行修复
"""

import argparse
import sys

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
from src.service import (
    OperationContext,
    OperationTaskService,
    RepairService,
)


def parse_args() -> argparse.Namespace:
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="修复漫画资料：标记孤儿漫画并删除孤儿标签"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅预览差异清单，不执行任何写入",
    )
    return parser.parse_args()


def main() -> None:
    """执行漫画资料修复的主入口"""
    args = parse_args()
    config_manager = ConfigManager()
    config_manager.load_config()
    download_path = str(config_manager.get("MANGA_DOWNLOAD_PATH"))
    db_path = str(config_manager.get("DB_PATH"))

    db_manager = DatabaseManager(db_path=db_path)
    db_manager.init_db()
    task_service = OperationTaskService(
        OperationTaskRepository(db_manager),
        TaskEventRepository(db_manager),
        AuditEventRepository(db_manager),
    )
    repair_service = RepairService(
        MangaRepository(db_manager, download_root=download_path),
        MangaTagRepository(db_manager),
        ScanRecordRepository(db_manager),
        task_service,
        download_root=download_path,
    )

    try:
        if args.dry_run:
            diff = repair_service.preview()
            logger.info(
                f"预览：孤儿漫画 {len(diff.orphan_manga_ids)} 个，"
                f"孤儿标签 {len(diff.orphan_tag_names)} 个"
            )
            for manga_id in diff.orphan_manga_ids:
                logger.info(f"  待标记缺失漫画: {manga_id}")
            for tag_name in diff.orphan_tag_names:
                logger.info(f"  待删除孤儿标签: {tag_name}")
            logger.info(
                "当前为预览模式，未执行任何写入；确认后可去掉 --dry-run 执行修复"
            )
            return
        cleaned_count = repair_service.repair(context=OperationContext.system())
        logger.info(f"修复完成：清理 {cleaned_count} 条孤儿记录")
    except Exception as error:
        logger.error(f"修复失败: {error}")
        sys.exit(1)
    finally:
        db_manager.close()


if __name__ == "__main__":
    main()
