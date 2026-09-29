"""数据库版本管理基础设施。

当前版本只登记现有 ORM 结构，后续 schema 改造必须通过新增版本迁移完成。
"""

from pathlib import Path
import os
import sqlite3

from sqlalchemy import Engine, inspect, text

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

CURRENT_SCHEMA_VERSION = 21


def prepare_legacy_file_paths(engine: Engine, download_root: str | None) -> None:
    """在删除旧绝对路径列前回填并验证所有文件相对路径。"""
    if not download_root:
        return
    root = Path(download_root).resolve()
    with engine.begin() as connection:
        columns = {
            column["name"] for column in inspect(connection).get_columns("manga_file")
        }
        if "file_path" not in columns or "relative_path" not in columns:
            return
        rows = connection.execute(
            text(
                "SELECT id, file_path, relative_path FROM manga_file "
                "WHERE relative_path IS NULL"
            )
        ).all()
        unresolved: list[int] = []
        for file_id, file_path, _relative_path in rows:
            resolved_path = Path(file_path).resolve()
            try:
                relative_path = str(resolved_path.relative_to(root))
            except ValueError:
                unresolved.append(file_id)
                continue
            if not resolved_path.is_file():
                unresolved.append(file_id)
                continue
            connection.execute(
                text(
                    "UPDATE manga_file SET relative_path = :relative_path, "
                    "status = 'ready', updated_at = CURRENT_TIMESTAMP WHERE id = :id"
                ),
                {"id": file_id, "relative_path": relative_path},
            )
        if unresolved:
            raise RuntimeError(
                "存在无法安全转换为相对路径的漫画文件记录，"
                f"请先处理文件ID: {unresolved}"
            )


def backup_database(engine: Engine, destination: str) -> None:
    """使用 SQLite backup API 创建一致性数据库备份。"""
    source_path = engine.url.database
    if not source_path or source_path == ":memory:":
        raise ValueError("只有文件型 SQLite 数据库支持迁移前备份")

    os.makedirs(os.path.dirname(os.path.abspath(destination)), exist_ok=True)
    source = sqlite3.connect(source_path)
    target = sqlite3.connect(destination)
    try:
        source.backup(target)
        target.commit()
    finally:
        target.close()
        source.close()


def upgrade_schema(engine: Engine, download_root: str | None = None) -> None:
    """将数据库升级到迁移目录中的最新版本。"""
    project_root = Path(__file__).resolve().parents[2]
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    config.set_main_option("sqlalchemy.url", engine.url.render_as_string())
    expected_revision = ScriptDirectory.from_config(config).get_current_head()
    with engine.connect() as connection:
        current_revision = MigrationContext.configure(connection).get_current_revision()
    if current_revision == expected_revision:
        return

    database_path = engine.url.database
    if database_path and database_path != ":memory:":
        backup_database(engine, f"{database_path}.pre-migration.bak")
    prepare_legacy_file_paths(engine, download_root)
    command.upgrade(config, "head")


def ensure_schema_version(engine: Engine) -> None:
    """创建并校验 schema 版本，拒绝由更新代码读取的未知版本。"""
    with engine.begin() as connection:
        connection.execute(text("""
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY,
                    applied_at DATETIME NOT NULL
                )
                """))
        current_version = connection.execute(
            text("SELECT MAX(version) FROM schema_version")
        ).scalar()

        if current_version is None or current_version < CURRENT_SCHEMA_VERSION:
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
