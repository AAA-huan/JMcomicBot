"""过期数据清理应用服务测试。"""

from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import update
import pytest

from src.database.models import AuditEvent, utc_now
from src.database.repositories import (
    AuditEventRepository,
    BackupRepository,
    OperationTaskRepository,
)
from src.service import CleanupService


def _build_service(db_manager, tmp_path) -> tuple[
    CleanupService,
    OperationTaskRepository,
    AuditEventRepository,
    BackupRepository,
    Path,
]:
    """构造清理服务并返回其依赖。"""
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    task_repo = OperationTaskRepository(db_manager)
    audit_repo = AuditEventRepository(db_manager)
    backup_repo = BackupRepository(db_manager)
    service = CleanupService(
        task_repo,
        audit_repo,
        backup_repo,
        backup_dir=str(backup_dir),
    )
    return service, task_repo, audit_repo, backup_repo, backup_dir


def _create_backup(
    backup_repo: BackupRepository,
    backup_dir: Path,
    name: str,
    size: int,
    created_at: datetime,
):
    """创建 ready 备份记录与对应文件，大小写入记录。"""
    (backup_dir / name).write_bytes(b"x" * size)
    record = backup_repo.create(name, name, "0022", created_at=created_at)
    backup_repo.mark_ready(record.id, size, "f" * 64)
    return backup_repo.get(record.id)


def test_cleanup_removes_expired_and_records_audit(db_manager, tmp_path) -> None:
    """cleanup 应清理过期任务与审计，并记录清理审计。"""
    service, task_repo, audit_repo, _backup_repo, _backup_dir = _build_service(
        db_manager, tmp_path
    )

    old_task = task_repo.create("download", "qq", "10001")
    with db_manager.get_session() as session:
        stored = session.get(type(old_task), old_task.id)
        stored.status = "succeeded"
        stored.finished_at = utc_now() - timedelta(days=200)
        session.commit()
    audit_repo.record(event_type="download.completed", source="qq", result="succeeded")
    with db_manager.get_session() as session:
        session.execute(
            update(AuditEvent).values(created_at=utc_now() - timedelta(days=400))
        )
        session.commit()

    removed = service.cleanup(now=utc_now())

    assert removed == 2
    assert task_repo.get(old_task.id) is None
    remaining_types = {event.event_type for event in audit_repo.list()}
    assert "maintenance.cleanup_completed" in remaining_types


def test_cleanup_backups_enforces_count_limit(
    db_manager, tmp_path, monkeypatch
) -> None:
    """备份数量超过上限时应删除最旧文件并标记 deleted，保留最新一份。"""
    service, _task_repo, _audit_repo, backup_repo, backup_dir = _build_service(
        db_manager, tmp_path
    )
    monkeypatch.setattr("src.service.cleanup_service.BACKUP_KEEP_COUNT", 3)
    monkeypatch.setattr("src.service.cleanup_service.BACKUP_MAX_TOTAL_BYTES", 10**9)
    base = utc_now() - timedelta(hours=10)
    records = [
        _create_backup(
            backup_repo,
            backup_dir,
            f"main-{index}.db",
            10,
            base + timedelta(hours=index),
        )
        for index in range(5)
    ]

    removed = service.cleanup()

    assert removed == 2
    for record in records[:2]:
        stored = backup_repo.get(record.id)
        assert stored.status == "deleted"
        assert stored.deleted_at is not None
        assert not (backup_dir / record.relative_path).exists()
    for record in records[2:]:
        stored = backup_repo.get(record.id)
        assert stored.status == "ready"
        assert (backup_dir / record.relative_path).exists()


def test_cleanup_backups_enforces_size_limit_and_keeps_newest(
    db_manager, tmp_path, monkeypatch
) -> None:
    """备份总量超过空间上限时从最旧开始删除，但永远保留最新一份。"""
    service, _task_repo, _audit_repo, backup_repo, backup_dir = _build_service(
        db_manager, tmp_path
    )
    monkeypatch.setattr("src.service.cleanup_service.BACKUP_KEEP_COUNT", 10)
    monkeypatch.setattr("src.service.cleanup_service.BACKUP_MAX_TOTAL_BYTES", 10)
    base = utc_now() - timedelta(hours=10)
    records = [
        _create_backup(
            backup_repo,
            backup_dir,
            f"main-{index}.db",
            4,
            base + timedelta(hours=index),
        )
        for index in range(4)
    ]

    removed = service.cleanup()

    # 16 字节 > 10 字节，从最旧删除 2 份后剩余 8 字节
    assert removed == 2
    assert backup_repo.get(records[0].id).status == "deleted"
    assert backup_repo.get(records[1].id).status == "deleted"
    assert backup_repo.get(records[2].id).status == "ready"
    assert backup_repo.get(records[3].id).status == "ready"
    assert (backup_dir / records[3].relative_path).exists()

    # 单份就超过上限时也不删除最新一份
    monkeypatch.setattr("src.service.cleanup_service.BACKUP_MAX_TOTAL_BYTES", 1)
    newest_records = [
        _create_backup(backup_repo, backup_dir, f"new-{index}.db", 10, utc_now())
        for index in range(2)
    ]
    removed = service.cleanup()
    assert removed >= 1
    assert backup_repo.get(newest_records[-1].id).status == "ready"
    assert (backup_dir / newest_records[-1].relative_path).exists()


def test_cleanup_rejects_backup_path_escape(db_manager, tmp_path, monkeypatch) -> None:
    """备份记录路径越过备份目录时必须停止清理，不删除目录外文件。"""
    service, _task_repo, _audit_repo, backup_repo, backup_dir = _build_service(
        db_manager, tmp_path
    )
    monkeypatch.setattr("src.service.cleanup_service.BACKUP_KEEP_COUNT", 1)
    monkeypatch.setattr("src.service.cleanup_service.BACKUP_MAX_TOTAL_BYTES", 10**9)
    outside_file = tmp_path / "escape.db"
    outside_file.write_bytes(b"outside")
    malicious = backup_repo.create(
        "escape.db",
        "../escape.db",
        "0022",
        status="ready",
        created_at=utc_now() - timedelta(hours=2),
    )
    _create_backup(backup_repo, backup_dir, "newest.db", 1, utc_now())

    with pytest.raises(RuntimeError, match="越过备份目录"):
        service.cleanup()

    assert outside_file.exists()
    assert backup_repo.get(malicious.id).status == "ready"
