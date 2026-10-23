"""数据迁移服务：导出结构、导入校验、替换与回滚测试。"""

from hashlib import sha256
import json
from pathlib import Path
import shutil
import sqlite3
from zipfile import ZipFile

import pytest

from src.database.migrations import is_ancestor_revision
from src.database.repositories import (
    AuditEventRepository,
    FavoriteRepository,
    MangaRepository,
)
from src.service.data_migration_service import DataImportError, DataMigrationService
from src.service.maintenance_lock import DATABASE_MAINTENANCE_LOCK
from src.service.operation_context import OperationContext


def _build_service(
    db_manager,
    download_path: str = "./downloads",
    db_path_config: str = "./data",
) -> DataMigrationService:
    """构造数据迁移服务，路径配置用于验证差异提示。"""
    return DataMigrationService(
        db_manager,
        AuditEventRepository(db_manager),
        db_path_config=db_path_config,
        manga_download_path=download_path,
    )


def _read_export(zip_path: Path) -> tuple[dict, bytes, str]:
    """读取导出包中的 export.json、数据库字节与文件名。"""
    with ZipFile(zip_path) as archive:
        db_name = next(
            name for name in archive.namelist() if name.lower().endswith(".db")
        )
        payload = json.loads(archive.read("export.json"))
        return payload, archive.read(db_name), db_name


def _write_zip(
    path: Path,
    payload: dict,
    db_bytes: bytes,
    db_name: str,
    extra_entries: dict[str, bytes] | None = None,
) -> Path:
    """按导出格式重新打包，供篡改与兼容性测试使用。"""
    with ZipFile(path, "w") as archive:
        archive.writestr(db_name, db_bytes)
        archive.writestr(
            "export.json",
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        )
        for name, content in (extra_entries or {}).items():
            archive.writestr(name, content)
    return path


def _db_hash(db_bytes: bytes) -> str:
    return sha256(db_bytes).hexdigest()


def _revision_db_bytes(db_path: Path, revision: str) -> bytes:
    """返回指定 schema revision 的数据库字节，用于祖先链校验。"""
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("UPDATE alembic_version SET version_num = ?", (revision,))
        connection.commit()
    finally:
        connection.close()
    return db_path.read_bytes()


def test_export_zip_contains_consistent_db_and_metadata(db_manager, tmp_path) -> None:
    """导出包应含单个 .db 与 export.json，摘要和行数均来自导出库。"""
    root = tmp_path / "downloads"
    mangas = MangaRepository(db_manager, str(root))
    mangas.upsert("100", "导出测试", "作者", 1, 10)
    FavoriteRepository(db_manager).set_favorite("web_admin", "1", "100", favorite=True)
    service = _build_service(db_manager)

    result = service.export_data(OperationContext.web("1", "127.0.0.1"))

    assert result.path.exists()
    assert result.filename.startswith("data-export-")
    assert result.filename.endswith(
        "-schema0030_add_reading_setting_prefetch_pages.zip"
    )
    assert result.file_size_bytes == result.path.stat().st_size
    assert result.schema_revision == "0030_add_reading_setting_prefetch_pages"
    with ZipFile(result.path) as archive:
        names = archive.namelist()
    assert len(names) == 2
    assert "export.json" in names
    assert next(name for name in names if name.endswith(".db")).startswith("main-")
    payload, db_bytes, db_name = _read_export(result.path)
    assert payload["format_version"] == 1
    assert payload["schema_revision"] == "0030_add_reading_setting_prefetch_pages"
    assert payload["db_filename"] == db_name
    assert payload["db_sha256"] == _db_hash(db_bytes)
    assert payload["exported_at"].endswith("Z")
    assert payload["table_counts"]["manga"] == 1
    assert payload["table_counts"]["manga_favorite"] == 1
    assert payload["table_counts"]["audit_event"] == 0
    assert payload["export_env"] == {
        "db_path": "./data",
        "manga_download_path": "./downloads",
    }

    # table_counts 必须与 zip 内数据库一致，不能取自写入导出审计后的运行库
    probe = tmp_path / "probe.db"
    probe.write_bytes(db_bytes)
    connection = sqlite3.connect(probe)
    try:
        assert connection.execute("SELECT COUNT(*) FROM manga").fetchone()[0] == 1
        assert (
            connection.execute("SELECT COUNT(*) FROM manga_favorite").fetchone()[0] == 1
        )
        assert connection.execute("SELECT COUNT(*) FROM audit_event").fetchone()[0] == 0
    finally:
        connection.close()

    audit_types = {
        event.event_type for event in AuditEventRepository(db_manager).list()
    }
    assert "data.exported" in audit_types
    shutil.rmtree(result.path.parent, ignore_errors=True)


def test_validate_import_returns_preview_and_path_warnings(
    db_manager, tmp_path
) -> None:
    """校验不替换文件、不写审计，并提示导出与当前路径差异。"""
    source_service = _build_service(db_manager)
    result = source_service.export_data()
    before_audits = len(AuditEventRepository(db_manager).list())
    target_service = _build_service(
        db_manager,
        download_path="./other-downloads",
        db_path_config="./other-data",
    )

    preview = target_service.validate_import(result.path)

    assert preview.schema_revision == "0030_add_reading_setting_prefetch_pages"
    assert preview.current_schema_revision == "0030_add_reading_setting_prefetch_pages"
    assert preview.table_counts["manga"] == 0
    assert preview.exported_at.endswith("Z")
    assert len(preview.path_warnings) == 2
    assert "导出环境下载目录为 ./downloads" in preview.path_warnings[0]
    assert "当前为 ./other-downloads" in preview.path_warnings[0]
    assert len(AuditEventRepository(db_manager).list()) == before_audits
    shutil.rmtree(result.path.parent, ignore_errors=True)


def test_is_ancestor_revision_accepts_history_and_rejects_unknown() -> None:
    """迁移图判断应接受 head 与祖先，拒绝未知或更新版本。"""
    assert is_ancestor_revision("0030_add_reading_setting_prefetch_pages") is True
    assert is_ancestor_revision("0026_manga_blacklist") is True
    assert is_ancestor_revision("9999_future_revision") is False


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing_entries", "数据包结构不正确"),
        ("extra_entry", "数据包结构不正确"),
        ("bad_sha", "校验和不一致"),
        ("bad_db", "数据库文件无法读取"),
    ],
)
def test_validate_import_rejects_invalid_packages(
    db_manager, tmp_path, mutation: str, message: str
) -> None:
    """结构、摘要与数据库可读性失败均返回统一的导入校验错误。"""
    service = _build_service(db_manager)
    result = service.export_data()
    payload, db_bytes, db_name = _read_export(result.path)
    bad_zip = tmp_path / "bad.zip"

    if mutation == "missing_entries":
        with ZipFile(bad_zip, "w") as archive:
            archive.writestr(db_name, db_bytes)
    elif mutation == "extra_entry":
        _write_zip(bad_zip, payload, db_bytes, db_name, {"extra.txt": b"extra"})
    elif mutation == "bad_sha":
        payload["db_sha256"] = "0" * 64
        _write_zip(bad_zip, payload, db_bytes, db_name)
    else:
        bad_db = b"not a sqlite database"
        payload["db_sha256"] = _db_hash(bad_db)
        _write_zip(bad_zip, payload, bad_db, db_name)

    with pytest.raises(DataImportError, match=message) as error:
        service.validate_import(bad_zip)
    assert error.value.error_code == "DATA_IMPORT_INVALID"
    assert error.value.status_code == 400
    shutil.rmtree(result.path.parent, ignore_errors=True)


def test_validate_import_accepts_ancestor_and_rejects_newer_schema(
    db_manager, tmp_path
) -> None:
    """旧 revision 属于当前 head 祖先时接受，未知/更新 revision 拒绝。"""
    service = _build_service(db_manager)
    result = service.export_data()
    payload, db_bytes, db_name = _read_export(result.path)
    extracted = tmp_path / "extracted.db"
    extracted.write_bytes(db_bytes)

    ancestor_bytes = _revision_db_bytes(extracted, "0026_manga_blacklist")
    payload["schema_revision"] = "0026_manga_blacklist"
    payload["db_sha256"] = _db_hash(ancestor_bytes)
    ancestor_zip = _write_zip(
        tmp_path / "ancestor.zip", payload, ancestor_bytes, db_name
    )
    preview = service.validate_import(ancestor_zip)
    assert preview.schema_revision == "0026_manga_blacklist"

    newer_bytes = _revision_db_bytes(extracted, "9999_future_revision")
    payload["schema_revision"] = "9999_future_revision"
    payload["db_sha256"] = _db_hash(newer_bytes)
    newer_zip = _write_zip(tmp_path / "newer.zip", payload, newer_bytes, db_name)
    with pytest.raises(DataImportError, match="不兼容的版本"):
        service.validate_import(newer_zip)
    shutil.rmtree(result.path.parent, ignore_errors=True)


def test_validate_import_rejects_table_count_mismatch(db_manager, tmp_path) -> None:
    """export.json 行数与数据库实际行数不一致时拒绝导入。"""
    service = _build_service(db_manager)
    result = service.export_data()
    payload, db_bytes, db_name = _read_export(result.path)
    payload["table_counts"]["manga"] = 99
    bad_zip = _write_zip(tmp_path / "counts.zip", payload, db_bytes, db_name)

    with pytest.raises(DataImportError, match="行数与 export.json 不一致"):
        service.validate_import(bad_zip)
    shutil.rmtree(result.path.parent, ignore_errors=True)


def test_apply_import_replaces_database_backs_up_and_writes_audit(
    db_manager, tmp_path
) -> None:
    """确认导入后替换整库、保留旧库备份，并在旧库写入导入审计。"""
    root = tmp_path / "downloads"
    mangas = MangaRepository(db_manager, str(root))
    mangas.upsert("100", "导出时漫画", "作者", 1, 10)
    service = _build_service(db_manager)
    result = service.export_data()
    original_mode = Path(db_manager.db_file).stat().st_mode

    mangas.upsert("200", "导入前新增", "作者", 1, 10)
    service.apply_import(result.path, OperationContext.web("1", "127.0.0.1"))

    reloaded = MangaRepository(db_manager, str(root))
    assert reloaded.get("100") is not None
    assert reloaded.get("100").title == "导出时漫画"
    assert reloaded.get("200") is None
    assert Path(db_manager.db_file).stat().st_mode == original_mode

    backup_path = next(Path(db_manager.db_dir).glob("main.db.pre-import-*.bak"))
    connection = sqlite3.connect(backup_path)
    try:
        mangas_in_backup = connection.execute(
            "SELECT id FROM manga ORDER BY id"
        ).fetchall()
        audit_events = connection.execute(
            "SELECT event_type, result FROM audit_event ORDER BY id"
        ).fetchall()
    finally:
        connection.close()
    assert mangas_in_backup == [("100",), ("200",)]
    assert ("data.imported", "accepted") in audit_events
    shutil.rmtree(result.path.parent, ignore_errors=True)


def test_apply_import_revalidates_after_validate(db_manager, tmp_path) -> None:
    """apply 不信任上一次校验结果，文件被替换后必须拒绝。"""
    mangas = MangaRepository(db_manager, str(tmp_path / "downloads"))
    mangas.upsert("100", "原始漫画", "作者", 1, 10)
    service = _build_service(db_manager)
    result = service.export_data()
    payload, db_bytes, db_name = _read_export(result.path)
    assert service.validate_import(result.path).schema_revision

    bad_db = b"tampered database"
    payload["db_sha256"] = _db_hash(bad_db)
    bad_zip = _write_zip(tmp_path / "tampered.zip", payload, bad_db, db_name)

    with pytest.raises(DataImportError, match="数据库文件无法读取"):
        service.apply_import(bad_zip)
    assert mangas.get("100") is not None
    assert mangas.get("100").title == "原始漫画"
    shutil.rmtree(result.path.parent, ignore_errors=True)


def test_apply_import_restores_old_database_when_replace_fails(
    db_manager, tmp_path, monkeypatch
) -> None:
    """替换阶段异常时自动恢复旧库，服务可继续读取旧数据。"""
    mangas = MangaRepository(db_manager, str(tmp_path / "downloads"))
    mangas.upsert("100", "导出时漫画", "作者", 1, 10)
    service = _build_service(db_manager)
    result = service.export_data()
    mangas.upsert("200", "导入前新增", "作者", 1, 10)

    def fail_replace(*_args, **_kwargs):
        raise OSError("模拟替换失败")

    monkeypatch.setattr("src.service.data_migration_service.os.replace", fail_replace)

    with pytest.raises(DataImportError, match="已自动恢复旧数据库") as error:
        service.apply_import(result.path)
    assert error.value.status_code == 500
    assert mangas.get("100").title == "导出时漫画"
    assert mangas.get("200").title == "导入前新增"
    assert next(Path(db_manager.db_dir).glob("main.db.pre-import-*.bak"))
    shutil.rmtree(result.path.parent, ignore_errors=True)


def test_apply_import_rejects_when_maintenance_lock_is_held(
    db_manager, tmp_path
) -> None:
    """并发维护操作持锁时导入直接返回冲突，不触碰数据库。"""
    mangas = MangaRepository(db_manager, str(tmp_path / "downloads"))
    mangas.upsert("100", "原始漫画", "作者", 1, 10)
    service = _build_service(db_manager)

    assert DATABASE_MAINTENANCE_LOCK.acquire(blocking=False)
    try:
        with pytest.raises(DataImportError) as error:
            service.apply_import(b"not-used-because-lock-first")
    finally:
        DATABASE_MAINTENANCE_LOCK.release()

    assert error.value.error_code == "DATA_IMPORT_CONFLICT"
    assert error.value.status_code == 409
    assert mangas.get("100").title == "原始漫画"
