"""远端收藏迁移保留本地数据，降级不静默删除导入结果。"""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
import pytest


def test_jm_favorite_migration_and_guarded_downgrade(tmp_path):
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.set_main_option("sqlalchemy.url", f'sqlite:///{tmp_path / "migration.db"}')
    command.upgrade(config, "0024_manga_remote_metadata")
    engine = create_engine(config.get_main_option("sqlalchemy.url"))
    with engine.begin() as connection:
        connection.execute(text("""
            INSERT INTO web_admin (id, password_hash, password_version, created_at, updated_at)
            VALUES (1, 'hash', 1, '2026-01-01', '2026-01-01')
        """))
    command.upgrade(config, "head")
    assert {"jm_remote_favorite", "jm_favorite_import"}.issubset(
        inspect(engine).get_table_names()
    )
    with engine.connect() as connection:
        assert (
            connection.execute(text("SELECT password_hash FROM web_admin")).scalar_one()
            == "hash"
        )
    command.downgrade(config, "0024_manga_remote_metadata")
    command.upgrade(config, "head")
    with engine.begin() as connection:
        connection.execute(text("""
            INSERT INTO jm_remote_favorite (admin_id, username, manga_id, title, folders,
                pending_local_favorite, imported_at, updated_at)
            VALUES (1, 'user', '100', '漫画', '{}', 1, '2026-01-01', '2026-01-01')
        """))
    with pytest.raises(RuntimeError, match="存在 JM 收藏导入记录"):
        command.downgrade(config, "0024_manga_remote_metadata")
    assert "jm_remote_favorite" in inspect(engine).get_table_names()
    # 与管理员本地收藏保持一致：受控重置管理员不删除已导入收藏。
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM web_admin WHERE id = 1"))
        assert (
            connection.execute(
                text("SELECT COUNT(*) FROM jm_remote_favorite")
            ).scalar_one()
            == 1
        )
    engine.dispose()
