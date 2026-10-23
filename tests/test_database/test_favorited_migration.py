"""0029 漫画 favorited 状态迁移测试。"""

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


def _insert_manga(connection, manga_id: str, status: str) -> None:
    """插入一条满足当前约束的漫画记录。"""
    connection.execute(
        text(
            "INSERT INTO manga ("
            "id, source_site, title, author, chapter_count, page_count, status,"
            " metadata_source, downloaded_at, created_at, updated_at"
            ") VALUES ("
            ":id, 'jmcomic', '标题', '', 0, 0, :status,"
            " 'jmcomic', '2026-01-01', '2026-01-01', '2026-01-01'"
            ")"
        ),
        {"id": manga_id, "status": status},
    )


def test_favorited_migration_allows_status_and_preserves_files(tmp_path: Path) -> None:
    """升级允许 favorited，降级转换状态且不丢失文件记录。"""
    config = _config(tmp_path)
    command.upgrade(config, "0028_drop_backup_record")
    engine = create_engine(config.get_main_option("sqlalchemy.url"))
    try:
        with engine.begin() as connection:
            _insert_manga(connection, "100", "downloaded")
            connection.execute(
                text(
                    "INSERT INTO manga_file ("
                    "manga_id, relative_path, display_name, file_type, mime_type,"
                    " file_size_bytes, page_count, status, created_at, updated_at"
                    ") VALUES ("
                    "'100', '100.pdf', '100.pdf', 'pdf', 'application/pdf',"
                    " 1024, 10, 'ready', '2026-01-01', '2026-01-01'"
                    ")"
                )
            )

        command.upgrade(config, "0029_add_manga_status_favorited")
        with engine.begin() as connection:
            _insert_manga(connection, "200", "favorited")
        checks = {
            item["sqltext"]
            for item in inspect(engine).get_check_constraints("manga")
            if item["name"] == "ck_manga_status"
        }
        assert any("favorited" in item for item in checks)

        command.downgrade(config, "0028_drop_backup_record")
        with engine.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT status FROM manga WHERE id = '200'")
                ).scalar_one()
                == "missing_file"
            )
            assert (
                connection.execute(
                    text("SELECT COUNT(*) FROM manga_file WHERE manga_id = '100'")
                ).scalar_one()
                == 1
            )
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                _insert_manga(connection, "300", "favorited")

        command.upgrade(config, "0029_add_manga_status_favorited")
        with engine.begin() as connection:
            _insert_manga(connection, "300", "favorited")
    finally:
        engine.dispose()
