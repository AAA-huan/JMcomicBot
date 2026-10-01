"""阶段三批次 A：迁移 0022 与新表结构测试。"""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
import pytest

from src.database.models import (
    BackupRecord,
    Manga,
    MangaFile,
    OperationTask,
    ReadingProgress,
    ScanRecord,
    utc_now,
)
from src.database.repositories import (
    AuditEventRepository,
    OperationTaskRepository,
    TaskEventRepository,
)
from src.service import OperationContext, OperationTaskService


def _alembic_config(database_path: Path) -> Config:
    """构造指向临时数据库的 Alembic 配置。"""
    project_root = Path(__file__).resolve().parents[2]
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    return config


def _add_task(session: Session, task_id: str, task_type: str) -> None:
    """插入一条最小字段的操作任务。"""
    now = utc_now()
    session.add(
        OperationTask(
            id=task_id,
            task_type=task_type,
            source="system",
            status="queued",
            stage="queued",
            requested_by="",
            summary="",
            created_at=now,
            updated_at=now,
        )
    )


@pytest.fixture()
def task_repo(db_manager) -> OperationTaskRepository:
    return OperationTaskRepository(db_manager)


@pytest.fixture()
def event_repo(db_manager) -> TaskEventRepository:
    return TaskEventRepository(db_manager)


@pytest.fixture()
def audit_repo(db_manager) -> AuditEventRepository:
    return AuditEventRepository(db_manager)


@pytest.fixture()
def task_service(task_repo, event_repo, audit_repo) -> OperationTaskService:
    return OperationTaskService(task_repo, event_repo, audit_repo)


def test_stage_three_schema_columns_exist(db_manager) -> None:
    """scan_record 与 backup_record 应重建为阶段三正式字段。"""
    inspector = inspect(db_manager.engine)
    assert {"reading_progress", "scan_record", "backup_record"} <= set(
        inspector.get_table_names()
    )

    scan_columns = {item["name"]: item for item in inspector.get_columns("scan_record")}
    assert {
        "task_id",
        "task_type",
        "path_label",
        "file_count",
        "new_count",
        "updated_count",
        "missing_count",
        "repaired_count",
        "corrupted_count",
        "error_count",
        "created_at",
    } <= set(scan_columns)
    assert scan_columns["task_id"]["nullable"] is False
    assert scan_columns["task_type"]["nullable"] is False
    assert scan_columns["path_label"]["nullable"] is False
    assert {"path_key", "scanned_count", "added_count"}.isdisjoint(scan_columns)

    backup_columns = {
        item["name"]: item for item in inspector.get_columns("backup_record")
    }
    assert {
        "filename",
        "relative_path",
        "file_size_bytes",
        "sha256",
        "schema_version",
        "status",
        "created_at",
        "updated_at",
        "deleted_at",
    } <= set(backup_columns)
    assert {"file_name", "path_key"}.isdisjoint(backup_columns)

    file_columns = {item["name"]: item for item in inspector.get_columns("manga_file")}
    assert "file_mtime" in file_columns
    assert file_columns["file_mtime"]["nullable"] is True


def test_stage_three_constraints_and_indexes_exist(db_manager) -> None:
    """新表的外键、唯一约束、CHECK 和索引应真实存在。"""
    inspector = inspect(db_manager.engine)

    task_checks = {
        item["name"] for item in inspector.get_check_constraints("operation_task")
    }
    scan_checks = {
        item["name"] for item in inspector.get_check_constraints("scan_record")
    }
    backup_checks = {
        item["name"] for item in inspector.get_check_constraints("backup_record")
    }
    assert "ck_operation_task_type" in task_checks
    assert "ck_scan_record_task_type" in scan_checks
    assert "ck_backup_record_status" in backup_checks

    scan_foreign_keys = {
        tuple(item["constrained_columns"]): item
        for item in inspector.get_foreign_keys("scan_record")
    }
    assert scan_foreign_keys[("task_id",)]["referred_table"] == "operation_task"
    assert scan_foreign_keys[("task_id",)]["options"]["ondelete"] == "CASCADE"
    progress_foreign_keys = {
        tuple(item["constrained_columns"]): item
        for item in inspector.get_foreign_keys("reading_progress")
    }
    assert progress_foreign_keys[("manga_file_id",)]["referred_table"] == "manga_file"
    assert progress_foreign_keys[("manga_file_id",)]["options"]["ondelete"] == "CASCADE"

    backup_uniques = {
        item["name"] for item in inspector.get_unique_constraints("backup_record")
    }
    assert "uq_backup_record_relative_path" in backup_uniques

    expected_indexes = {
        "scan_record": {"ix_scan_record_task_id", "ix_scan_record_created"},
        "backup_record": {
            "ix_backup_record_status_created",
            "ix_backup_record_created",
        },
        "reading_progress": {"ix_reading_progress_updated"},
    }
    for table_name, names in expected_indexes.items():
        actual = {item["name"] for item in inspector.get_indexes(table_name)}
        assert names <= actual, f"表 {table_name} 缺少索引: {names - actual}"


def test_operation_task_type_check_accepts_verify(db_manager) -> None:
    """operation_task 应接受 verify 任务类型并拒绝未知类型。"""
    with db_manager.get_session() as session:
        _add_task(session, "verify-task", "verify")
        session.commit()

        _add_task(session, "bad-task", "unknown")
        with pytest.raises(IntegrityError):
            session.commit()


def test_scan_record_type_check_and_task_cascade(db_manager) -> None:
    """scan_record 任务类型受控，且随任务删除级联清理。"""
    now = utc_now()
    with db_manager.get_session() as session:
        _add_task(session, "scan-task", "scan")
        session.flush()
        session.add(
            ScanRecord(
                task_id="scan-task",
                task_type="scan",
                path_label="MANGA_DOWNLOAD_PATH",
                file_count=5,
                new_count=1,
                corrupted_count=0,
                created_at=now,
            )
        )
        session.commit()

        # download 不是维护任务，不能写入 scan_record
        session.add(
            ScanRecord(
                task_id="scan-task",
                task_type="download",
                path_label="MANGA_DOWNLOAD_PATH",
                created_at=now,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    with db_manager.get_session() as session:
        session.execute(delete(OperationTask).where(OperationTask.id == "scan-task"))
        session.commit()
        assert session.scalars(select(ScanRecord)).all() == []


def test_backup_record_status_and_unique_path(db_manager) -> None:
    """backup_record 应校验状态并保证相对路径唯一。"""
    now = utc_now()
    with db_manager.get_session() as session:
        session.add(
            BackupRecord(
                filename="main-20260101-000000-0022.db",
                relative_path="main-20260101-000000-0022.db",
                file_size_bytes=1024,
                schema_version="0022",
                status="ready",
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()

        session.add(
            BackupRecord(
                filename="main-20260102-000000-0022.db",
                relative_path="main-20260101-000000-0022.db",
                schema_version="0022",
                status="ready",
                created_at=now,
                updated_at=now,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        session.add(
            BackupRecord(
                filename="main-20260103-000000-0022.db",
                relative_path="main-20260103-000000-0022.db",
                schema_version="0022",
                status="broken",
                created_at=now,
                updated_at=now,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_reading_progress_cascades_with_manga_deletion(db_manager) -> None:
    """删除漫画应级联删除 PDF 记录与阅读进度。"""
    now = utc_now()
    with db_manager.get_session() as session:
        session.add(
            Manga(
                id="manga-1",
                title="测试漫画",
                author="",
                chapter_count=1,
                page_count=10,
                status="downloaded",
                downloaded_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        session.flush()
        manga_file = MangaFile(
            manga_id="manga-1",
            relative_path="测试漫画.pdf",
            display_name="测试漫画.pdf",
            file_type="pdf",
            mime_type="application/pdf",
            file_size_bytes=2048,
            page_count=10,
            status="ready",
            created_at=now,
            updated_at=now,
        )
        session.add(manga_file)
        session.flush()
        session.add(
            ReadingProgress(
                manga_file_id=manga_file.id,
                page_number=3,
                page_count=10,
                percent=0.3,
                updated_at=now,
            )
        )
        session.commit()
        file_id = manga_file.id

    with db_manager.get_session() as session:
        session.execute(delete(Manga).where(Manga.id == "manga-1"))
        session.commit()
        assert session.get(MangaFile, file_id) is None
        assert session.get(ReadingProgress, file_id) is None


def test_verify_task_type_is_supported_by_service(
    task_repo, task_service, audit_repo
) -> None:
    """仓储与审计映射应支持 verify 任务类型。"""
    task = task_repo.create("verify", "system")
    assert task.summary == "校验漫画文件"

    context = OperationContext.system()
    verify_task = task_service.create("verify", context)
    task_service.start(verify_task.id, "verifying")
    task_service.succeed(verify_task.id, context=context)

    event_types = {event.event_type for event in audit_repo.list()}
    assert {
        "library.verify_requested",
        "library.verify_completed",
    } <= event_types


def test_stage_three_queries_use_expected_indexes(db_manager) -> None:
    """继续阅读、维护记录和备份列表查询应命中阶段三索引。"""
    with db_manager.get_session() as session:
        progress_plan = session.execute(
            text(
                "EXPLAIN QUERY PLAN SELECT manga_file_id FROM reading_progress "
                "ORDER BY updated_at DESC LIMIT 20"
            )
        ).all()
        scan_plan = session.execute(
            text(
                "EXPLAIN QUERY PLAN SELECT id FROM scan_record "
                "WHERE task_id = 'x' ORDER BY created_at DESC, id LIMIT 20"
            )
        ).all()
        backup_plan = session.execute(
            text(
                "EXPLAIN QUERY PLAN SELECT id FROM backup_record "
                "WHERE status = 'ready' ORDER BY created_at DESC, id LIMIT 20"
            )
        ).all()

    progress_details = " ".join(str(row[-1]) for row in progress_plan)
    scan_details = " ".join(str(row[-1]) for row in scan_plan)
    backup_details = " ".join(str(row[-1]) for row in backup_plan)
    assert "ix_reading_progress_updated" in progress_details
    assert "ix_scan_record_task_id" in scan_details
    assert "ix_backup_record_status_created" in backup_details


def test_migration_0022_upgrades_existing_database(tmp_path) -> None:
    """从 0021 升级时旧数据保留、verify 可用且新字段就位。"""
    database_path = tmp_path / "upgrade.db"
    config = _alembic_config(database_path)
    command.upgrade(config, "0021_add_operation_task_summary")

    engine = create_engine(f"sqlite:///{database_path}")
    try:
        with engine.begin() as connection:
            connection.execute(text("""
                    INSERT INTO operation_task (
                        id, task_type, source, status, stage, requested_by,
                        attempt_count, created_at, updated_at
                    ) VALUES (
                        'old-task', 'download', 'qq', 'queued', 'queued', '10001',
                        0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                    )
                    """))
            connection.execute(text("""
                    INSERT INTO manga (
                        id, title, author, chapter_count, page_count, status,
                        downloaded_at, created_at, updated_at
                    ) VALUES (
                        '350234', '测试漫画', '', 2, 10, 'downloaded',
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                    )
                    """))
            connection.execute(text("""
                    INSERT INTO manga_file (
                        id, manga_id, created_at, relative_path, display_name,
                        file_type, mime_type, file_size_bytes, page_count, status,
                        updated_at
                    ) VALUES (
                        1, '350234', CURRENT_TIMESTAMP, '测试漫画.pdf', '测试漫画.pdf',
                        'pdf', 'application/pdf', 2048, 10, 'ready',
                        CURRENT_TIMESTAMP
                    )
                    """))
            connection.execute(text("""
                    INSERT INTO reading_progress (
                        manga_file_id, page_number, page_count, percent, updated_at
                    ) VALUES (1, 3, 10, 0.3, CURRENT_TIMESTAMP)
                    """))

        command.upgrade(config, "head")
        command.upgrade(config, "head")

        with engine.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one()
                == "0022_add_reading_maintenance_schema"
            )
            assert (
                connection.execute(
                    text("SELECT task_type FROM operation_task WHERE id = 'old-task'")
                ).scalar_one()
                == "download"
            )
            assert (
                connection.execute(
                    text("SELECT file_mtime FROM manga_file WHERE id = 1")
                ).scalar_one()
                is None
            )
            assert (
                connection.execute(
                    text(
                        "SELECT page_number FROM reading_progress "
                        "WHERE manga_file_id = 1"
                    )
                ).scalar_one()
                == 3
            )
            connection.execute(text("""
                    INSERT INTO operation_task (
                        id, task_type, source, status, stage, requested_by,
                        attempt_count, created_at, updated_at
                    ) VALUES (
                        'new-verify', 'verify', 'system', 'queued', 'queued', '',
                        0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                    )
                    """))
            connection.commit()
    finally:
        engine.dispose()


def test_migration_0022_rejects_nonempty_placeholder(tmp_path) -> None:
    """占位表存在数据时迁移必须停止且不留下半完成结构。"""
    database_path = tmp_path / "reject.db"
    config = _alembic_config(database_path)
    command.upgrade(config, "0021_add_operation_task_summary")

    engine = create_engine(f"sqlite:///{database_path}")
    try:
        with engine.begin() as connection:
            connection.execute(text("""
                    INSERT INTO scan_record (
                        path_key, scanned_count, added_count, updated_count,
                        missing_count, repaired_count, error_count, created_at
                    ) VALUES (
                        'MANGA_DOWNLOAD_PATH', 1, 1, 0, 0, 0, 0, CURRENT_TIMESTAMP
                    )
                    """))

        with pytest.raises(RuntimeError, match="占位表 scan_record"):
            command.upgrade(config, "head")

        with engine.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one()
                == "0021_add_operation_task_summary"
            )
            file_columns = {
                row[1]
                for row in connection.execute(text("PRAGMA table_info(manga_file)"))
            }
            assert "file_mtime" not in file_columns
            assert (
                connection.execute(
                    text("SELECT COUNT(*) FROM scan_record")
                ).scalar_one()
                == 1
            )
    finally:
        engine.dispose()


def test_migration_0022_downgrade_restores_placeholder_schema(tmp_path) -> None:
    """回退应恢复占位表结构与旧任务类型约束。"""
    database_path = tmp_path / "downgrade.db"
    config = _alembic_config(database_path)
    command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{database_path}")
    try:
        command.downgrade(config, "0021_add_operation_task_summary")
        with engine.connect() as connection:
            scan_columns = {
                row[1]
                for row in connection.execute(text("PRAGMA table_info(scan_record)"))
            }
            backup_columns = {
                row[1]
                for row in connection.execute(text("PRAGMA table_info(backup_record)"))
            }
            file_columns = {
                row[1]
                for row in connection.execute(text("PRAGMA table_info(manga_file)"))
            }
            assert {"path_key", "scanned_count", "added_count"} <= scan_columns
            assert "file_name" in backup_columns
            assert "file_mtime" not in file_columns

        # 回退后仍可重新升级
        command.upgrade(config, "head")
        with engine.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one()
                == "0022_add_reading_maintenance_schema"
            )
    finally:
        engine.dispose()
