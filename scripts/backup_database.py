"""数据库备份脚本

使用 SQLite backup API 创建一致性备份，并写入 backup_record 与任务审计。
备份目录由 BACKUP_PATH 配置，默认 ./data/backups；迁移前的
main.db.pre-migration.bak 不属于 backup_record。

用法:
    uv run python scripts/backup_database.py
"""

from pathlib import Path

import sys

# 直接运行时项目根不在 sys.path，先注入以便导入 src 包；包方式导入同样安全
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# pylint: disable=wrong-import-position
from src.config.manager import ConfigManager
from src.database.database import DatabaseManager
from src.database.repositories import (
    AuditEventRepository,
    BackupRepository,
    OperationTaskRepository,
    TaskEventRepository,
)
from src.logging.logger_config import logger
from src.service import (
    DatabaseMaintenanceService,
    OperationContext,
    OperationTaskService,
)


def main() -> None:
    """执行一致性数据库备份的主入口"""
    config_manager = ConfigManager()
    config_manager.load_config()
    db_path = str(config_manager.get("DB_PATH"))
    backup_path = str(config_manager.get("BACKUP_PATH"))

    db_manager = DatabaseManager(db_path=db_path)
    db_manager.init_db()
    try:
        service = DatabaseMaintenanceService(
            db_manager,
            OperationTaskService(
                OperationTaskRepository(db_manager),
                TaskEventRepository(db_manager),
                AuditEventRepository(db_manager),
            ),
            BackupRepository(db_manager),
            backup_dir=backup_path,
        )
        result = service.create_backup(context=OperationContext.system())
        logger.info(f"备份完成: {result.path}")
    except Exception as error:
        logger.error(f"备份失败: {error}")
        sys.exit(1)
    finally:
        db_manager.close()


if __name__ == "__main__":
    main()
