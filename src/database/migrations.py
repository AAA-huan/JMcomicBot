"""数据库版本管理基础设施。

当前版本只登记现有 ORM 结构，后续 schema 改造必须通过新增版本迁移完成。
"""

from pathlib import Path
import os
import sqlite3

from sqlalchemy import Connection, Engine, inspect, text

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

CURRENT_SCHEMA_VERSION = 23


def prepare_legacy_file_paths(engine: Engine, download_root: str | None) -> None:
    """在删除旧绝对路径列前回填文件相对路径，并合并历史重复登记。

    历史版本曾以相对路径与绝对路径两种写法为同一漫画重复写入文件记录，
    而 0008 迁移会为 manga_id 建立唯一索引，因此必须在此之前确定性合并。
    仅当同一漫画的重复记录指向同一文件时自动合并，其余冲突明确报错等待
    人工处理，不做猜测性覆盖。
    """
    if not download_root:
        return
    root = Path(download_root).resolve()
    with engine.begin() as connection:
        inspector = inspect(connection)
        table_names = inspector.get_table_names()
        if "manga_file" not in table_names:
            # 全新数据库尚无 manga_file 表，没有旧路径需要回填
            return
        columns = {column["name"] for column in inspector.get_columns("manga_file")}
        if "file_path" not in columns or "relative_path" not in columns:
            return
        has_display_name = "display_name" in columns
        has_reading_progress = "reading_progress" in table_names

        select_columns = "id, manga_id, file_path, relative_path"
        if has_display_name:
            select_columns += ", display_name"
        rows = connection.execute(
            text(f"SELECT {select_columns} FROM manga_file ORDER BY id")
        ).all()

        manga_by_file: dict[int, str] = {}
        relative_by_file: dict[int, str] = {}
        display_by_file: dict[int, str] = {}
        pending_backfill: set[int] = set()
        unresolved: list[int] = []
        for row in rows:
            file_id, manga_id, file_path, relative_path = row[:4]
            manga_by_file[file_id] = manga_id
            if has_display_name:
                display_by_file[file_id] = row[4] or ""
            if relative_path is not None:
                relative_by_file[file_id] = relative_path
                continue
            resolved_path = Path(file_path).resolve()
            try:
                candidate = str(resolved_path.relative_to(root))
            except ValueError:
                unresolved.append(file_id)
                continue
            if not resolved_path.is_file():
                unresolved.append(file_id)
                continue
            relative_by_file[file_id] = candidate
            pending_backfill.add(file_id)
        if unresolved:
            raise RuntimeError(
                "存在无法安全转换为相对路径的漫画文件记录，"
                f"请先处理文件ID: {unresolved}"
            )

        _merge_duplicate_file_records(
            connection,
            manga_by_file,
            relative_by_file,
            update_reading_progress=has_reading_progress,
        )

        owner_by_relative: dict[str, int] = {}
        for file_id, relative_path in relative_by_file.items():
            owner = owner_by_relative.get(relative_path)
            if owner is not None and manga_by_file[owner] != manga_by_file[file_id]:
                raise RuntimeError(
                    "同一文件被多个漫画引用，无法安全转换，请先人工确认归属: "
                    f"文件ID {owner} 与 {file_id}"
                )
            owner_by_relative[relative_path] = file_id

        for file_id in sorted(pending_backfill):
            if file_id not in relative_by_file:
                # 该记录已在合并重复时被合并删除
                continue
            relative_path = relative_by_file[file_id]
            parameters: dict[str, object] = {
                "id": file_id,
                "relative_path": relative_path,
            }
            statement = (
                "UPDATE manga_file SET relative_path = :relative_path, "
                "status = 'ready', updated_at = CURRENT_TIMESTAMP"
            )
            # 历史记录曾把路径写进 display_name，统一规范为真实文件名
            display_name = display_by_file.get(file_id, "")
            if has_display_name and (
                not display_name or "/" in display_name or "\\" in display_name
            ):
                statement += ", display_name = :display_name"
                parameters["display_name"] = Path(relative_path).name
            connection.execute(text(f"{statement} WHERE id = :id"), parameters)


def _merge_duplicate_file_records(
    connection: Connection,
    manga_by_file: dict[int, str],
    relative_by_file: dict[int, str],
    update_reading_progress: bool,
) -> None:
    """合并同一漫画指向同一文件的重复登记，保留最早的记录。

    Raises:
        RuntimeError: 同一漫画的重复记录指向不同文件时，无法自动判断保留哪条。
    """
    file_ids_by_manga: dict[str, list[int]] = {}
    for file_id, manga_id in manga_by_file.items():
        file_ids_by_manga.setdefault(manga_id, []).append(file_id)

    for manga_id, file_ids in file_ids_by_manga.items():
        if len(file_ids) < 2:
            continue
        file_ids_by_relative: dict[str, list[int]] = {}
        for file_id in file_ids:
            file_ids_by_relative.setdefault(relative_by_file[file_id], []).append(
                file_id
            )
        if len(file_ids_by_relative) > 1:
            raise RuntimeError(
                f"漫画ID {manga_id} 存在指向不同文件的重复记录，"
                f"请先人工确认: {sorted(file_ids)}"
            )
        for group in file_ids_by_relative.values():
            if len(group) < 2:
                continue
            keep = min(group)
            for duplicate_id in group:
                if duplicate_id == keep:
                    continue
                duplicate = (
                    connection.execute(
                        text("SELECT * FROM manga_file WHERE id = :id"),
                        {"id": duplicate_id},
                    )
                    .mappings()
                    .first()
                )
                if duplicate is not None:
                    connection.execute(
                        text(
                            "UPDATE manga_file SET"
                            " file_size_bytes = COALESCE(file_size_bytes, :file_size_bytes),"
                            " page_count = COALESCE(page_count, :page_count),"
                            " sha256 = COALESCE(sha256, :sha256),"
                            " last_verified_at = COALESCE(last_verified_at, :last_verified_at)"
                            " WHERE id = :keep"
                        ),
                        {
                            "keep": keep,
                            "file_size_bytes": duplicate.get("file_size_bytes"),
                            "page_count": duplicate.get("page_count"),
                            "sha256": duplicate.get("sha256"),
                            "last_verified_at": duplicate.get("last_verified_at"),
                        },
                    )
                if update_reading_progress:
                    connection.execute(
                        text(
                            "UPDATE reading_progress SET manga_file_id = :keep "
                            "WHERE manga_file_id = :duplicate"
                        ),
                        {"keep": keep, "duplicate": duplicate_id},
                    )
                connection.execute(
                    text("DELETE FROM manga_file WHERE id = :id"),
                    {"id": duplicate_id},
                )
                relative_by_file.pop(duplicate_id, None)
                manga_by_file.pop(duplicate_id, None)


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


def get_schema_revision(engine: Engine) -> str:
    """返回数据库当前 Alembic revision；未应用迁移时明确报错。"""
    with engine.connect() as connection:
        revision = MigrationContext.configure(connection).get_current_revision()
    if not revision:
        raise RuntimeError("数据库未应用任何 Alembic 迁移，无法确定 schema 版本")
    return revision


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
