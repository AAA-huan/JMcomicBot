"""配置管理器的 .env 读取与自重启持久化测试。"""

from os import environ
from pathlib import Path

import pytest

from src.config.manager import ConfigManager


def test_dotenv_values_do_not_leak_into_process_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """.env 中的值不写入 os.environ，避免自重启继承旧配置。"""
    env_file = tmp_path / ".env"
    env_file.write_text("DB_ECHO=false\n", encoding="utf-8")
    monkeypatch.delenv("DB_ECHO", raising=False)

    manager = ConfigManager(env_file=str(env_file))
    manager.load_config()

    assert manager.get("DB_ECHO") is False
    assert "DB_ECHO" not in environ

    # 模拟设置页修改启动项后自重启：新进程只应读取新的 .env
    manager.save_restart_setting("DB_ECHO", "true")
    restarted = ConfigManager(env_file=str(env_file))
    restarted.load_config()

    assert restarted.get("DB_ECHO") is True


def test_explicit_environment_still_overrides_dotenv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """显式导出的环境变量仍优先于 .env，保持部署语义不变。"""
    env_file = tmp_path / ".env"
    env_file.write_text("DB_ECHO=false\n", encoding="utf-8")
    monkeypatch.setenv("DB_ECHO", "true")

    manager = ConfigManager(env_file=str(env_file))
    manager.load_config()

    assert manager.get("DB_ECHO") is True


def test_build_restart_environment_drops_managed_dotenv_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """网页重启只移除 .env 中由本程序管理的同名环境变量。"""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "DB_ECHO=false\n"
        "WEBUI_PORT=7999\n"
        "GROUP_WHITELIST=10001\n"
        "OTHER_SETTING=from-dotenv\n",
        encoding="utf-8",
    )
    for key, value in (
        ("DB_ECHO", "true"),
        ("WEBUI_PORT", "9000"),
        ("GROUP_WHITELIST", "20002"),
        ("OTHER_SETTING", "from-environment"),
        ("JMBOT_RESTART_TEST", "keep"),
    ):
        monkeypatch.setenv(key, value)

    manager = ConfigManager(env_file=str(env_file))
    manager.load_config()
    environment = manager.build_restart_environment()

    assert "DB_ECHO" not in environment
    assert "WEBUI_PORT" not in environment
    assert "GROUP_WHITELIST" not in environment
    assert environment["OTHER_SETTING"] == "from-environment"
    assert environment["JMBOT_RESTART_TEST"] == "keep"
    assert "PATH" in environment


def test_build_restart_environment_reads_latest_dotenv_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """设置页刚写入的启动项也要参与重启清理，不能使用启动时的旧快照。"""
    env_file = tmp_path / ".env"
    env_file.write_text("DB_ECHO=false\n", encoding="utf-8")
    manager = ConfigManager(env_file=str(env_file))
    manager.load_config()

    manager.save_restart_setting("DB_ECHO", "true")
    monkeypatch.setenv("DB_ECHO", "false")

    environment = manager.build_restart_environment()

    assert "DB_ECHO" not in environment
