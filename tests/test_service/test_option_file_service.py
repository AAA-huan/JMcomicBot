"""option.yml 网页编辑服务测试：读取、校验、原子保存与审计。"""

from pathlib import Path

import pytest

from src.database.repositories import AuditEventRepository
from src.service.operation_context import OperationContext
from src.service.option_file_service import (
    OPTION_FILE_MAX_BYTES,
    OptionFileService,
)


def _build_service(tmp_path: Path) -> OptionFileService:
    """构造指向临时目录 option.yml 的服务实例。"""
    return OptionFileService(
        option_file_path=str(tmp_path / "option.yml"),
        audit_repository=AuditEventRepository(_db_manager_for(tmp_path)),
    )


def _db_manager_for(tmp_path: Path):
    """为审计仓储构造临时数据库管理器。"""
    from src.database.database import DatabaseManager

    db = DatabaseManager(db_path=str(tmp_path / "data"), echo=False)
    db.init_db()
    return db


def test_read_returns_empty_when_file_missing(tmp_path: Path) -> None:
    """文件不存在时返回空串，不抛错。"""
    service = _build_service(tmp_path)
    assert service.read() == ""


def test_write_creates_file_and_persists_content(tmp_path: Path) -> None:
    """保存后文件存在且内容一致。"""
    service = _build_service(tmp_path)
    content = "download:\n  image:\n    suffix: .jpg\n"
    service.write(content, OperationContext.web("1", "127.0.0.1"))
    assert service.read() == content
    assert (tmp_path / "option.yml").read_text(encoding="utf-8") == content


def test_write_rejects_non_dict_yaml(tmp_path: Path) -> None:
    """顶层不是字典时明确报错。"""
    service = _build_service(tmp_path)
    with pytest.raises(ValueError, match="顶层必须是字典"):
        service.write("- item1\n- item2\n")
    with pytest.raises(ValueError, match="顶层必须是字典"):
        service.write("just a string\n")


def test_write_rejects_empty_content(tmp_path: Path) -> None:
    """空内容（None 或纯空白）应明确拒绝，避免误清空 option.yml。"""
    service = _build_service(tmp_path)
    with pytest.raises(ValueError, match="不能为空"):
        service.write(None)
    with pytest.raises(ValueError, match="不能为空"):
        service.write("")
    with pytest.raises(ValueError, match="不能为空"):
        service.write("   \n  \t  \n")
    assert not (tmp_path / "option.yml").exists()


def test_write_rejects_invalid_yaml(tmp_path: Path) -> None:
    """非法 YAML 明确报错。"""
    service = _build_service(tmp_path)
    with pytest.raises(ValueError, match="不是合法 YAML"):
        service.write("download: [unterminated\n")


def test_write_rejects_oversize_content(tmp_path: Path) -> None:
    """超过大小上限时明确报错且不落盘。"""
    service = _build_service(tmp_path)
    oversized = "key: " + "x" * (OPTION_FILE_MAX_BYTES + 10)
    with pytest.raises(ValueError, match="超过大小上限"):
        service.write(oversized)
    assert not (tmp_path / "option.yml").exists()


def test_write_records_audit_event(tmp_path: Path) -> None:
    """保存成功后写一条 setting.changed 审计，target_id=option.yml。"""
    db_manager = _db_manager_for(tmp_path)
    service = OptionFileService(
        option_file_path=str(tmp_path / "option.yml"),
        audit_repository=AuditEventRepository(db_manager),
    )
    service.write("download:\n  dir:\n    base: ./downloads\n")
    events = AuditEventRepository(db_manager).list()
    assert len(events) == 1
    assert events[0].event_type == "setting.changed"
    assert events[0].target_id == "option.yml"
    assert events[0].target_type == "setting"


def test_write_is_atomic_on_yaml_error(tmp_path: Path) -> None:
    """校验失败时不创建文件、不留临时文件。"""
    service = _build_service(tmp_path)
    with pytest.raises(ValueError):
        service.write("not: {valid yaml")
    assert not (tmp_path / "option.yml").exists()
    # 临时文件应被清理
    leftovers = [p for p in tmp_path.iterdir() if p.name.startswith(".option.yml-")]
    assert leftovers == []


def test_write_overwrites_existing_atomically(tmp_path: Path) -> None:
    """覆盖已有文件时不出现半写状态。"""
    service = _build_service(tmp_path)
    service.write("download:\n  image:\n    suffix: .jpg\n")
    service.write("download:\n  image:\n    suffix: .png\n")
    assert "suffix: .png" in service.read()
    assert "suffix: .jpg" not in service.read()
