"""运行时配置应用服务测试。"""

from typing import Any, Callable, Dict

import pytest

from src.database.repositories import (
    AuditEventRepository,
    SettingHistoryRepository,
    SettingRepository,
)
from src.service import OperationContext, SettingsService
from src.service.settings_service import EFFECT_IMMEDIATE, SETTING_DEFINITIONS


class _ConfigManager:
    """仅保存配置字典的测试替身，行为与 ConfigManager.config_dict 一致。"""

    def __init__(self, config_dict: Dict[str, Any] | None = None) -> None:
        self.config_dict: Dict[str, Any] = dict(config_dict or {})


def _editable_keys() -> set[str]:
    """注册表中所有可编辑且立即生效的键。"""
    return {
        definition.key
        for definition in SETTING_DEFINITIONS
        if definition.editable and definition.effect == EFFECT_IMMEDIATE
    }


def _build_service(
    db_manager, config_dict: Dict[str, Any] | None = None
) -> tuple[SettingsService, Dict[str, Any]]:
    """构造配置服务并注册记录调用的测试应用接口。"""
    service = SettingsService(
        SettingRepository(db_manager),
        SettingHistoryRepository(db_manager),
        AuditEventRepository(db_manager),
        _ConfigManager(config_dict),  # type: ignore[arg-type]
    )
    applied: Dict[str, Any] = {}

    def make_applier(key: str) -> Callable[[Any], None]:
        def apply(value: Any) -> None:
            applied[key] = value

        return apply

    service.register_appliers({key: make_applier(key) for key in _editable_keys()})
    return service, applied


def _find_view(service: SettingsService, key: str):
    return next(view for view in service.list() if view.key == key)


def test_list_masks_sensitive_values(db_manager) -> None:
    """敏感配置只显示是否已设置，永不回显真实值。"""
    service, _applied = _build_service(
        db_manager, {"NAPCAT_TOKEN": "super-secret-token"}
    )

    views = service.list()
    token_view = _find_view(service, "NAPCAT_TOKEN")

    assert token_view.sensitive is True
    assert token_view.value is None
    assert token_view.is_set is True
    assert "super-secret-token" not in repr(views)


def test_update_persists_applies_and_audits(db_manager) -> None:
    """修改配置应调用显式接口、落库并写审计与脱敏历史。"""
    service, applied = _build_service(db_manager, {"FILE_SEND_INTERVAL": 1.8})

    view = service.update(
        "FILE_SEND_INTERVAL", 2.5, OperationContext.web("1", "127.0.0.1")
    )

    assert view.value == 2.5
    assert applied["FILE_SEND_INTERVAL"] == 2.5
    assert service.config_manager.config_dict["FILE_SEND_INTERVAL"] == 2.5
    assert SettingRepository(db_manager).get_optional("FILE_SEND_INTERVAL") == "2.5"

    history = SettingHistoryRepository(db_manager).list()
    assert len(history) == 1
    assert history[0].key == "FILE_SEND_INTERVAL"
    assert history[0].old_value_masked == "1.8"
    assert history[0].new_value_masked == "2.5"
    assert history[0].source == "web"
    assert history[0].changed_by == "1"

    audit_events = AuditEventRepository(db_manager).list()
    assert len(audit_events) == 1
    assert audit_events[0].event_type == "setting.changed"
    assert audit_events[0].target_id == "FILE_SEND_INTERVAL"


def test_update_rejects_invalid_values_and_readonly_keys(db_manager) -> None:
    """越界、类型错误、未知键与只读键都必须明确报错。"""
    service, applied = _build_service(db_manager, {"FILE_SEND_INTERVAL": 1.8})

    with pytest.raises(ValueError, match="不能小于"):
        service.update("FILE_SEND_INTERVAL", 0.01)
    with pytest.raises(ValueError, match="需要数字"):
        service.update("FILE_SEND_INTERVAL", True)
    with pytest.raises(ValueError, match="需要整数"):
        service.update("FILE_SEND_BATCH_SIZE", 2.5)
    with pytest.raises(ValueError, match="不支持的配置项"):
        service.update("NOT_EXIST", 1)
    with pytest.raises(ValueError, match="不允许在 WebUI 修改"):
        service.update("NAPCAT_TOKEN", "leak")

    assert applied == {}
    assert SettingHistoryRepository(db_manager).list() == []


def test_update_without_change_does_not_write_history(db_manager) -> None:
    """值与当前有效值一致时不写库、不写历史、不调用应用接口。"""
    service, applied = _build_service(db_manager, {"FILE_SEND_INTERVAL": 1.8})

    view = service.update("FILE_SEND_INTERVAL", 1.8)

    assert view.value == 1.8
    assert applied == {}
    assert SettingRepository(db_manager).get_optional("FILE_SEND_INTERVAL") is None
    assert SettingHistoryRepository(db_manager).list() == []
    assert AuditEventRepository(db_manager).list() == []


def test_load_persisted_applies_overrides(db_manager) -> None:
    """启动时应把数据库动态覆盖值应用到运行配置。"""
    service, _applied = _build_service(db_manager, {"FILE_SEND_INTERVAL": 1.8})
    SettingRepository(db_manager).set("FILE_SEND_INTERVAL", "3.5")

    applied_count = service.load_persisted()

    assert applied_count == 1
    assert service.config_manager.config_dict["FILE_SEND_INTERVAL"] == 3.5
    assert _find_view(service, "FILE_SEND_INTERVAL").value == 3.5


def test_load_persisted_rejects_readonly_and_unknown_keys(db_manager) -> None:
    """数据库出现只读键或未注册键时启动必须明确失败。"""
    service, _applied = _build_service(db_manager)
    setting_repo = SettingRepository(db_manager)

    setting_repo.set("LOW_MEMORY_MODE", "true")
    with pytest.raises(ValueError, match="不允许通过数据库覆盖"):
        service.load_persisted()

    setting_repo.delete("LOW_MEMORY_MODE")
    setting_repo.set("UNKNOWN_KEY", "1")
    with pytest.raises(ValueError, match="未注册的配置项"):
        service.load_persisted()


def test_register_appliers_requires_complete_set(db_manager) -> None:
    """应用接口必须完整覆盖可编辑配置，多余或缺失都明确报错。"""
    service = SettingsService(
        SettingRepository(db_manager),
        SettingHistoryRepository(db_manager),
        AuditEventRepository(db_manager),
        _ConfigManager(),  # type: ignore[arg-type]
    )

    with pytest.raises(ValueError, match="缺少立即生效配置的应用接口"):
        service.register_appliers({})

    appliers = {key: (lambda _value: None) for key in _editable_keys()}
    appliers["NOT_EDITABLE"] = lambda _value: None
    with pytest.raises(ValueError, match="无对应可编辑配置"):
        service.register_appliers(appliers)
