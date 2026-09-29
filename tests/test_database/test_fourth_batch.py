"""第四批文案、扫描与启动清理回归测试"""

from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from src.bot import MangaBot
from src.command.executor import CommandExecutor
from src.command.parser import CommandParser
from src.service import DownloadQueueService
from src.utils.helpers import cleanup_failed_downloads
from src.utils.manga_scanner import MangaScanEntry


class _PermissionManager:
    """测试用权限管理器"""

    @staticmethod
    def check_user_permission(*_args: Any) -> None:
        return None


class _DownloadManager:
    """测试帮助文案所需的最小下载管理器"""

    downloading_mangas: Dict[str, bool] = {}

    @staticmethod
    def cancel_download(_manga_id: str) -> bool:
        return False

    @staticmethod
    def cancel_all_downloads() -> int:
        return 0


def test_list_help_uses_real_page_example(tmp_path) -> None:
    """帮助与错误提示应使用可执行的 -2 示例，并准确描述 -a"""
    messages: List[str] = []
    download_manager = _DownloadManager()
    executor = CommandExecutor(
        message_sender=lambda _user, message, _group, _private: messages.append(
            message
        ),
        file_sender=lambda *_args: None,
        download_manager=download_manager,
        config={"MANGA_DOWNLOAD_PATH": str(tmp_path)},
        self_id_getter=lambda: "bot",
        permission_manager=_PermissionManager(),
        download_service=DownloadQueueService(download_manager),
    )

    executor._send_help("10001", "", None, True)
    list_error = CommandParser().get_error_message("list")

    assert "-2 查看第2页" in messages[-1]
    assert "-a 列出全部" in messages[-1]
    assert "漫画列表 -2" in list_error
    assert "查看详情" not in list_error
    assert "漫画列表 -n" not in list_error


def test_scanner_dead_max_chapter_property_removed() -> None:
    """无调用且语义错误的 max_chapter_count 属性应被移除"""
    entry = MangaScanEntry(manga_id="350234", title="漫画", chapter_count=3)
    assert not hasattr(entry, "max_chapter_count")


def test_cleanup_missing_directory_raises_precisely(tmp_path) -> None:
    """工具函数遇到缺失目录时应明确抛错，不再声称已跳过"""
    missing_path = tmp_path / "missing"
    with pytest.raises(FileNotFoundError, match="下载目录不存在"):
        cleanup_failed_downloads(str(missing_path))


def test_bot_startup_handles_missing_cleanup_directory(tmp_path, monkeypatch) -> None:
    """启动清理遇到目录意外缺失时应记录并继续，而不是中断初始化"""
    bot = object.__new__(MangaBot)
    bot.config_manager = SimpleNamespace(
        config_dict={"MANGA_DOWNLOAD_PATH": str(tmp_path / "missing")}
    )
    monkeypatch.setattr(
        "src.bot.cleanup_failed_downloads",
        lambda path: (_ for _ in ()).throw(FileNotFoundError(path)),
    )

    bot._cleanup_download_directory()
