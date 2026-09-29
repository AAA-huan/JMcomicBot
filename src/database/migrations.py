"""数据库版本管理基础设施。

当前版本只登记现有 ORM 结构，后续 schema 改造必须通过新增版本迁移完成。
"""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text

CURRENT_SCHEMA_VERSION = 1


def upgrade_schema(engine: Engine) -> None:
    """将数据库升级到迁移目录中的最新版本。"""
    project_root = Path(__file__).resolve().parents[2]
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    config.set_main_option("sqlalchemy.url", engine.url.render_as_string())
    command.upgrade(config, "head")


def ensure_schema_version(engine: Engine) -> None:
    """创建并校验 schema 版本，拒绝由更新代码读取的未知版本。"""
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY,
                    applied_at DATETIME NOT NULL
                )
                """
            )
        )
        current_version = connection.execute(
            text("SELECT MAX(version) FROM schema_version")
        ).scalar()

        if current_version is None:
            connection.execute(
                text(
                    "INSERT INTO schema_version(version, applied_at) "
                    "VALUES (:version, CURRENT_TIMESTAMP)"
                ),
                {"version": CURRENT_SCHEMA_VERSION},
            )
            return

        if current_version > CURRENT_SCHEMA_VERSION:
            raise RuntimeError(
                f"数据库 schema 版本 {current_version} 高于当前代码支持的版本 "
                f"{CURRENT_SCHEMA_VERSION}，请先升级应用"
            )
