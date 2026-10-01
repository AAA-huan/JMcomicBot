"""WebUI 启动配置测试。"""

import pytest

from src.config.manager import ConfigManager


@pytest.fixture(autouse=True)
def _isolate_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    """配置测试只读取显式设置的环境变量，不读取开发者本地的 .env。"""
    monkeypatch.setattr("src.config.manager.load_dotenv", lambda *args, **kwargs: None)


def test_webui_config_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "WEBUI_ENABLED",
        "WEBUI_HOST",
        "WEBUI_PORT",
        "WEBUI_SESSION_HOURS",
    ):
        monkeypatch.delenv(name, raising=False)
    manager = ConfigManager()

    manager.load_config()

    assert manager.get("WEBUI_ENABLED") is True
    assert manager.get("WEBUI_HOST") == "127.0.0.1"
    assert manager.get("WEBUI_PORT") == 8000
    assert manager.get("WEBUI_SESSION_HOURS") == 24


def test_webui_config_accepts_explicit_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WEBUI_ENABLED", "false")
    monkeypatch.setenv("WEBUI_HOST", "0.0.0.0")
    monkeypatch.setenv("WEBUI_PORT", "8088")
    monkeypatch.setenv("WEBUI_SESSION_HOURS", "48")
    manager = ConfigManager()

    manager.load_config()

    assert manager.get("WEBUI_ENABLED") is False
    assert manager.get("WEBUI_HOST") == "0.0.0.0"
    assert manager.get("WEBUI_PORT") == 8088
    assert manager.get("WEBUI_SESSION_HOURS") == 48


def test_webui_dev_origins_are_optional_and_validated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """开发来源默认留空；配置时必须是完整的来源地址。"""
    monkeypatch.delenv("WEBUI_DEV_ORIGINS", raising=False)
    manager = ConfigManager()
    manager.load_config()
    assert manager.webui_dev_origins == []

    monkeypatch.setenv(
        "WEBUI_DEV_ORIGINS", "http://127.0.0.1:5173, http://localhost:5173"
    )
    manager = ConfigManager()
    manager.load_config()
    assert manager.webui_dev_origins == [
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ]

    monkeypatch.setenv("WEBUI_DEV_ORIGINS", "127.0.0.1:5173")
    with pytest.raises(ValueError, match="完整的来源地址"):
        ConfigManager().load_config()


@pytest.mark.parametrize(
    ("name", "value", "message"),
    (
        ("WEBUI_ENABLED", "maybe", "必须是布尔值"),
        ("WEBUI_PORT", "0", "必须位于 1 到 65535 之间"),
        ("WEBUI_PORT", "abc", "必须是整数"),
        ("WEBUI_SESSION_HOURS", "721", "必须位于 1 到 720 之间"),
    ),
)
def test_webui_config_rejects_invalid_values(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
    message: str,
) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match=message):
        ConfigManager().load_config()
