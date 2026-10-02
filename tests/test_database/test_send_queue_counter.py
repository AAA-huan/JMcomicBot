"""文件发送队列计数与批量进度回归测试"""

from threading import Lock
from types import SimpleNamespace
from typing import Any, Dict, List

import queue

from src.command.executor import CommandExecutor
from src.message.manager import MessageManager, SendTask
from src.service import DownloadQueueService


class _PermissionManager:
    """测试用权限管理器"""

    @staticmethod
    def check_user_permission(*_args: Any) -> None:
        return None


class _DownloadManager:
    """仅提供发送流程所需状态的下载管理器替身"""

    def __init__(self) -> None:
        self.downloading_mangas: Dict[str, bool] = {}

    @staticmethod
    def cancel_download(_manga_id: str) -> bool:
        return False

    @staticmethod
    def cancel_all_downloads() -> int:
        return 0


def _build_executor(download_path: str, messages: List[str]) -> CommandExecutor:
    """构造使用即时成功文件发送器的命令执行器"""

    def message_sender(*args: Any) -> None:
        messages.append(str(args[1]))

    download_manager = _DownloadManager()
    return CommandExecutor(
        message_sender=message_sender,
        file_sender=lambda *_args: None,
        download_manager=download_manager,
        config={
            "MANGA_DOWNLOAD_PATH": download_path,
            "FILE_SEND_BATCH_SIZE": 2,
            "FILE_SEND_BATCH_INTERVAL": 1,
        },
        self_id_getter=lambda: "bot",
        permission_manager=_PermissionManager(),
        download_service=DownloadQueueService(
            download_manager,
            task_service=SimpleNamespace(  # type: ignore[arg-type]
                find_active_download=lambda _manga_id: None
            ),
        ),
        manga_service=SimpleNamespace(delete=lambda *_args, **_kwargs: None),
    )


def test_resend_queue_count_returns_to_zero(tmp_path, monkeypatch) -> None:
    """重发任务入队时登记计数，处理完成后应回到零而非负数"""
    monkeypatch.setattr(MessageManager, "_start_file_queue_worker", lambda self: None)
    manager = MessageManager(config={})
    pdf_path = tmp_path / "350234-漫画(1章).pdf"
    pdf_path.write_bytes(b"%PDF")
    manager._pending_errors = [
        {
            "user_id": "10001",
            "group_id": None,
            "private": True,
            "content_type": "file",
            "content": str(pdf_path),
            "awaiting_resend": True,
        }
    ]

    assert manager.resend_pending_files("10001") == 1
    assert manager.get_send_queue_status()["queue_size"] == 1

    task = manager._file_queue.get_nowait()
    monkeypatch.setattr(manager, "_send_file_with_retry", lambda _task: None)
    manager._process_send_task(task)

    assert manager.get_send_queue_status()["queue_size"] == 0


def test_batch_progress_uses_file_total(tmp_path, monkeypatch) -> None:
    """多本单文件漫画应按文件总数在第2、4个文件后报告进度"""
    manga_ids = [str(350230 + index) for index in range(5)]
    for manga_id in manga_ids:
        (tmp_path / f"{manga_id}-漫画(1章).pdf").write_bytes(b"%PDF")

    messages: List[str] = []
    sleep_calls: List[float] = []
    executor = _build_executor(str(tmp_path), messages)
    monkeypatch.setattr(
        "src.command.executor.time.sleep", lambda seconds: sleep_calls.append(seconds)
    )

    executor._send_manga_files("10001", manga_ids, None, True)

    progress_messages = [message for message in messages if "发送进度" in message]
    assert len(progress_messages) == 2
    assert "已发送 2 个文件" in progress_messages[0]
    assert "已发送 4 个文件" in progress_messages[1]
    assert sleep_calls == [1.0, 1.0]


def test_no_progress_pause_after_final_file(tmp_path, monkeypatch) -> None:
    """最后一个文件恰好达到批次大小时不应再报告进度或休眠"""
    manga_id = "350240"
    for index in range(10):
        filename = f"{manga_id}-第{index + 1}章.pdf"
        (tmp_path / filename).write_bytes(b"%PDF")

    messages: List[str] = []
    sleep_calls: List[float] = []
    executor = _build_executor(str(tmp_path), messages)
    executor.update_batch_settings(batch_size=10)
    monkeypatch.setattr(
        "src.command.executor.time.sleep", lambda seconds: sleep_calls.append(seconds)
    )

    executor._send_manga_files("10001", [manga_id], None, True)

    assert not any("发送进度" in message for message in messages)
    assert sleep_calls == []


def test_is_manga_sending_detects_current_and_queued() -> None:
    """is_manga_sending 应识别正在发送与排队中的漫画文件。"""
    manager = object.__new__(MessageManager)
    manager._current_sending_file = "350236-标题(2章).pdf"
    manager._file_queue = queue.Queue()
    manager._file_queue.put(
        SendTask(
            user_id="10001",
            file_path="/tmp/350234-标题(1章).pdf",
            group_id=None,
            private=True,
        )
    )

    assert manager.is_manga_sending("350236") is True
    assert manager.is_manga_sending("350234") is True
    assert manager.is_manga_sending("350999") is False


def test_send_queue_status_reports_pending_and_active() -> None:
    """发送队列任务总数含正在发送的文件，pending_count 只算排队。"""
    manager = object.__new__(MessageManager)
    manager._queue_count_lock = Lock()
    manager._queue_running = True
    manager._queue_count = 2
    manager._current_sending_file = "350236-标题(2章).pdf"

    status = manager.get_send_queue_status()

    assert status["running"] is True
    assert status["queue_size"] == 2
    assert status["pending_count"] == 1
    assert status["current_file"] == "350236-标题(2章).pdf"


def test_send_queue_status_without_active_file() -> None:
    """没有正在发送的文件时待处理数等于任务总数。"""
    manager = object.__new__(MessageManager)
    manager._queue_count_lock = Lock()
    manager._queue_running = True
    manager._queue_count = 3
    manager._current_sending_file = None

    status = manager.get_send_queue_status()

    assert status["queue_size"] == 3
    assert status["pending_count"] == 3
    assert status["current_file"] is None
