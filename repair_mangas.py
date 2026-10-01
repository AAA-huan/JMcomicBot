"""漫画资料修复脚本

扫描下载目录与数据库差异，标记孤儿漫画为缺失并删除无关联的孤儿标签。

用法:
    uv run python repair_mangas.py
"""

import sys

from src.config.manager import ConfigManager
from src.database.database import DatabaseManager
from src.database.repositories import (
    AuditEventRepository,
    MangaRepository,
    MangaTagRepository,
    OperationTaskRepository,
    TaskEventRepository,
)
from src.logging.logger_config import logger
from src.service import (
    OperationContext,
    OperationTaskService,
    RepairService,
)


def main() -> None:
    """执行漫画资料修复的主入口"""
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
        MangaRepository(db_manager),
        MangaTagRepository(db_manager),
        task_service,
    )

    try:
        cleaned_count = repair_service.repair(
            download_path, context=OperationContext.system()
        )
        logger.info(f"修复完成：清理 {cleaned_count} 条孤儿记录")
    except Exception as error:
        logger.error(f"修复失败: {error}")
        sys.exit(1)
    finally:
        db_manager.close()


if __name__ == "__main__":
    main()
