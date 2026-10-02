"""备份目录配置测试。"""

import os

from src.config.manager import ConfigManager


def test_backup_path_default_and_absolute(monkeypatch) -> None:
    """未配置 BACKUP_PATH 时应使用默认目录并转为绝对路径。"""
    monkeypatch.delenv("BACKUP_PATH", raising=False)
    manager = ConfigManager()

    manager.load_config()

    assert manager.get("BACKUP_PATH") == os.path.abspath("./data/backups")


def test_backup_path_accepts_relative_and_tilde(monkeypatch) -> None:
    """BACKUP_PATH 应支持相对路径与波浪号，并统一转为绝对路径。"""
    monkeypatch.setenv("BACKUP_PATH", "custom_backups")
    manager = ConfigManager()
    manager.load_config()
    assert manager.get("BACKUP_PATH") == os.path.abspath("custom_backups")

    monkeypatch.setenv("BACKUP_PATH", "~/jmbot-backups")
    manager = ConfigManager()
    manager.load_config()
    assert manager.get("BACKUP_PATH") == os.path.abspath(
        os.path.expanduser("~/jmbot-backups")
    )
