"""下载管理器取消任务逻辑的测试"""

from unittest.mock import Mock

from src.download.manager import DownloadManager


class TestDownloadManagerCancel:
    """下载管理器取消任务测试类"""

    def _make_manager(self) -> DownloadManager:
        logger = Mock()
        config = {"MANGA_DOWNLOAD_PATH": "/tmp/dl"}
        sender = Mock()
        manager = DownloadManager(
            logger_instance=logger,
            config=config,
            message_sender=sender,
        )
        return manager

    def test_cancel_queued_task(self) -> None:
        manager = self._make_manager()
        # 模拟一个排队中的任务
        manager.queued_tasks["100"] = ("user", None, True)

        assert manager.cancel_download("100") is True
        assert "100" not in manager.queued_tasks
        assert manager.cancelled_downloads.get("100") is True

    def test_cancel_non_existent_task(self) -> None:
        manager = self._make_manager()
        assert manager.cancel_download("999") is False

    def test_cancel_downloading_task_rejected(self) -> None:
        manager = self._make_manager()
        manager.downloading_mangas["100"] = True

        # 正在下载的任务无法取消
        assert manager.cancel_download("100") is False

    def test_cancel_all_downloads(self) -> None:
        manager = self._make_manager()
        manager.queued_tasks["100"] = ("user", None, True)
        manager.queued_tasks["101"] = ("user", None, True)
        manager.downloading_mangas["200"] = True  # 正在下载的不计入

        count = manager.cancel_all_downloads()
        assert count == 2
        assert "100" not in manager.queued_tasks
        assert "101" not in manager.queued_tasks
        assert "200" in manager.queued_tasks or "200" in manager.downloading_mangas

    def test_process_download_task_skips_cancelled(self) -> None:
        manager = self._make_manager()
        manager.queued_tasks["100"] = ("user", None, True)
        manager.cancelled_downloads["100"] = True

        # 已取消的排队任务被取出执行时直接跳过
        manager._process_download_task(
            "user", "100", "", True
        )  # pylint: disable=protected-access

        assert "100" not in manager.downloading_mangas
        assert "100" not in manager.cancelled_downloads
