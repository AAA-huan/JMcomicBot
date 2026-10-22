"""漫画黑名单迁移测试。"""

from pathlib import Path

import pytest
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


def _insert_blacklist_task(connection) -> None:
    """写入一条 blacklist 任务，验证扩展后的约束可用。"""
    connection.execute(text("""
            INSERT INTO operation_task (
                id, task_type, source, status, stage, progress, manga_id,
                requested_by, summary, error_code, error_message, attempt_count,
                created_at, started_at, updated_at, finished_at
            ) VALUES (
                'blacklist-task', 'blacklist', 'qq', 'succeeded', 'done', 100, '100',
                '10001', '漫画黑名单 100', NULL, NULL, 0,
                '2026-01-01', '2026-01-01', '2026-01-01', '2026-01-01'
            )
        """))


def test_manga_blacklist_migration_and_guarded_downgrade(tmp_path) -> None:
    """升级建表与约束；存在黑名单或 blacklist 任务时拒绝降级。"""
    config = _config(tmp_path)
    command.upgrade(config, "0025_jm_favorite_import")

    command.upgrade(config, "head")
    engine = create_engine(config.get_main_option("sqlalchemy.url"))
    inspector = inspect(engine)
    assert "manga_blacklist" in inspector.get_table_names()
    assert "ix_manga_blacklist_manga_id" in {
        index["name"] for index in inspector.get_indexes("manga_blacklist")
    }
    columns = {
        column["name"]: column for column in inspector.get_columns("manga_blacklist")
    }
    assert columns["blacklisted_at"]["nullable"] is False
    assert columns["blacklisted_at"]["default"] is not None

    with engine.begin() as connection:
        # 不显式提供时间，验证迁移中的 server_default 生效。
        connection.execute(text("""
                INSERT INTO manga_blacklist (manga_id, reason, requested_by, source)
                VALUES ('100', '测试', '10001', 'qq')
            """))
        assert (
            connection.execute(
                text("SELECT blacklisted_at FROM manga_blacklist WHERE manga_id='100'")
            ).scalar_one()
            is not None
        )
        _insert_blacklist_task(connection)

    with pytest.raises(RuntimeError, match="漫画黑名单记录"):
        command.downgrade(config, "0025_jm_favorite_import")
    assert "manga_blacklist" in inspect(engine).get_table_names()

    with engine.begin() as connection:
        connection.execute(text("DELETE FROM manga_blacklist"))
    with pytest.raises(RuntimeError, match="blacklist 任务记录"):
        command.downgrade(config, "0025_jm_favorite_import")
    assert "manga_blacklist" in inspect(engine).get_table_names()

    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM operation_task WHERE task_type='blacklist'")
        )
    command.downgrade(config, "0025_jm_favorite_import")
    inspector = inspect(engine)
    assert "manga_blacklist" not in inspector.get_table_names()
    with engine.begin() as connection:
        insert_legacy = text("""
            INSERT INTO operation_task (
                id, task_type, source, status, stage, progress, manga_id,
                requested_by, summary, error_code, error_message, attempt_count,
                created_at, started_at, updated_at, finished_at
            ) VALUES (
                'invalid-blacklist', 'blacklist', 'qq', 'queued', 'queued', NULL, NULL,
                '', '', NULL, NULL, 0, '2026-01-01', NULL, '2026-01-01', NULL
            )
        """)
        with pytest.raises(Exception):
            connection.execute(insert_legacy)
    engine.dispose()
