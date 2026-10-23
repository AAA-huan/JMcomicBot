"""0028 删除备份记录表迁移测试。"""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


def _config(tmp_path: Path) -> Config:
    """构造指向临时 SQLite 文件的 Alembic 配置。"""
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{tmp_path / 'migration.db'}")
    return config


def test_drop_backup_record_migration_removes_table_and_keeps_downgrade_empty(
    tmp_path,
) -> None:
    """升级应删除含数据的备份表；降级不重建，再次升级仍可执行。"""
    config = _config(tmp_path)
    command.upgrade(config, "0027_reading_setting")

    engine = create_engine(config.get_main_option("sqlalchemy.url"))
    try:
        assert "backup_record" in inspect(engine).get_table_names()
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO backup_record ("
                    "filename, relative_path, file_size_bytes, schema_version,"
                    " status, created_at, updated_at"
                    ") VALUES ("
                    "'main-20260101-000000.db', 'main-20260101-000000.db', 1024,"
                    " '0027_reading_setting', 'ready', '2026-01-01', '2026-01-01'"
                    ")"
                )
            )

        command.upgrade(config, "0028_drop_backup_record")
        assert "backup_record" not in inspect(engine).get_table_names()

        command.downgrade(config, "0027_reading_setting")
        assert "backup_record" not in inspect(engine).get_table_names()

        command.upgrade(config, "0028_drop_backup_record")
        assert "backup_record" not in inspect(engine).get_table_names()
    finally:
        engine.dispose()
