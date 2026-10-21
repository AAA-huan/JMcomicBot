"""下载进度采集、事件节流与 jmcomic 下载器钩子测试。"""

from threading import Thread
from typing import Any, Dict, List
from unittest.mock import Mock, patch

from jmcomic import ProgressDownloader

from src.download.progress import (
    DownloadProgressTracker,
    WebProgressDownloader,
)


class _PhotoEntity:
    """带 ID 与图片数量的章节替身，满足 len() 调用。"""

    id = "p1"

    def __init__(self, total: int = 2) -> None:
        self.total = total

    def __len__(self) -> int:
        return self.total


class _AlbumEntity:
    """带 ID 与章节数量的本子替身。"""

    id = "a1"

    def __len__(self) -> int:
        return 2


def test_tracker_publishes_phases_and_completion() -> None:
    """起止、章节与完成事件应携带完整快照，章节完成回调输出百分比。"""
    events: List[Dict[str, Any]] = []
    progress: List[int] = []
    tracker = DownloadProgressTracker(
        lambda event_type, data: events.append({"type": event_type, "data": data}),
        monotonic_clock=lambda: 1.0,
    )

    tracker.begin("900001", "task-1", progress.append)
    tracker.start("900001", 2)
    tracker.chapter_started("p1", 2)
    tracker.image_done("p1")
    tracker.image_done("p1")
    tracker.chapter_finished("p1")
    tracker.chapter_started("p2", 1)
    tracker.image_done("p2")
    tracker.chapter_finished("p2")
    tracker.finish()

    snapshot = tracker.snapshot()
    assert snapshot is not None
    assert snapshot.manga_id == "900001"
    assert snapshot.task_id == "task-1"
    assert snapshot.album_id == "900001"
    assert snapshot.album_total == 2
    assert snapshot.album_done == 2
    assert snapshot.finished is True
    assert snapshot.succeeded is True
    assert [(item.photo_id, item.done, item.total) for item in snapshot.chapters] == [
        ("p1", 2, 2),
        ("p2", 1, 1),
    ]
    assert progress == [50, 100]

    assert all(event["type"] == "download.progress" for event in events)
    assert [event["data"]["phase"] for event in events] == [
        "started",
        "progress",
        "progress",
        "progress",
        "progress",
        "finished",
    ]
    assert events[-1]["data"]["succeeded"] is True
    assert "T" in events[0]["data"]["started_at"]


def test_tracker_throttles_image_progress_events() -> None:
    """图片级高频事件按时间间隔合并，快照仍保留每次图片完成。"""
    clock = [0]
    events: List[Dict[str, Any]] = []
    tracker = DownloadProgressTracker(
        lambda _event_type, data: events.append(data),
        throttle_seconds=5.0,
        monotonic_clock=lambda: float(clock[0]),
    )

    tracker.begin("900001", "task-1")
    tracker.start("900001", 1)
    tracker.chapter_started("p1", 100)
    events.clear()

    for _ in range(100):
        clock[0] += 1
        tracker.image_done("p1")

    # 每 5 张图片才发布一次进度事件，而不是 100 次
    assert len(events) == 20
    snapshot = tracker.snapshot()
    assert snapshot is not None
    assert snapshot.chapters[0].done == 100
    assert snapshot.album_done == 0


def test_tracker_is_thread_safe_for_concurrent_images() -> None:
    """多线程累加图片时不能丢失计数，章节完成后快照应一致。"""
    events: List[Dict[str, Any]] = []
    tracker = DownloadProgressTracker(
        lambda _event_type, data: events.append(data),
        throttle_seconds=3600,
        monotonic_clock=lambda: 1.0,
    )
    tracker.begin("900001", "task-1")
    tracker.start("900001", 1)
    tracker.chapter_started("p1", 800)

    def download_images() -> None:
        for _ in range(100):
            tracker.image_done("p1")

    threads = [Thread(target=download_images) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    tracker.chapter_finished("p1")
    tracker.finish()

    snapshot = tracker.snapshot()
    assert snapshot is not None
    assert snapshot.chapters[0].done == 800
    assert snapshot.chapters[0].finished is True
    assert snapshot.album_done == 1
    assert snapshot.succeeded is True


def test_web_progress_downloader_forwards_hooks_after_super() -> None:
    """下载器覆写方法应先执行原生逻辑，再登记 WebUI 进度。"""
    tracker = Mock()
    downloader = WebProgressDownloader.__new__(WebProgressDownloader)
    WebProgressDownloader.configure(tracker)
    photo = _PhotoEntity(total=2)
    album = _AlbumEntity()
    image = type("Image", (), {"from_photo": photo})()
    calls: List[str] = []

    def record(name: str):
        return lambda *_args, **_kwargs: calls.append(name)

    try:
        with (
            patch.object(
                ProgressDownloader, "start_progress", side_effect=record("start")
            ),
            patch.object(
                ProgressDownloader, "before_photo", side_effect=record("photo")
            ),
            patch.object(
                ProgressDownloader, "after_image", side_effect=record("image")
            ),
            patch.object(
                ProgressDownloader, "after_photo", side_effect=record("photo_done")
            ),
            patch.object(
                ProgressDownloader, "after_album", side_effect=record("album")
            ),
            patch.object(
                ProgressDownloader, "stop_progress", side_effect=record("stop")
            ),
        ):
            downloader.start_progress(2, "a1")
            downloader.before_photo(photo)
            downloader.after_image(image, "/tmp/a.jpg")
            downloader.after_photo(photo)
            downloader.after_album(album)
            downloader.stop_progress()
    finally:
        WebProgressDownloader.configure(None)

    assert calls == ["start", "photo", "image", "photo_done", "album", "stop"]
    tracker.start.assert_called_once_with("a1", 2)
    tracker.chapter_started.assert_called_once_with("p1", 2)
    tracker.image_done.assert_called_once_with("p1")
    tracker.chapter_finished.assert_called_once_with("p1")
    tracker.finish.assert_called_once_with()
    tracker.flush.assert_called_once_with()
