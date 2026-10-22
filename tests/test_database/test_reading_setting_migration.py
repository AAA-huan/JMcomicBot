"""阅读设置迁移测试。"""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError


def _config(tmp_path: Path) -> Config:
    """构造指向临时 SQLite 文件的 Alembic 配置。"""
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{tmp_path / 'migration.db'}")
    return config


def _insert_admin(connection) -> None:
    """写入单管理员记录，满足阅读设置外键。"""
    connection.execute(text("""
            INSERT INTO web_admin (
                id, password_hash, password_version, created_at, updated_at
            ) VALUES (
                1, 'hash', 1, '2026-01-01', '2026-01-01'
            )
        """))


def test_reading_setting_migration_and_guarded_downgrade(tmp_path) -> None:
    """升级建表、默认值与 CHECK 生效；存在记录时拒绝降级。"""
    config = _config(tmp_path)
    command.upgrade(config, "0026_manga_blacklist")

    command.upgrade(config, "head")
    engine = create_engine(config.get_main_option("sqlalchemy.url"))
    inspector = inspect(engine)
    assert "reading_setting" in inspector.get_table_names()
    columns = {
        column["name"]: column for column in inspector.get_columns("reading_setting")
    }
    assert set(columns) == {
        "admin_id",
        "reading_mode",
        "continuous",
        "click_to_turn",
        "reverse_click",
        "dark_background",
        "updated_at",
    }
    assert all(column["nullable"] is False for column in columns.values())
    assert {
        constraint["name"]
        for constraint in inspector.get_check_constraints("reading_setting")
    } == {"ck_reading_setting_mode"}
    foreign_keys = inspector.get_foreign_keys("reading_setting")
    assert foreign_keys[0]["referred_table"] == "web_admin"
    assert foreign_keys[0]["options"]["ondelete"] == "CASCADE"

    with engine.begin() as connection:
        _insert_admin(connection)
        # 只提供 admin_id，验证迁移中的 server_default 生效。
        connection.execute(text("INSERT INTO reading_setting (admin_id) VALUES (1)"))
        row = connection.execute(
            text(
                "SELECT reading_mode, continuous, click_to_turn, reverse_click,"
                " dark_background, updated_at FROM reading_setting WHERE admin_id = 1"
            )
        ).one()
        assert row[0] == "normal"
        assert row[1:5] == (0, 0, 0, 0)
        assert row[5] is not None

        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO reading_setting (admin_id, reading_mode)"
                    " VALUES (2, 'invalid')"
                )
            )

    with pytest.raises(RuntimeError, match="阅读设置记录"):
        command.downgrade(config, "0026_manga_blacklist")
    assert "reading_setting" in inspect(engine).get_table_names()

    with engine.begin() as connection:
        connection.execute(text("DELETE FROM reading_setting"))
    command.downgrade(config, "0026_manga_blacklist")
    assert "reading_setting" not in inspect(engine).get_table_names()
    engine.dispose()
