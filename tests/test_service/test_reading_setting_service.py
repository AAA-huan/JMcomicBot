"""阅读设置应用服务测试：默认值、校验、部分更新与审计。"""

import json

from src.database.database import DatabaseManager
from src.database.repositories import (
    AuditEventRepository,
    ReadingSettingRepository,
    WebAdminRepository,
)
from src.service import OperationContext, ReadingSettingService


def _build_service(db_manager: DatabaseManager) -> ReadingSettingService:
    """创建管理员并构造阅读设置服务。"""
    WebAdminRepository(db_manager).create("password-hash")
    return ReadingSettingService(
        ReadingSettingRepository(db_manager),
        AuditEventRepository(db_manager),
    )


def test_get_or_default_does_not_persist(db_manager) -> None:
    """未保存时返回全默认值且不创建数据库记录。"""
    service = _build_service(db_manager)
    setting = service.get_or_default(1)

    assert setting.reading_mode == "normal"
    assert setting.continuous is False
    assert setting.click_to_turn is False
    assert setting.reverse_click is False
    assert setting.dark_background is False
    assert setting.updated_at is not None
    assert ReadingSettingRepository(db_manager).get(1) is None


def test_upsert_partial_update_preserves_existing_fields(db_manager) -> None:
    """只更新传入字段，其余字段保留原值。"""
    service = _build_service(db_manager)
    service.upsert(
        1,
        {
            "reading_mode": "manga",
            "continuous": True,
            "click_to_turn": True,
            "reverse_click": True,
            "dark_background": True,
        },
        OperationContext.web("1", "127.0.0.1"),
    )

    updated = service.upsert(
        1,
        {"dark_background": False},
        OperationContext.web("1", "127.0.0.1"),
    )
    assert updated.reading_mode == "manga"
    assert updated.continuous is True
    assert updated.click_to_turn is True
    assert updated.reverse_click is True
    assert updated.dark_background is False

    events = AuditEventRepository(db_manager).list(page_size=20)
    assert [event.event_type for event in events[:2]] == [
        "reader.setting_changed",
        "reader.setting_changed",
    ]
    metadata = json.loads(events[0].metadata_json or "{}")
    assert metadata == {"changed_fields": ["dark_background"]}
    assert events[0].source == "web"
    assert events[0].target_type == "reading_setting"
    assert events[0].target_id == "1"


def test_upsert_rejects_invalid_values_without_writing(db_manager) -> None:
    """非法模式、类型、未知字段与反转依赖均应在写库前拒绝。"""
    service = _build_service(db_manager)

    cases = [
        {"reading_mode": "single"},
        {"continuous": "yes"},
        {"unknown": True},
        {"click_to_turn": False, "reverse_click": True},
    ]
    for payload in cases:
        try:
            service.upsert(1, payload, OperationContext.web("1", "127.0.0.1"))
        except ValueError:
            continue
        raise AssertionError(f"应当拒绝非法设置: {payload}")

    assert ReadingSettingRepository(db_manager).get(1) is None
    assert AuditEventRepository(db_manager).list(page_size=20) == []


def test_upsert_empty_payload_returns_current_without_audit(db_manager) -> None:
    """空更新请求不创建记录，也不写审计。"""
    service = _build_service(db_manager)
    setting = service.upsert(1, {}, OperationContext.web("1", "127.0.0.1"))

    assert setting.reading_mode == "normal"
    assert ReadingSettingRepository(db_manager).get(1) is None
    assert AuditEventRepository(db_manager).list(page_size=20) == []
