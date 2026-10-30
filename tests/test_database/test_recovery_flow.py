"""启动恢复询问与 bot 调度流程测试。"""

from types import SimpleNamespace
from typing import List

from src.bot import MangaBot
from src.database.repositories import AuditEventRepository


class _TaskService:
    """记录被取消恢复的任务 ID。"""

    def __init__(self) -> None:
        self.cancelled_ids: List[str] = []

    def cancel_recovery(self, task_id: str) -> None:
        self.cancelled_ids.append(task_id)


class _AuditRecorder:
    """记录审计事件参数，避免为每个分支创建数据库。"""

    def __init__(self) -> None:
        self.events: List[dict[str, object]] = []

    def record(self, **kwargs: object) -> None:
        self.events.append(dict(kwargs))


def _tasks() -> List[SimpleNamespace]:
    return [
        SimpleNamespace(id="task-100", manga_id="100"),
        SimpleNamespace(id="task-200", manga_id="200"),
    ]


def test_no_channel_defaults_to_continue(monkeypatch) -> None:
    """终端非交互且 WebUI 关闭时直接恢复，不进入等待。"""
    bot = object.__new__(MangaBot)
    bot._pending_recovery_tasks = _tasks()
    bot.web_server = None
    bot.config_manager = SimpleNamespace(
        config_dict={"RECOVERY_PROMPT_TIMEOUT_SECONDS": 180}
    )
    recovered: List[object] = []
    cancelled: List[object] = []
    bot._recover_download_tasks = recovered.append
    bot._cancel_recovery_tasks = cancelled.append
    monkeypatch.setattr("src.bot.sys.stdin", SimpleNamespace(isatty=lambda: False))

    bot._handle_recovery_prompt()

    assert [task.id for task in recovered[0]] == ["task-100", "task-200"]
    assert cancelled == []
    assert bot._pending_recovery_tasks == []
    assert bot.recovery_prompt is None


def test_terminal_cancel_skips_recovery(monkeypatch) -> None:
    """终端选择取消后不再调用恢复入队。"""
    bot = object.__new__(MangaBot)
    bot._pending_recovery_tasks = _tasks()
    bot.web_server = None
    bot.config_manager = SimpleNamespace(
        config_dict={"RECOVERY_PROMPT_TIMEOUT_SECONDS": 180}
    )
    recovered: List[object] = []
    cancelled: List[object] = []
    bot._recover_download_tasks = recovered.append
    bot._cancel_recovery_tasks = cancelled.append
    monkeypatch.setattr("src.bot.sys.stdin", SimpleNamespace(isatty=lambda: True))
    bot._start_terminal_recovery_prompt = lambda prompt: prompt.resolve("cancel")

    bot._handle_recovery_prompt()

    assert recovered == []
    assert [task.id for task in cancelled[0]] == ["task-100", "task-200"]


def test_cancel_recovery_tasks_updates_tasks_audit_and_temp(db_manager) -> None:
    """取消遗留任务时写任务状态、审计并清理下载临时目录。"""
    bot = object.__new__(MangaBot)
    task_service = _TaskService()
    audit_repo = AuditEventRepository(db_manager)
    bot.operation_task_service = task_service
    bot.audit_event_repo = audit_repo
    cleanup_calls: List[bool] = []
    bot._cleanup_download_directory = lambda: cleanup_calls.append(True)

    bot._cancel_recovery_tasks(_tasks())

    assert task_service.cancelled_ids == ["task-100", "task-200"]
    events = audit_repo.list()
    cancel_events = [
        event for event in events if event.event_type == "bot.recovery_cancelled"
    ]
    assert len(cancel_events) == 2
    assert {event.target_id for event in cancel_events} == {"100", "200"}
    assert all(
        event.metadata_json is not None and "user_cancelled" in event.metadata_json
        for event in cancel_events
    )
    assert cleanup_calls == [True]


def test_continue_records_recovery_audit() -> None:
    """继续恢复时复用下载管理器并记录汇总审计。"""
    bot = object.__new__(MangaBot)
    calls: List[object] = []
    bot.download_manager = SimpleNamespace(
        recover_tasks=lambda tasks: (
            calls.append(tasks)
            or SimpleNamespace(
                recovered_count=2,
                resumed_count=1,
                skipped_count=0,
                aborted=False,
            )
        )
    )
    audit = _AuditRecorder()
    bot.audit_event_repo = audit

    bot._recover_download_tasks(_tasks())

    assert len(calls) == 1
    assert audit.events[0]["event_type"] == "bot.tasks_recovered"
    assert audit.events[0]["result"] == "succeeded"
    assert audit.events[0]["metadata"] == {
        "recovered_count": 2,
        "resumed_count": 1,
    }


def test_run_starts_recovery_after_web_without_blocking() -> None:
    """Web 启动后才发起恢复询问，且询问不阻塞 WebSocket 连接。"""
    bot = object.__new__(MangaBot)
    order: List[str] = []
    bot._pending_recovery_tasks = _tasks()
    bot._recovery_thread = None
    bot._shutdown_event = SimpleNamespace(
        wait=lambda: order.append("wait"),
        set=lambda: None,
    )
    bot.web_server = SimpleNamespace(start=lambda: order.append("web"))
    bot.connect_websocket = lambda: order.append("websocket")
    bot.start_reconnect_manager = lambda: order.append("reconnect")
    bot.start_cleanup_scheduler = lambda: order.append("cleanup")
    bot._start_recovery_prompt = lambda: order.append("recovery")

    bot.run()

    assert order == ["web", "recovery", "websocket", "reconnect", "cleanup", "wait"]
