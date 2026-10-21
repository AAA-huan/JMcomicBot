"""下载管理器接入实时进度采集的集成测试。"""

from unittest.mock import Mock

from jmcomic import JmModuleConfig

import jmcomic

from src.download.manager import DownloadManager, DownloadQueueItem
from src.download.progress import (
    DownloadProgressTracker,
    WebProgressDownloader,
)
from src.service import OperationContext


class _FakeAlbum:
    """供元数据读取的本子替身。"""

    id = "900001"
    name = "进度测试漫画"
    authors = ["测试作者"]
    tags = ["测试"]
    episode_list = ["p1", "p2"]


class _FakeClient:
    """只返回固定本子元数据的客户端替身。"""

    def get_album_detail(self, manga_id: str) -> _FakeAlbum:
        assert manga_id == "900001"
        return _FakeAlbum()


class _FakeOption:
    """满足下载管理器 option 操作的最小替身。"""

    def __init__(self) -> None:
        self.plugins: dict = {}

    def new_jm_client(self) -> _FakeClient:
        return _FakeClient()

    def call_all_plugin(self, _name: str, safe: bool = False) -> None:
        del safe


class _FakeManifest:
    """固定生成 PDF 与图片清单。"""

    image_filepath_list = ["a.jpg", "b.jpg"]

    def __init__(self, pdf_path: str) -> None:
        self.pdf_path = pdf_path

    def get_export_filepath_list(self, suffix: str) -> list[str]:
        return [self.pdf_path] if suffix == "pdf" else []


class _FakeResult:
    """下载结果替身。"""

    def __init__(self, pdf_path: str) -> None:
        self.manifest = _FakeManifest(pdf_path)


def test_download_manager_reports_progress_to_task_and_tracker(
    monkeypatch, tmp_path
) -> None:
    """下载钩子进度应同步任务百分比、发布事件并在完成后收尾。"""
    events: list[dict] = []
    tracker = DownloadProgressTracker(lambda _event_type, data: events.append(data))
    task_service = Mock()
    option = _FakeOption()
    pdf_path = str(tmp_path / "900001-进度测试漫画(2章).pdf")

    monkeypatch.setattr(
        DownloadManager, "_start_download_queue_processor", lambda self: None
    )
    monkeypatch.setattr(jmcomic, "create_option_by_file", lambda _path: option)

    def fake_download_album(manga_id: str, option) -> _FakeResult:
        del option
        assert manga_id == "900001"
        tracker.start("900001", 2)
        tracker.chapter_started("p1", 1)
        tracker.image_done("p1")
        tracker.chapter_finished("p1")
        tracker.chapter_started("p2", 1)
        tracker.image_done("p2")
        tracker.chapter_finished("p2")
        return _FakeResult(pdf_path)

    monkeypatch.setattr(jmcomic, "download_album", fake_download_album)
    manager = DownloadManager(
        logger_instance=Mock(),
        config={
            "MANGA_DOWNLOAD_PATH": str(tmp_path / "downloads"),
            "LOW_MEMORY_MODE": False,
            "LOW_MEMORY_DELETE_DELAY": 3,
        },
        message_sender=Mock(),
        operation_task_service=task_service,
        progress_tracker=tracker,
    )
    item = DownloadQueueItem(
        manga_id="900001",
        context=OperationContext.web("admin", "127.0.0.1"),
        operation_task_id="task-1",
        notifier=None,
    )
    previous_downloader = JmModuleConfig.CLASS_DOWNLOADER

    try:
        manager._process_download_task(item)  # pylint: disable=protected-access

        assert JmModuleConfig.downloader_class() is WebProgressDownloader
        task_service.start.assert_called_once_with("task-1", "downloading")
        assert task_service.progress.call_args_list == [
            (("task-1", "downloading", 50), {}),
            (("task-1", "downloading", 100), {}),
        ]
        task_service.succeed.assert_called_once()
        task_service.fail.assert_not_called()

        snapshot = tracker.snapshot()
        assert snapshot is not None
        assert snapshot.finished is True
        assert snapshot.succeeded is True
        assert snapshot.album_done == 2
        assert [event["phase"] for event in events][-1] == "finished"
    finally:
        JmModuleConfig.CLASS_DOWNLOADER = previous_downloader
        WebProgressDownloader.configure(None)
