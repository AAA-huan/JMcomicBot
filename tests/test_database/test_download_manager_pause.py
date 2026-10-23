"""下载队列暂停与持久化测试。"""

from pathlib import Path
from threading import Event
from typing import Any, Dict, List
from unittest.mock import Mock

import time

from src.config.manager import ConfigManager
from src.database.repositories import (
    AuditEventRepository,
    SettingHistoryRepository,
    SettingRepository,
)
from src.download.manager import DownloadManager, DownloadQueueItem
from src.service import OperationContext, SettingsService


class _ConfigManager(ConfigManager):
    """仅提供 config_dict 的配置管理器替身。"""

    def __init__(self, config_dict: Dict[str, Any], env_file: str) -> None:
        super().__init__(env_file=env_file)
        self.config_dict = dict(config_dict)


def _build_settings(db_manager) -> SettingsService:
    """基于临时数据库构造配置服务。"""
    return SettingsService(
        SettingRepository(db_manager),
        SettingHistoryRepository(db_manager),
        AuditEventRepository(db_manager),
        _ConfigManager({}, str(Path(db_manager.db_dir) / ".env")),  # type: ignore[arg-type]
    )


def test_pause_state_persists_across_manager_restart(
    db_manager, monkeypatch, tmp_path
) -> None:
    """暂停后重建管理器仍为暂停，恢复后持久化为未暂停。"""
    monkeypatch.setattr(
        DownloadManager, "_start_download_queue_processor", lambda self: None
    )
    settings = _build_settings(db_manager)

    def build_manager() -> DownloadManager:
        return DownloadManager(
            logger_instance=Mock(),
            config={
                "MANGA_DOWNLOAD_PATH": str(tmp_path / "downloads"),
                "LOW_MEMORY_MODE": False,
            },
            message_sender=Mock(),
            settings_service=settings,
        )

    manager = build_manager()
    assert manager.is_paused() is False
    assert manager.pause() is True
    assert manager.pause() is False
    assert settings.is_download_queue_paused() is True
    assert manager.get_queue_status()["paused"] is True

    restarted = build_manager()
    assert restarted.is_paused() is True
    assert restarted.resume() is True
    assert restarted.resume() is False
    assert settings.is_download_queue_paused() is False
    assert build_manager().is_paused() is False


def test_pause_stops_worker_after_current_task_and_resume_continues(
    monkeypatch, tmp_path
) -> None:
    """暂停在当前任务完成后生效，恢复后继续处理排队任务。"""
    processed: List[str] = []
    first_started = Event()
    release_first = Event()

    def fake_process(_manager: DownloadManager, item: DownloadQueueItem) -> None:
        processed.append(item.manga_id)
        if item.manga_id == "100":
            first_started.set()
            assert release_first.wait(timeout=3)

    monkeypatch.setattr(DownloadManager, "_process_download_task", fake_process)
    manager = DownloadManager(
        logger_instance=Mock(),
        config={
            "MANGA_DOWNLOAD_PATH": str(tmp_path / "downloads"),
            "LOW_MEMORY_MODE": False,
        },
        message_sender=Mock(),
    )
    context = OperationContext.system()
    try:
        manager.request_download("100", context, None)
        manager.request_download("101", context, None)
        assert first_started.wait(timeout=3)

        assert manager.pause() is True
        release_first.set()

        deadline = time.monotonic() + 1
        while processed != ["100"] and time.monotonic() < deadline:
            time.sleep(0.01)
        assert processed == ["100"]
        # 暂停期间不再取新任务
        time.sleep(0.3)
        assert processed == ["100"]
        assert manager.download_queue.qsize() == 1

        assert manager.resume() is True
        deadline = time.monotonic() + 3
        while processed != ["100", "101"] and time.monotonic() < deadline:
            time.sleep(0.01)
        assert processed == ["100", "101"]
    finally:
        release_first.set()
        manager.stop(timeout=2)
