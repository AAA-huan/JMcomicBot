"""阶段三批次 D：文件校验服务测试。"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import hashlib
import json

import pytest

from src.database.models import Manga, MangaFile, utc_now
from src.database.repositories import (
    AuditEventRepository,
    MangaRepository,
    OperationTaskRepository,
    ScanRecordRepository,
    TaskEventRepository,
)
from src.service import OperationTaskService, VerifyService


def _sha256(data: bytes) -> str:
    """计算字节内容的 SHA-256 十六进制摘要。"""
    return hashlib.sha256(data).hexdigest()


def _utc_mtime(path: Path) -> datetime:
    """按数据库 UTC 语义读取文件修改时间。"""
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).replace(
        tzinfo=None
    )


@dataclass
class VerifyEnv:
    """校验测试环境，聚合服务、仓储与下载根目录。"""

    service: VerifyService
    manga_repo: MangaRepository
    scan_record_repo: ScanRecordRepository
    task_repo: OperationTaskRepository
    event_repo: TaskEventRepository
    audit_repo: AuditEventRepository
    download_root: Path


@pytest.fixture()
def verify_env(db_manager, tmp_path) -> VerifyEnv:
    """构造下载根目录与校验服务依赖。"""
    download_root = tmp_path / "downloads"
    download_root.mkdir()
    manga_repo = MangaRepository(db_manager, download_root=str(download_root))
    scan_record_repo = ScanRecordRepository(db_manager)
    task_repo = OperationTaskRepository(db_manager)
    event_repo = TaskEventRepository(db_manager)
    audit_repo = AuditEventRepository(db_manager)
    service = VerifyService(
        manga_repo,
        scan_record_repo,
        OperationTaskService(task_repo, event_repo, audit_repo),
        download_root=str(download_root),
    )
    return VerifyEnv(
        service=service,
        manga_repo=manga_repo,
        scan_record_repo=scan_record_repo,
        task_repo=task_repo,
        event_repo=event_repo,
        audit_repo=audit_repo,
        download_root=download_root,
    )


def _create_file(
    env: VerifyEnv,
    manga_id: str,
    relative_path: str,
    status: str = "ready",
    file_size_bytes: int = 0,
    sha256: Optional[str] = None,
    file_mtime: Optional[datetime] = None,
) -> int:
    """插入测试用漫画与 PDF 记录，返回 PDF 文件ID。"""
    now = utc_now()
    with env.manga_repo.db_manager.get_session() as session:
        session.add(
            Manga(
                id=manga_id,
                title=f"测试漫画{manga_id}",
                author="",
                chapter_count=1,
                page_count=1,
                status="downloaded",
                downloaded_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        session.flush()
        manga_file = MangaFile(
            manga_id=manga_id,
            relative_path=relative_path,
            display_name=Path(relative_path).name,
            file_type="pdf",
            mime_type="application/pdf",
            file_size_bytes=file_size_bytes,
            page_count=1,
            sha256=sha256,
            file_mtime=file_mtime,
            status=status,
            created_at=now,
            updated_at=now,
        )
        session.add(manga_file)
        session.commit()
        session.refresh(manga_file)
        return manga_file.id


def _stored_file(env: VerifyEnv, manga_id: str) -> MangaFile:
    """读取指定漫画的 PDF 记录。"""
    manga = env.manga_repo.get(manga_id)
    assert manga is not None
    assert len(manga.files) == 1
    return manga.files[0]


def test_first_verify_records_hash_and_task_records(verify_env: VerifyEnv) -> None:
    """首次校验应写入大小、mtime 与 SHA-256，并产生任务、审计和统计。"""
    data = b"%PDF-1.4 fake pdf content"
    relative_path = "1001-漫画(1章).pdf"
    (verify_env.download_root / relative_path).write_bytes(data)
    _create_file(verify_env, "1001", relative_path)

    result = verify_env.service.verify()

    assert result.file_count == 1
    assert result.ready_count == 1
    stored = _stored_file(verify_env, "1001")
    assert stored.status == "ready"
    assert stored.sha256 == _sha256(data)
    assert stored.file_size_bytes == len(data)
    assert stored.file_mtime == _utc_mtime(verify_env.download_root / relative_path)
    assert stored.last_verified_at is not None

    task = verify_env.task_repo.list()[0]
    assert task.task_type == "verify"
    assert task.status == "succeeded"
    event_types = [event.event_type for event in verify_env.event_repo.list(task.id)]
    assert event_types[0] == "verify.requested"
    assert "verify.progress" in event_types
    assert "verify.completed" in event_types
    audit_types = {event.event_type for event in verify_env.audit_repo.list()}
    assert {"library.verify_requested", "library.verify_completed"} <= audit_types

    records = verify_env.scan_record_repo.list()
    assert len(records) == 1
    assert records[0].task_id == task.id
    assert records[0].task_type == "verify"
    assert records[0].file_count == 1
    assert records[0].corrupted_count == 0


def test_matching_hash_stays_ready(verify_env: VerifyEnv) -> None:
    """已登记摘要与磁盘一致时应保持 ready 并刷新验证时间。"""
    data = b"%PDF-1.4 stable content"
    relative_path = "1002.pdf"
    path = verify_env.download_root / relative_path
    path.write_bytes(data)
    _create_file(
        verify_env,
        "1002",
        relative_path,
        file_size_bytes=len(data),
        sha256=_sha256(data),
        file_mtime=_utc_mtime(path),
    )

    result = verify_env.service.verify()

    assert result.ready_count == 1
    stored = _stored_file(verify_env, "1002")
    assert stored.status == "ready"
    assert stored.sha256 == _sha256(data)
    assert stored.last_verified_at is not None


def test_hash_mismatch_marks_corrupted(verify_env: VerifyEnv) -> None:
    """大小与 mtime 未变但摘要不符时应标记 corrupted 且保留旧摘要。"""
    data = b"%PDF-1.4 tampered content"
    relative_path = "1003.pdf"
    path = verify_env.download_root / relative_path
    path.write_bytes(data)
    wrong_sha = "0" * 64
    _create_file(
        verify_env,
        "1003",
        relative_path,
        file_size_bytes=len(data),
        sha256=wrong_sha,
        file_mtime=_utc_mtime(path),
    )

    result = verify_env.service.verify()

    assert result.corrupted_count == 1
    stored = _stored_file(verify_env, "1003")
    assert stored.status == "corrupted"
    assert stored.sha256 == wrong_sha
    assert stored.last_verified_at is None

    task = verify_env.task_repo.list()[0]
    completed = next(
        event
        for event in verify_env.event_repo.list(task.id)
        if event.event_type == "verify.completed"
    )
    assert json.loads(completed.metadata_json)["corrupted_count"] == 1
    assert verify_env.scan_record_repo.list()[0].corrupted_count == 1


def test_size_change_rebaselines_hash(verify_env: VerifyEnv) -> None:
    """文件大小变化时应更新字节数并重新计算摘要，不误报损坏。"""
    data = b"%PDF-1.4 replaced content with new size"
    relative_path = "1004.pdf"
    path = verify_env.download_root / relative_path
    path.write_bytes(data)
    _create_file(
        verify_env,
        "1004",
        relative_path,
        file_size_bytes=10,
        sha256="f" * 64,
        file_mtime=_utc_mtime(path),
    )

    result = verify_env.service.verify()

    assert result.ready_count == 1
    stored = _stored_file(verify_env, "1004")
    assert stored.status == "ready"
    assert stored.file_size_bytes == len(data)
    assert stored.sha256 == _sha256(data)
    assert stored.file_mtime == _utc_mtime(path)


def test_mtime_change_rebaselines_hash(verify_env: VerifyEnv) -> None:
    """文件修改时间变化时应更新 mtime 并重新计算摘要。"""
    data = b"%PDF-1.4 mtime changed"
    relative_path = "1005.pdf"
    path = verify_env.download_root / relative_path
    path.write_bytes(data)
    _create_file(
        verify_env,
        "1005",
        relative_path,
        file_size_bytes=len(data),
        sha256="f" * 64,
        file_mtime=_utc_mtime(path) - timedelta(days=1),
    )

    result = verify_env.service.verify()

    assert result.ready_count == 1
    stored = _stored_file(verify_env, "1005")
    assert stored.status == "ready"
    assert stored.file_mtime == _utc_mtime(path)
    assert stored.sha256 == _sha256(data)


def test_missing_file_marks_manga_missing(verify_env: VerifyEnv) -> None:
    """磁盘无文件时应标记文件与漫画缺失，不删除记录。"""
    _create_file(verify_env, "1006", "1006.pdf")

    result = verify_env.service.verify()

    assert result.missing_count == 1
    manga = verify_env.manga_repo.get("1006")
    assert manga is not None
    assert manga.status == "missing_file"
    assert manga.files[0].status == "missing"


def test_verify_restores_manga_status_when_file_returns(
    verify_env: VerifyEnv,
) -> None:
    """文件恢复且校验通过时，漫画状态应从 missing_file 恢复为 downloaded。"""
    data = b"%PDF-1.4 restored content"
    relative_path = "1006.pdf"
    _create_file(verify_env, "1006", relative_path)

    first = verify_env.service.verify()
    assert first.missing_count == 1
    assert verify_env.manga_repo.get("1006").status == "missing_file"

    # 用户恢复文件后再次校验，文件与漫画状态都应恢复正常
    (verify_env.download_root / relative_path).write_bytes(data)
    second = verify_env.service.verify()

    assert second.ready_count == 1
    manga = verify_env.manga_repo.get("1006")
    assert manga is not None
    assert manga.status == "downloaded"
    assert manga.files[0].status == "ready"
    assert manga.files[0].sha256 == _sha256(data)


def test_invalid_paths_are_rejected(verify_env: VerifyEnv) -> None:
    """越界路径、非 PDF 后缀和目录都应标记 invalid_path。"""
    # 越界路径：解析后位于下载根目录之外
    escape_id = _create_file(verify_env, "1007", "../escape.pdf")
    # 非 PDF 后缀
    (verify_env.download_root / "note.txt").write_bytes(b"not a pdf")
    text_id = _create_file(verify_env, "1008", "note.txt")
    # 目录冒充 PDF
    (verify_env.download_root / "dir.pdf").mkdir()
    dir_id = _create_file(verify_env, "1009", "dir.pdf")

    result = verify_env.service.verify()

    assert result.invalid_path_count == 3
    with verify_env.manga_repo.db_manager.get_session() as session:
        statuses = {
            session.get(MangaFile, file_id).status
            for file_id in (escape_id, text_id, dir_id)
        }
    assert statuses == {"invalid_path"}


def test_verify_scope_and_unknown_manga(verify_env: VerifyEnv) -> None:
    """--id 范围校验只处理指定漫画；未知漫画明确报错并使任务失败。"""
    (verify_env.download_root / "2001.pdf").write_bytes(b"%PDF one")
    _create_file(verify_env, "2001", "2001.pdf")
    _create_file(verify_env, "2002", "2002.pdf")

    result = verify_env.service.verify(["2001"])

    assert result.file_count == 1
    assert result.ready_count == 1
    assert _stored_file(verify_env, "2001").status == "ready"
    # 未指定漫画的状态不变
    assert _stored_file(verify_env, "2002").status == "ready"
    assert _stored_file(verify_env, "2002").last_verified_at is None

    with pytest.raises(ValueError, match="漫画不存在"):
        verify_env.service.verify(["missing-id"])
    assert verify_env.task_repo.list()[0].status == "failed"
    audit_types = {event.event_type for event in verify_env.audit_repo.list()}
    assert "library.verify_failed" in audit_types


def test_no_files_does_not_fake_progress(verify_env: VerifyEnv) -> None:
    """没有任何文件时应正常完成，且不伪造进度事件。"""
    result = verify_env.service.verify()

    assert result.file_count == 0
    task = verify_env.task_repo.list()[0]
    event_types = [event.event_type for event in verify_env.event_repo.list(task.id)]
    assert "verify.progress" not in event_types
    assert verify_env.scan_record_repo.list()[0].file_count == 0


def test_missing_download_root_fails_fast(verify_env: VerifyEnv) -> None:
    """下载根目录不存在时应在创建任务前明确报错。"""
    verify_env.download_root.rmdir()

    with pytest.raises(FileNotFoundError, match="下载根目录不存在"):
        verify_env.service.verify()
    assert verify_env.task_repo.list() == []
