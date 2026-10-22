"""漫画黑名单 QQ 命令与下载拦截测试。"""

from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from src.command.executor import CommandExecutor
from src.command.parser import CommandParser
from src.service.operation_context import OperationContext
from src.service.results import (
    BlacklistBatchResult,
    BlacklistOutcome,
    DownloadRequestItem,
)


class _PermissionManager:
    """记录黑名单权限检查的测试替身。"""

    def __init__(self, allowed: bool = True) -> None:
        self.allowed = allowed
        self.blacklist_checks: List[str] = []

    @staticmethod
    def check_user_permission(
        user_id: str, group_id: Optional[str], private: bool
    ) -> None:
        del user_id, group_id, private

    def check_blacklist_permission(self, user_id: str) -> bool:
        self.blacklist_checks.append(user_id)
        if not self.allowed:
            raise ValueError(f"用户 {user_id} 没有拉黑漫画的权限")
        return True


class _BlacklistService:
    """记录批量调用的黑名单服务替身。"""

    def __init__(
        self,
        blacklisted_ids: Optional[List[str]] = None,
        deleted_ids: Optional[List[str]] = None,
    ) -> None:
        self.blacklisted_ids = set(blacklisted_ids or [])
        self.deleted_ids = set(deleted_ids or [])
        self.add_calls: List[tuple[List[str], Optional[str], OperationContext]] = []
        self.remove_calls: List[tuple[List[str], OperationContext]] = []

    def add_batch(
        self,
        manga_ids: List[str],
        reason: Optional[str],
        context: OperationContext,
    ) -> BlacklistBatchResult:
        self.add_calls.append((manga_ids, reason, context))
        outcomes = []
        for manga_id in manga_ids:
            changed = manga_id not in self.blacklisted_ids
            self.blacklisted_ids.add(manga_id)
            outcomes.append(
                BlacklistOutcome(
                    manga_id=manga_id,
                    changed=changed,
                    status="blacklisted" if changed else "already_blacklisted",
                    task_id="task" if changed else None,
                    deleted=manga_id in self.deleted_ids,
                )
            )
        return BlacklistBatchResult(outcomes=tuple(outcomes))

    def remove_batch(
        self, manga_ids: List[str], context: OperationContext
    ) -> BlacklistBatchResult:
        self.remove_calls.append((manga_ids, context))
        outcomes = []
        for manga_id in manga_ids:
            changed = manga_id in self.blacklisted_ids
            self.blacklisted_ids.discard(manga_id)
            outcomes.append(
                BlacklistOutcome(
                    manga_id=manga_id,
                    changed=changed,
                    status="unblacklisted" if changed else "not_blacklisted",
                    task_id="task" if changed else None,
                )
            )
        return BlacklistBatchResult(outcomes=tuple(outcomes))

    def is_blacklisted(self, manga_id: str) -> bool:
        return manga_id in self.blacklisted_ids


class _DownloadManager:
    """仅提供下载拦截测试所需属性的下载管理器替身。"""

    def __init__(self) -> None:
        self.downloading_mangas: Dict[str, bool] = {}
        self.queued_tasks: Dict[str, Any] = {}
        self.requested: List[str] = []

    def request_download(
        self,
        manga_id: str,
        context: OperationContext,
        notifier: Optional[Any],
    ) -> DownloadRequestItem:
        del context, notifier
        self.requested.append(manga_id)
        return DownloadRequestItem(manga_id=manga_id, status="queued", task_id=None)

    @staticmethod
    def find_active_download(_manga_id: str) -> Optional[str]:
        return None


def _build_executor(
    messages: List[str],
    blacklist_service: Optional[_BlacklistService] = None,
    permission_manager: Optional[_PermissionManager] = None,
    download_manager: Optional[_DownloadManager] = None,
) -> CommandExecutor:
    """构造带消息捕获的 QQ 命令执行器。"""
    manager = download_manager or _DownloadManager()

    def message_sender(
        user_id: str, message: str, group_id: Optional[str], private: bool
    ) -> None:
        del user_id, group_id, private
        messages.append(message)

    return CommandExecutor(
        message_sender=message_sender,
        file_sender=lambda *_args: None,
        download_manager=manager,
        config={"MANGA_DOWNLOAD_PATH": "/tmp", "FILE_SEND_BATCH_SIZE": 10},
        self_id_getter=lambda: "bot",
        permission_manager=permission_manager or _PermissionManager(),
        download_service=SimpleNamespace(  # type: ignore[arg-type]
            request=lambda ids, context, notifier: SimpleNamespace(
                skipped_blacklisted=(), duplicate_count=0
            )
        ),
        manga_service=SimpleNamespace(delete=lambda *_args, **_kwargs: None),  # type: ignore[arg-type]
        blacklist_service=blacklist_service,  # type: ignore[arg-type]
    )


def test_parser_supports_chinese_and_english_aliases() -> None:
    """拉黑与解除拉黑的中英文别名应归一化到标准命令。"""
    parser = CommandParser()
    for alias in ("拉黑", "加入黑名单", "blacklist"):
        assert parser.parse(f"{alias} 100") == ("blacklist", "100")
    for alias in ("解除拉黑", "移出黑名单", "unblacklist"):
        assert parser.parse(f"{alias} 100") == ("unblacklist", "100")


def test_parser_validates_blacklist_ids() -> None:
    """黑名单命令接受单个数字与逗号句号分隔批量 ID。"""
    parser = CommandParser()
    assert parser.validate_params("blacklist", "100") is True
    assert parser.validate_params("blacklist", "100,101。102，103") is True
    assert parser.validate_params("unblacklist", "100") is True
    assert parser.validate_params("blacklist", "abc") is False
    assert parser.validate_params("blacklist", "") is False
    assert parser.validate_params("blacklist", "100 abc") is False
    assert "拉黑 350234" in parser.get_error_message("blacklist")


def test_execute_blacklist_command_reports_counts() -> None:
    """执行拉黑命令应检查权限、调用批量服务并返回中文汇总。"""
    messages: List[str] = []
    blacklist = _BlacklistService(blacklisted_ids=["101"], deleted_ids=["100"])
    permission = _PermissionManager()
    executor = _build_executor(messages, blacklist, permission)

    executor.execute_command("10001", "拉黑 100,101", private=True)

    assert permission.blacklist_checks == ["10001"]
    assert blacklist.add_calls[0][0] == ["100", "101"]
    assert blacklist.add_calls[0][1] is None
    assert blacklist.add_calls[0][2] == OperationContext.qq("10001")
    assert messages == [
        "✅ 已拉黑 1 条漫画，其中 1 条已在黑名单，并同步删除 1 条本地漫画"
    ]


def test_execute_unblacklist_command_reports_counts() -> None:
    """解除拉黑命令应调用解除批量服务并报告未命中数量。"""
    messages: List[str] = []
    blacklist = _BlacklistService(blacklisted_ids=["100"])
    executor = _build_executor(messages, blacklist)

    executor.execute_command("10001", "解除拉黑 100,101", private=True)

    assert blacklist.remove_calls[0][0] == ["100", "101"]
    assert blacklist.remove_calls[0][1] == OperationContext.qq("10001")
    assert messages == ["✅ 已解除 1 条漫画的黑名单，其中 1 条不在黑名单"]


def test_blacklist_permission_denied_does_not_call_service() -> None:
    """无删除权限的用户命令被拒，且不接触黑名单服务。"""
    messages: List[str] = []
    blacklist = _BlacklistService()
    executor = _build_executor(messages, blacklist, _PermissionManager(allowed=False))

    executor.execute_command("10001", "拉黑 100", private=True)

    assert blacklist.add_calls == []
    assert messages == ["❌ 权限检查失败：用户 10001 没有拉黑漫画的权限"]


def test_blacklist_all_parameter_is_rejected() -> None:
    """--all 在拉黑命令中不执行，明确提示提供具体 ID。"""
    messages: List[str] = []
    blacklist = _BlacklistService()
    executor = _build_executor(messages, blacklist)

    executor.execute_command("10001", "拉黑 --all", private=True)

    assert blacklist.add_calls == []
    assert messages == ["❌ 拉黑命令不支持 --all 参数\n请提供具体的漫画ID"]


def test_blacklisted_downloaded_manga_is_skipped_before_pdf_check(
    tmp_path, monkeypatch
) -> None:
    """已下载的拉黑漫画也应优先跳过，不再走 PDF 已存在分支。"""
    manga_id = "100"
    (tmp_path / f"{manga_id}-标题.pdf").write_bytes(b"%PDF")
    messages: List[str] = []
    download_manager = _DownloadManager()
    executor = _build_executor(
        messages,
        _BlacklistService(blacklisted_ids=[manga_id]),
        download_manager=download_manager,
    )
    monkeypatch.setattr(
        "src.command.executor.find_manga_pdf",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("拉黑漫画不应检查 PDF")
        ),
    )

    executor._download_manga_files("10001", [manga_id], None, True)

    assert download_manager.requested == []
    assert "🚫 已被拉黑，跳过下载" in "\n".join(messages)
    assert "已下载" not in "\n".join(messages)


def test_help_contains_blacklist_commands_once() -> None:
    """帮助文案应说明拉黑与解除拉黑，且不重复展示。"""
    messages: List[str] = []
    executor = _build_executor(messages)

    executor._send_help("10001", "", None, True)

    assert messages[0].count("- 拉黑 <漫画ID>") == 1
    assert messages[0].count("- 解除拉黑 <漫画ID>") == 1
