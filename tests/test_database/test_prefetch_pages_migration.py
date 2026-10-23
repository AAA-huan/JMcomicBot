"""0030 阅读设置预加载页数迁移测试。"""

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


def test_prefetch_pages_migration_defaults_and_downgrade(tmp_path) -> None:
    """升级为历史设置补默认值 1，降级删除该列且保留其他设置。"""
    config = _config(tmp_path)
    command.upgrade(config, "0029_add_manga_status_favorited")

    engine = create_engine(config.get_main_option("sqlalchemy.url"))
    try:
        with engine.begin() as connection:
            connection.execute(text("""
                    INSERT INTO web_admin (
                        id, password_hash, password_version, created_at, updated_at
                    ) VALUES (
                        1, 'hash', 1, '2026-01-01', '2026-01-01'
                    )
                """))
            connection.execute(text("""
                    INSERT INTO reading_setting (
                        admin_id, reading_mode, continuous, click_to_turn,
                        reverse_click, dark_background
                    ) VALUES (1, 'manga', 1, 0, 0, 0)
                """))

        command.upgrade(config, "0030_add_reading_setting_prefetch_pages")
        inspector = inspect(engine)
        columns = {
            column["name"]: column
            for column in inspector.get_columns("reading_setting")
        }
        assert columns["prefetch_pages"]["nullable"] is False
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT reading_mode, prefetch_pages FROM reading_setting"
                    " WHERE admin_id = 1"
                )
            ).one()
        assert row == ("manga", 1)

        command.downgrade(config, "0029_add_manga_status_favorited")
        columns = {
            column["name"] for column in inspect(engine).get_columns("reading_setting")
        }
        assert "prefetch_pages" not in columns
        with engine.connect() as connection:
            retained = connection.execute(
                text("SELECT reading_mode FROM reading_setting WHERE admin_id = 1")
            ).scalar_one()
        assert retained == "manga"
    finally:
        engine.dispose()
