"""旧数据迁移：重复文件记录合并与相对路径回填回归测试。"""

from pathlib import Path

import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text

from src.database.migrations import upgrade_schema

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LEGACY_REVISION = "0007_unique_relative_file_path"
HEAD_REVISION = "0023_favorites_admin_qq"


def _engine_for(tmp_path: Path) -> Engine:
    """为测试构造独立的 SQLite 引擎。"""
    return create_engine(f"sqlite:///{tmp_path / 'main.db'}")


def _upgrade_to_legacy(engine: Engine) -> None:
    """把测试数据库升级到存在 file_path 列的 0007 版本。"""
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", engine.url.render_as_string())
    command.upgrade(config, LEGACY_REVISION)


def _insert_manga(engine: Engine, manga_id: str, title: str) -> None:
    """插入一条漫画记录。"""
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO manga (id, title, author, tags, chapter_count,"
                " page_count, status, downloaded_at)"
                " VALUES (:id, :title, '作者', '', 1, 1, 'downloaded',"
                " '2026-09-22 12:00:00')"
            ),
            {"id": manga_id, "title": title},
        )


def _insert_file(
    engine: Engine, manga_id: str, file_path: str, display_name: str
) -> int:
    """插入一条旧格式 manga_file 记录并返回 ID。"""
    with engine.begin() as connection:
        result = connection.execute(
            text(
                "INSERT INTO manga_file (manga_id, file_path, file_size_mb,"
                " created_at, display_name, file_size_bytes)"
                " VALUES (:manga_id, :file_path, 1.0, '2026-09-22 12:00:00',"
                " :display_name, 1024)"
            ),
            {
                "manga_id": manga_id,
                "file_path": file_path,
                "display_name": display_name,
            },
        )
        return int(result.lastrowid or 0)


def test_migration_merges_duplicate_file_records(tmp_path: Path) -> None:
    """同一漫画的相对/绝对路径重复登记应合并为一条并完成迁移。"""
    download_root = tmp_path / "downloads"
    download_root.mkdir()
    pdf_path = download_root / "516751-测试漫画(144章).pdf"
    pdf_path.write_bytes(b"%PDF-1.4 test")

    engine = _engine_for(tmp_path)
    _upgrade_to_legacy(engine)
    _insert_manga(engine, "516751", "测试漫画")
    # 模拟历史版本写入的两种路径写法：相对当前工作目录与绝对路径
    relative_file_path = os.path.relpath(pdf_path, Path.cwd())
    first_id = _insert_file(engine, "516751", relative_file_path, relative_file_path)
    second_id = _insert_file(engine, "516751", str(pdf_path), str(pdf_path))
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO reading_progress (manga_file_id, page_number,"
                " page_count, percent, updated_at)"
                " VALUES (:file_id, 3, 10, 30, '2026-09-24 00:00:00')"
            ),
            {"file_id": second_id},
        )

    upgrade_schema(engine, str(download_root))

    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT id, relative_path, display_name, status FROM manga_file")
        ).all()
        assert len(rows) == 1
        file_id, relative_path, display_name, status = rows[0]
        assert file_id == first_id
        assert relative_path == pdf_path.name
        assert display_name == pdf_path.name
        assert status == "ready"
        progress_file_id = connection.execute(
            text("SELECT manga_file_id FROM reading_progress")
        ).scalar_one()
        assert progress_file_id == first_id
        revision = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
        assert revision == HEAD_REVISION


def test_migration_rejects_same_file_for_different_manga(tmp_path: Path) -> None:
    """同一文件被两个漫画引用时停止迁移而不是猜测归属。"""
    download_root = tmp_path / "downloads"
    download_root.mkdir()
    pdf_path = download_root / "shared.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 test")

    engine = _engine_for(tmp_path)
    _upgrade_to_legacy(engine)
    _insert_manga(engine, "100", "漫画甲")
    _insert_manga(engine, "200", "漫画乙")
    _insert_file(engine, "100", str(pdf_path), str(pdf_path))
    relative_file_path = os.path.relpath(pdf_path, Path.cwd())
    _insert_file(engine, "200", relative_file_path, relative_file_path)

    with pytest.raises(RuntimeError, match="同一文件被多个漫画引用"):
        upgrade_schema(engine, str(download_root))


def test_migration_rejects_same_manga_with_different_files(tmp_path: Path) -> None:
    """同一漫画的重复记录指向不同文件时停止迁移等待人工确认。"""
    download_root = tmp_path / "downloads"
    download_root.mkdir()
    first_pdf = download_root / "first.pdf"
    second_pdf = download_root / "second.pdf"
    first_pdf.write_bytes(b"%PDF-1.4 first")
    second_pdf.write_bytes(b"%PDF-1.4 second")

    engine = _engine_for(tmp_path)
    _upgrade_to_legacy(engine)
    _insert_manga(engine, "300", "漫画丙")
    _insert_file(engine, "300", str(first_pdf), str(first_pdf))
    _insert_file(engine, "300", str(second_pdf), str(second_pdf))

    with pytest.raises(RuntimeError, match="指向不同文件的重复记录"):
        upgrade_schema(engine, str(download_root))
