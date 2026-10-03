"""阶段三批次 E：备份记录与一致性备份测试。"""

from datetime import datetime

import pytest

from src.database.repositories import (
    AuditEventRepository,
    BackupRepository,
    OperationTaskRepository,
    TaskEventRepository,
)
from src.service import (
    BackupConflictError,
    DatabaseMaintenanceService,
    OperationContext,
    OperationTaskService,
)
from src.utils.file_hash import sha256_of


@pytest.fixture()
def backup_repo(db_manager) -> BackupRepository:
    return BackupRepository(db_manager)


def _build_service(db_manager, backup_dir: str) -> DatabaseMaintenanceService:
    """构造备份服务及其任务依赖。"""
    task_service = OperationTaskService(
        OperationTaskRepository(db_manager),
        TaskEventRepository(db_manager),
        AuditEventRepository(db_manager),
    )
    return DatabaseMaintenanceService(
        db_manager, task_service, BackupRepository(db_manager), backup_dir=backup_dir
    )


def test_create_backup_registers_ready_record(
    tmp_path, db_manager, backup_repo
) -> None:
    """备份应生成文件并登记 ready 记录，含大小、SHA-256 与 schema 版本。"""
    service = _build_service(db_manager, str(tmp_path / "backups"))

    result = service.create_backup(
        context=OperationContext.web("admin", "203.0.113.10")
    )

    assert result.path.exists()
    assert result.path.read_bytes().startswith(b"SQLite format 3\x00")
    assert result.path.parent == (tmp_path / "backups").resolve()

    records = backup_repo.list()
    assert len(records) == 1
    record = records[0]
    assert record.filename == result.path.name
    assert record.relative_path == result.path.name
    assert record.status == "ready"
    assert record.schema_version == "0023_favorites_admin_qq"
    assert record.file_size_bytes == result.path.stat().st_size
    assert record.sha256 == sha256_of(result.path)
    assert record.deleted_at is None
    # 文件名格式：main-YYYYmmdd-HHMMSS-<revision>.db
    assert record.filename.startswith("main-")
    assert record.filename.endswith("-0023_favorites_admin_qq.db")
    assert "/" not in record.relative_path

    task = OperationTaskRepository(db_manager).list()[0]
    assert task.task_type == "backup"
    assert task.status == "succeeded"
    audit_types = {
        event.event_type for event in AuditEventRepository(db_manager).list()
    }
    assert {
        "database.backup_requested",
        "database.backup_created",
    } <= audit_types


def test_backup_failure_marks_record_and_task_failed(
    tmp_path, db_manager, backup_repo, monkeypatch
) -> None:
    """备份步骤失败时记录置 failed、任务失败且不返回虚假成功。"""

    def _fail_backup(*_args, **_kwargs):
        raise OSError("disk full")

    service = _build_service(db_manager, str(tmp_path / "backups"))
    monkeypatch.setattr(
        "src.service.database_maintenance_service.backup_database", _fail_backup
    )

    with pytest.raises(OSError, match="disk full"):
        service.create_backup()

    records = backup_repo.list()
    assert [record.status for record in records] == ["failed"]
    assert OperationTaskRepository(db_manager).list()[0].status == "failed"
    audit_types = {
        event.event_type for event in AuditEventRepository(db_manager).list()
    }
    assert "database.backup_failed" in audit_types


def test_create_backup_rejects_duplicate_within_same_second(
    tmp_path, db_manager, backup_repo, monkeypatch
) -> None:
    """同一秒重复创建应返回冲突，不产生第二条记录。"""
    fixed_time = datetime(2026, 10, 1, 12, 0, 0)
    monkeypatch.setattr(
        "src.service.database_maintenance_service.utc_now", lambda: fixed_time
    )
    service = _build_service(db_manager, str(tmp_path / "backups"))

    first = service.create_backup()
    with pytest.raises(BackupConflictError):
        service.create_backup()

    assert first.path.exists()
    assert len(backup_repo.list()) == 1
    assert OperationTaskRepository(db_manager).list()[0].status == "succeeded"


def test_backup_repository_validates_and_marks_deleted(backup_repo) -> None:
    """备份仓储应校验受控输入，并支持标记 deleted 保留记录行。"""
    with pytest.raises(ValueError, match="备份状态"):
        backup_repo.create("a.db", "a.db", "0022", status="broken")
    with pytest.raises(ValueError, match="绝对路径"):
        backup_repo.create("a.db", "/abs/a.db", "0022")
    with pytest.raises(ValueError, match="不能为空"):
        backup_repo.create("", "", "0022")

    record = backup_repo.create("b.db", "b.db", "0022")
    assert record.status == "creating"
    assert backup_repo.mark_ready(record.id, 10, "f" * 64) is True
    ready = backup_repo.get(record.id)
    assert ready is not None
    assert ready.status == "ready"
    assert ready.file_size_bytes == 10
    assert ready.sha256 == "f" * 64

    assert backup_repo.mark_deleted(record.id) is True
    deleted = backup_repo.get(record.id)
    assert deleted is not None
    assert deleted.status == "deleted"
    assert deleted.deleted_at is not None
    assert backup_repo.mark_deleted(9999) is False
    with pytest.raises(ValueError, match="备份状态"):
        backup_repo.list(status="unknown")
