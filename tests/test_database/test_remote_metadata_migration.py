"""站点快照迁移必须保留已有本地页数，降级不得静默丢失快照。"""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
import pytest


def test_remote_metadata_migration_preserves_local_data(tmp_path):
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.set_main_option("sqlalchemy.url", f'sqlite:///{tmp_path / "migration.db"}')
    command.upgrade(config, "0023_favorites_admin_qq")
    engine = create_engine(config.get_main_option("sqlalchemy.url"))
    with engine.begin() as connection:
        connection.execute(text("""
            INSERT INTO manga (id, source_site, title, author, chapter_count, page_count,
              status, metadata_source, downloaded_at, created_at, updated_at)
            VALUES ('100', 'jmcomic', '旧记录', '作者', 1, 5, 'downloaded', 'jmcomic',
              '2026-01-01', '2026-01-01', '2026-01-01')
        """))
    command.upgrade(config, "head")
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT page_count, chapter_count, remote_metadata FROM manga")
        ).one()
        assert tuple(row) == (5, 1, None)
    command.downgrade(config, "0023_favorites_admin_qq")
    command.upgrade(config, "head")
    with engine.begin() as connection:
        connection.execute(text("UPDATE manga SET remote_metadata = '{}'"))
    with pytest.raises(RuntimeError, match="存在站点元数据"):
        command.downgrade(config, "0023_favorites_admin_qq")
    engine.dispose()
