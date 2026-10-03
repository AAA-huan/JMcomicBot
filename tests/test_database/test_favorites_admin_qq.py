"""收藏与管理员 QQ 关联的迁移和数据约束回归。"""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
import pytest

from src.database.models import MangaFavorite, utc_now
from src.database.repositories import (
    FavoriteRepository,
    MangaRepository,
    WebAdminRepository,
)


@pytest.mark.parametrize("favorite", [True, False])
def test_favorites_are_idempotent_and_owner_isolated(db_manager, favorite):
    """同一漫画的管理员与不同 QQ 收藏相互独立。"""
    mangas = MangaRepository(db_manager)
    mangas.upsert("100", "漫画", "作者", 1, 10)
    repository = FavoriteRepository(db_manager)
    assert repository.set_favorite("web_admin", "1", "100", True)
    assert repository.set_favorite("qq", "12345", "100", True)
    assert repository.set_favorite("qq", "67890", "100", True)
    assert not repository.set_favorite("web_admin", "1", "100", True)
    assert repository.set_favorite("web_admin", "1", "100", favorite) is (not favorite)
    assert not repository.set_favorite("web_admin", "1", "100", favorite)
    assert repository.ids_for_mangas("qq", "12345", ["100", "200"]) == {"100"}
    assert len(repository.list("qq", "67890")) == 1
    assert mangas.delete("100")
    assert repository.list("qq", "12345") == []
    assert repository.list("qq", "67890") == []
    assert repository.list("web_admin", "1") == []
    mangas.upsert("100", "重新下载", "作者", 1, 10)
    assert repository.get("web_admin", "1", "100") is None


@pytest.mark.parametrize(
    "owner_type,owner_id,manga_id",
    [
        ("unknown", "1", "100"),
        ("qq", "", "100"),
        ("qq", "12345", "missing"),
    ],
)
def test_favorite_database_constraints(db_manager, owner_type, owner_id, manga_id):
    """数据库约束拒绝未知归属、空用户和不存在的漫画。"""
    MangaRepository(db_manager).upsert("100", "漫画", "", 1, 1)
    with db_manager.get_session() as session:
        session.add(
            MangaFavorite(
                owner_type=owner_type,
                owner_id=owner_id,
                manga_id=manga_id,
                created_at=utc_now(),
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_migration_preserves_admin_sessions_and_rejects_lossy_downgrade(tmp_path):
    """0022 → 0023 保留旧账户与会话，有新增数据时不能静默降级。"""
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    file = tmp_path / "upgrade.db"
    config.set_main_option("sqlalchemy.url", f"sqlite:///{file}")
    command.upgrade(config, "0022_add_reading_maintenance_schema")
    engine = create_engine(f"sqlite:///{file}")
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO web_admin (id, password_hash, password_version, created_at, updated_at) VALUES (1, 'old-hash', 2, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO web_session (id, token_hash, admin_id, password_version, created_at, expires_at, last_seen_at) VALUES ('old-session', 'token-hash', 1, 2, CURRENT_TIMESTAMP, '2099-01-01', CURRENT_TIMESTAMP)"
                )
            )
        command.upgrade(config, "head")
        command.upgrade(config, "head")
        with engine.begin() as connection:
            assert connection.execute(
                text("SELECT password_hash, password_version, qq_id FROM web_admin")
            ).one() == ("old-hash", 2, None)
            assert (
                connection.execute(text("SELECT id FROM web_session")).scalar_one()
                == "old-session"
            )
            connection.execute(text("UPDATE web_admin SET qq_id='12345' WHERE id=1"))
        with pytest.raises(RuntimeError, match="存在收藏或管理员 QQ 关联"):
            command.downgrade(config, "0022_add_reading_maintenance_schema")
        with engine.begin() as connection:
            connection.execute(text("UPDATE web_admin SET qq_id=NULL WHERE id=1"))
            connection.execute(
                text(
                    "INSERT INTO manga (id,title,author,chapter_count,page_count,status,downloaded_at,created_at,updated_at) VALUES ('100','漫画','',1,1,'downloaded',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO manga_favorite VALUES ('web_admin','1','100',CURRENT_TIMESTAMP)"
                )
            )
        with pytest.raises(RuntimeError, match="存在收藏或管理员 QQ 关联"):
            command.downgrade(config, "0022_add_reading_maintenance_schema")
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM manga_favorite"))
        command.downgrade(config, "0022_add_reading_maintenance_schema")
        assert "manga_favorite" not in inspect(engine).get_table_names()
        command.upgrade(config, "head")
        with engine.connect() as connection:
            assert (
                connection.execute(text("SELECT id FROM web_session")).scalar_one()
                == "old-session"
            )
    finally:
        engine.dispose()
