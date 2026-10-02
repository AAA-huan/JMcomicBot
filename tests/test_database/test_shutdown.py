"""机器人后台线程与资源关闭流程测试"""

from types import SimpleNamespace
from typing import List

import threading
import time

import pytest

from src.bot import MangaBot
from src.database.repositories.audit_event_repository import AuditEventRepository
from src.download.manager import DownloadManager
from src.logging.logger_config import logger
from src.message.manager import MessageManager
from src.websocket.client import WebSocketClient


def test_idle_message_queue_stops_immediately() -> None:
    """空闲文件队列应由哨兵立即唤醒，不等待 queue.get 超时"""
    manager = MessageManager(config={})

    started_at = time.perf_counter()
    stopped = manager.stop()
    elapsed = time.perf_counter() - started_at

    assert stopped is True
    assert elapsed < 0.5

    with pytest.raises(RuntimeError, match="文件发送队列已停止"):
        manager.send_file("10001", __file__)


def test_active_send_retry_is_interrupted_on_stop(tmp_path) -> None:
    """等待 WebSocket 重连的发送任务应被停止事件立即中断"""
    manager = MessageManager(config={"SEND_RETRY_TIMEOUT": 30})
    pdf_path = tmp_path / "350234-漫画(1章).pdf"
    pdf_path.write_bytes(b"%PDF")
    errors: List[Exception] = []

    def send_file() -> None:
        try:
            manager.send_file("10001", str(pdf_path))
        except Exception as e:  # pylint: disable=broad-exception-caught
            errors.append(e)

    sender = threading.Thread(target=send_file)
    sender.start()
    deadline = time.time() + 1
    while manager.get_send_queue_status()["queue_size"] == 0:
        assert time.time() < deadline
        time.sleep(0.01)

    started_at = time.perf_counter()
    stopped = manager.stop()
    sender.join(timeout=0.5)
    elapsed = time.perf_counter() - started_at

    assert stopped is True
    assert not sender.is_alive()
    assert errors
    assert elapsed < 0.5


def test_websocket_watchdog_stops_immediately() -> None:
    """看门狗应由 Event 立即唤醒，不等待十秒轮询周期"""
    client = WebSocketClient(
        {"NAPCAT_WS_URL": "ws://localhost:8080", "NAPCAT_TOKEN": ""}
    )
    client.start_reconnect_manager()

    started_at = time.perf_counter()
    stopped = client.close()
    elapsed = time.perf_counter() - started_at

    assert stopped is True
    assert elapsed < 0.5


def test_shutdown_request_unblocks_main_loop(db_manager) -> None:
    """关闭请求应立即唤醒主循环，不再依赖一秒轮询"""
    bot = object.__new__(MangaBot)
    bot._shutdown_event = threading.Event()
    bot.audit_event_repo = AuditEventRepository(db_manager)
    bot.web_server = None
    bot.connect_websocket = lambda: None
    bot.start_reconnect_manager = lambda: None
    bot.start_cleanup_scheduler = lambda: None
    run_errors: List[BaseException] = []

    def run_bot() -> None:
        try:
            bot.run()
        except BaseException as error:  # pylint: disable=broad-exception-caught
            run_errors.append(error)

    runner = threading.Thread(target=run_bot)
    runner.start()

    bot.request_shutdown("测试关闭")
    runner.join(timeout=0.5)

    assert not runner.is_alive()
    assert run_errors == []


def test_shutdown_request_records_audit(db_manager) -> None:
    """关闭请求应记录 bot.shutdown_requested 审计，且重复调用不重复记录。"""
    bot = object.__new__(MangaBot)
    bot._shutdown_event = threading.Event()
    bot.audit_event_repo = AuditEventRepository(db_manager)

    bot.request_shutdown("收到用户中断信号")
    bot.request_shutdown("重复调用不应再记录")

    events = AuditEventRepository(db_manager).list()
    shutdown_events = [
        event for event in events if event.event_type == "bot.shutdown_requested"
    ]
    assert len(shutdown_events) == 1
    assert shutdown_events[0].source == "system"
    assert shutdown_events[0].result == "accepted"


def test_idle_download_queue_stops_immediately(tmp_path) -> None:
    """空闲下载队列应由哨兵立即退出"""
    manager = DownloadManager(
        logger_instance=logger,
        config={"MANGA_DOWNLOAD_PATH": str(tmp_path), "LOW_MEMORY_MODE": False},
        message_sender=lambda *_args: None,
    )

    started_at = time.perf_counter()
    stopped = manager.stop()
    elapsed = time.perf_counter() - started_at

    assert stopped is True
    assert elapsed < 0.5

    with pytest.raises(RuntimeError, match="下载队列已停止"):
        manager.download_manga("10001", "350234", None, True)


def test_bot_close_is_idempotent_and_continues_after_error() -> None:
    """单个组件关闭失败不应阻断其他组件，重复关闭不应重复执行"""
    calls: List[str] = []

    def fail_websocket() -> None:
        calls.append("websocket")
        raise RuntimeError("关闭失败")

    bot = object.__new__(MangaBot)
    bot._shutdown_event = threading.Event()
    bot._close_lock = threading.Lock()
    bot._resources_closed = False
    bot._cleanup_thread = None
    bot._cleanup_stop_event = threading.Event()
    bot.web_server = SimpleNamespace(stop=lambda: calls.append("web") or True)
    bot.ws_client = SimpleNamespace(close=fail_websocket)
    bot.message_manager = SimpleNamespace(stop=lambda: calls.append("message") or True)
    bot.download_manager = SimpleNamespace(
        stop=lambda: calls.append("download") or True
    )
    bot.database_manager = SimpleNamespace(close=lambda: calls.append("database"))

    bot.close()
    bot.close()

    assert calls == ["web", "websocket", "message", "download", "database"]
    assert bot._shutdown_event.is_set()


def test_run_cleanup_once_cleans_sessions_and_swallows_errors() -> None:
    """单次清理应同时清理过期会话，且异常只记录不抛出"""
    calls: List[str] = []
    bot = object.__new__(MangaBot)
    bot.cleanup_service = SimpleNamespace(cleanup=lambda: calls.append("cleanup") or 3)
    bot.web_auth_service = SimpleNamespace(
        cleanup_expired_sessions=lambda: calls.append("sessions") or 2
    )

    bot._run_cleanup_once()
    assert calls == ["cleanup", "sessions"]

    def fail_cleanup() -> int:
        raise RuntimeError("清理失败")

    bot.cleanup_service = SimpleNamespace(cleanup=fail_cleanup)
    bot._run_cleanup_once()
