"""漫画文件校验脚本

逐文件校验下载目录与数据库记录：路径安全、存在性、大小、修改时间与 SHA-256。
损坏文件只标记 corrupted，不自动删除或重新下载；删除走 delete 任务，
重新下载走 download 任务。

用法:
    uv run python verify_mangas.py                # 校验全部漫画文件
    uv run python verify_mangas.py --id 350234    # 仅校验指定漫画（可重复指定）
"""

import argparse
import sys

from src.config.manager import ConfigManager
from src.database.database import DatabaseManager
from src.database.repositories import (
    AuditEventRepository,
    MangaRepository,
    OperationTaskRepository,
    ScanRecordRepository,
    TaskEventRepository,
)
from src.logging.logger_config import logger
from src.service import OperationContext, OperationTaskService, VerifyService


def parse_args() -> argparse.Namespace:
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="校验漫画PDF文件的存在性、大小、修改时间与 SHA-256"
    )
    parser.add_argument(
        "--id",
        dest="manga_ids",
        action="append",
        default=None,
        help="仅校验指定漫画ID，可重复指定",
    )
    return parser.parse_args()


def main() -> None:
    """执行文件校验的主入口"""
    args = parse_args()
    config_manager = ConfigManager()
    config_manager.load_config()
    download_path = str(config_manager.get("MANGA_DOWNLOAD_PATH"))
    db_path = str(config_manager.get("DB_PATH"))

    db_manager = DatabaseManager(db_path=db_path)
    db_manager.init_db()
    try:
        verify_service = VerifyService(
            MangaRepository(db_manager, download_root=download_path),
            ScanRecordRepository(db_manager),
            OperationTaskService(
                OperationTaskRepository(db_manager),
                TaskEventRepository(db_manager),
                AuditEventRepository(db_manager),
            ),
            download_root=download_path,
        )
        result = verify_service.verify(
            args.manga_ids, context=OperationContext.system()
        )
        logger.info(
            "校验完成："
            f"文件 {result.file_count} 个，正常 {result.ready_count}，"
            f"缺失 {result.missing_count}，损坏 {result.corrupted_count}，"
            f"路径异常 {result.invalid_path_count}，读取错误 {result.error_count}"
        )
    except Exception as error:
        logger.error(f"校验失败: {error}")
        sys.exit(1)
    finally:
        db_manager.close()


if __name__ == "__main__":
    main()
