"""运行时配置应用服务测试。"""

from pathlib import Path
from typing import Any, Callable, Dict

from dotenv import dotenv_values

import pytest

from src.config.manager import ConfigManager
from src.database.repositories import (
    AuditEventRepository,
    SettingHistoryRepository,
    SettingRepository,
)
from src.service import OperationContext, SettingsService
from src.service.settings_service import EFFECT_IMMEDIATE, SETTING_DEFINITIONS


class _ConfigManager(ConfigManager):
    """仅保存配置字典的测试替身，行为与 ConfigManager.config_dict 一致。"""

    def __init__(
        self, config_dict: Dict[str, Any] | None = None, env_file=None
    ) -> None:
        super().__init__(env_file=env_file)
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
        _ConfigManager(config_dict, str(Path(db_manager.db_dir) / ".env")),  # type: ignore[arg-type]
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
    with pytest.raises(ValueError, match="不能为空"):
        service.update("WEBUI_HOST", "")

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


@pytest.mark.parametrize(
    "key,value",
    [
        ("LOW_MEMORY_MODE", True),
        ("MANGA_DOWNLOAD_PATH", "./new-downloads"),
        ("DB_PATH", "./new-data"),
        ("BACKUP_PATH", "./new-backups"),
        ("WEBUI_ENABLED", False),
        ("WEBUI_HOST", "0.0.0.0"),
        ("WEBUI_PORT", 8001),
        ("WEBUI_SESSION_HOURS", 48),
        ("NAPCAT_WS_URL", "ws://localhost:9000/qq"),
        ("NAPCAT_TOKEN", "secret-new"),
    ],
)
def test_restart_settings_save_env_without_applying(db_manager, key, value):
    """启动项写入隔离环境文件，不修改运行配置或动态配置表。"""
    service, applied = _build_service(db_manager)
    view = service.update(key, value)
    assert view.editable and view.restart_required
    assert applied == {}
    assert key not in service.config_manager.config_dict
    assert SettingRepository(db_manager).get_optional(key) is None
    assert dotenv_values(service.config_manager.env_file)[key] == service._serialize(
        value
    )
    if view.sensitive:
        assert view.value is None
        assert value not in repr(service.list())
        assert (
            SettingHistoryRepository(db_manager).list()[0].new_value_masked == "******"
        )
    else:
        assert view.value == value


def test_restart_save_failure_has_no_pending_or_audit(db_manager, monkeypatch):
    """写文件失败时不能报告已保存或留下成功审计。"""
    service, _ = _build_service(db_manager)

    def fail(_key, _value):
        raise OSError("写入失败")

    monkeypatch.setattr(service.config_manager, "save_restart_setting", fail)
    with pytest.raises(OSError):
        service.update("WEBUI_PORT", 8001)
    assert not _find_view(service, "WEBUI_PORT").restart_required
    assert SettingHistoryRepository(db_manager).list() == []
    assert AuditEventRepository(db_manager).list() == []


def test_restart_saved_values_loaded_at_startup(db_manager, monkeypatch):
    """新进程加载已保存启动项，同时保留环境文件中的其他内容。"""
    service, _ = _build_service(db_manager)
    path = Path(service.config_manager.env_file)
    path.write_text("# 保留注释\nOTHER_SETTING=preserved\n", encoding="utf-8")
    service.update("WEBUI_PORT", 8001)
    service.update("DB_PATH", "./new-data")
    service.update("NAPCAT_TOKEN", "secret-new")
    for key in ("WEBUI_PORT", "DB_PATH", "NAPCAT_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    manager = ConfigManager(env_file=str(path))
    manager.load_config()
    assert manager.config_dict["WEBUI_PORT"] == 8001
    assert manager.config_dict["DB_PATH"] == str(Path("./new-data").resolve())
    assert manager.config_dict["NAPCAT_TOKEN"] == "secret-new"
    assert "# 保留注释" in path.read_text(encoding="utf-8")
    assert dotenv_values(path)["OTHER_SETTING"] == "preserved"
