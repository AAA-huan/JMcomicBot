"""第二批用户交互 bug 的 executor 层回归测试"""

from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional

import pytest

from src.command.executor import CommandExecutor
from src.database.repositories import (
    AuditEventRepository,
    MangaRepository,
    MangaTagRepository,
    OperationTaskRepository,
    TaskEventRepository,
)
from src.download.manager import DownloadManager
from src.service import (
    DownloadQueueService,
    OperationContext,
    OperationTaskService,
)


class _PermissionManager:
    """测试用权限管理器，允许所有普通命令和删除命令"""

    @staticmethod
    def check_user_permission(
        user_id: str, group_id: Optional[str], private: bool
    ) -> None:
        del user_id, group_id, private

    @staticmethod
    def check_delete_permission(user_id: str) -> None:
        del user_id


class _DownloadManager:
    """仅提供 executor 测试所需属性的下载管理器替身"""

    def __init__(self) -> None:
        self.downloading_mangas: Dict[str, bool] = {}
        self.queued_tasks: Dict[str, Any] = {}

    def download_manga(
        self, user_id: str, manga_id: str, group_id: Optional[str], private: bool
    ) -> None:
        del user_id, manga_id, group_id, private

    def cancel_download(self, manga_id: str) -> bool:
        if manga_id not in self.queued_tasks:
            return False
        del self.queued_tasks[manga_id]
        return True

    def cancel_all_downloads(self) -> int:
        cancelled_count = len(self.queued_tasks)
        self.queued_tasks.clear()
        return cancelled_count


def _build_executor(
    download_path: str,
    messages: List[str],
    download_manager: Any,
    manga_repo: Optional[MangaRepository] = None,
    tag_repo: Optional[MangaTagRepository] = None,
    file_sender: Optional[Callable[[str, str, Optional[str], bool], None]] = None,
) -> CommandExecutor:
    """构造具备消息捕获能力的命令执行器"""

    def message_sender(
        user_id: str, message: str, group_id: Optional[str], private: bool
    ) -> None:
        del user_id, group_id, private
        messages.append(message)

    return CommandExecutor(
        message_sender=message_sender,
        file_sender=file_sender or (lambda *_args: None),
        download_manager=download_manager,
        config={"MANGA_DOWNLOAD_PATH": download_path, "FILE_SEND_BATCH_SIZE": 10},
        self_id_getter=lambda: "bot",
        permission_manager=_PermissionManager(),
        download_service=DownloadQueueService(download_manager),
        manga_repo=manga_repo,
        tag_repo=tag_repo,
    )


def _add_manga(manga_repo: MangaRepository, manga_id: str, chapter_count: int) -> None:
    """写入测试漫画元数据"""
    manga_repo.upsert(
        manga_id=manga_id,
        title=f"标题{manga_id}",
        author="作者",
        chapter_count=chapter_count,
        page_count=100,
    )


@pytest.fixture()
def operation_task_service(db_manager) -> OperationTaskService:
    """构造持久化操作任务服务。"""
    return OperationTaskService(
        OperationTaskRepository(db_manager),
        TaskEventRepository(db_manager),
        AuditEventRepository(db_manager),
    )


def test_unknown_command_replies(tmp_path) -> None:
    """未知命令应明确回复用户，而不是只写日志"""
    messages: List[str] = []
    executor = _build_executor(
        str(tmp_path), messages, download_manager=_DownloadManager()
    )

    executor.execute_command("10001", "哈哈哈")

    assert messages == ["❓ 未知命令，请输入'漫画帮助'查看所有可用命令"]


def test_cancel_downloads_uses_service_without_changing_qq_messages(tmp_path) -> None:
    """取消下载迁入应用服务后应保持既有 QQ 回复。"""
    messages: List[str] = []
    download_manager = _DownloadManager()
    download_manager.queued_tasks = {
        "100": ("user", None, True),
        "101": ("user", None, True),
    }
    executor = _build_executor(
        str(tmp_path), messages, download_manager=download_manager
    )

    executor._cancel_downloads("10001", "100,999", None, True)
    executor._cancel_downloads("10001", "", None, True)

    assert messages == [
        "🛑 已取消 1 个下载任务：100",
        "🛑 已取消全部下载任务（共 1 个）",
    ]


def test_tag_query_splits_spaces_like_parser(tmp_path) -> None:
    """executor 应与 parser 一致，将空格视为多标签分隔符"""
    messages: List[str] = []
    received_tags: List[List[str]] = []
    tag_repo = SimpleNamespace(
        get_manga_ids_by_tags=lambda tags: received_tags.append(tags) or set()
    )
    executor = _build_executor(
        str(tmp_path),
        messages,
        download_manager=_DownloadManager(),
        tag_repo=tag_repo,
    )

    executor._handle_manga_query("10001", "-t 纯爱 后宫", None, True)

    assert received_tags == [["纯爱", "后宫"]]
    assert "标签「纯爱、后宫」" in messages[-1]


def test_chapter_count_messages_prefer_database(
    tmp_path, manga_repo: MangaRepository, monkeypatch
) -> None:
    """下载、发送、查询文案应展示 DB 章节数，而不是 PDF 文件数"""
    manga_id = "350234"
    pdf_path = tmp_path / f"{manga_id}-标题(25章).pdf"
    pdf_path.write_bytes(b"%PDF")
    _add_manga(manga_repo, manga_id, chapter_count=25)

    messages: List[str] = []
    sent_files: List[str] = []

    def file_sender(
        user_id: str, file_path: str, group_id: Optional[str], private: bool
    ) -> None:
        del user_id, group_id, private
        sent_files.append(file_path)

    executor = _build_executor(
        str(tmp_path),
        messages,
        download_manager=_DownloadManager(),
        manga_repo=manga_repo,
        file_sender=file_sender,
    )

    # 批量响应默认只展示失败详情，此处直接展开结果明细以验证发送文案。
    monkeypatch.setattr(
        "src.command.executor.format_batch_response",
        lambda _command, results: "\n".join(message for _, _, message in results),
    )

    executor._download_manga_files("10001", [manga_id], None, True)
    executor._send_manga_files("10001", [manga_id], None, True)
    executor._query_manga_files("10001", [manga_id], None, True)

    combined_messages = "\n".join(messages)
    assert "共 25 个章节" in combined_messages
    assert "发送成功 1/1 个PDF文件（共 25 个章节）" in combined_messages
    assert "（25 个章节，共" in combined_messages
    assert sent_files == [str(pdf_path)]


def test_chapter_count_falls_back_to_pdf_count(tmp_path) -> None:
    """数据库没有漫画记录时，章节数回退为 PDF 文件数"""
    manga_id = "350235"
    (tmp_path / f"{manga_id}-第一章.pdf").write_bytes(b"%PDF")
    (tmp_path / f"{manga_id}-第二章.pdf").write_bytes(b"%PDF")
    messages: List[str] = []
    executor = _build_executor(
        str(tmp_path), messages, download_manager=_DownloadManager()
    )

    executor._query_manga_files("10001", [manga_id], None, True)

    assert "（2 个章节，共" in messages[-1]


def test_batch_delete_cleans_database(
    tmp_path, manga_repo: MangaRepository, tag_repo: MangaTagRepository
) -> None:
    """批量删除磁盘 PDF 后应同步清理漫画、文件和标签记录"""
    manga_ids = ["350236", "350237"]
    for manga_id in manga_ids:
        pdf_path = tmp_path / f"{manga_id}-标题(3章).pdf"
        pdf_path.write_bytes(b"%PDF")
        _add_manga(manga_repo, manga_id, chapter_count=3)
        manga_repo.add_file(manga_id, str(pdf_path))
        tag_repo.add("纯爱", manga_id)

    download_manager = object.__new__(DownloadManager)
    download_manager.manga_repo = manga_repo
    download_manager.tag_repo = tag_repo
    download_manager.queued_tasks = {}
    download_manager.downloading_mangas = {}

    messages: List[str] = []
    executor = _build_executor(
        str(tmp_path),
        messages,
        download_manager=download_manager,
        manga_repo=manga_repo,
        tag_repo=tag_repo,
    )

    executor._delete_batch_mangas("10001", manga_ids, None, True)

    for manga_id in manga_ids:
        assert manga_repo.get(manga_id) is None
    assert tag_repo.get_by_tag("纯爱") == []
    assert list(tmp_path.glob("*.pdf")) == []
    assert "成功：2" in messages[-1]


def test_is_download_active_reports_queued_and_downloading() -> None:
    """is_download_active 应识别排队中和下载中的漫画。"""
    manager = object.__new__(DownloadManager)
    manager.queued_tasks = {"111": ("10001", None, True)}
    manager.downloading_mangas = {"222": True}

    assert manager.is_download_active("111") is True
    assert manager.is_download_active("222") is True
    assert manager.is_download_active("333") is False


def test_delete_manga_skips_active_download(tmp_path, manga_repo) -> None:
    """正在下载中的漫画不应被删除，应返回冲突错误并保留文件。"""
    manga_id = "350238"
    pdf_path = tmp_path / f"{manga_id}-标题(1章).pdf"
    pdf_path.write_bytes(b"%PDF")
    _add_manga(manga_repo, manga_id, chapter_count=1)
    manga_repo.add_file(manga_id, str(pdf_path))

    download_manager = object.__new__(DownloadManager)
    download_manager.manga_repo = manga_repo
    download_manager.tag_repo = None
    download_manager.queued_tasks = {}
    download_manager.downloading_mangas = {manga_id: True}
    download_manager.config = {"MANGA_DOWNLOAD_PATH": str(tmp_path)}
    download_manager.logger = SimpleNamespace(
        info=lambda *a: None, error=lambda *a: None
    )
    download_manager.task_log_repo = None
    download_manager.operation_task_service = None
    download_manager.cancelled_downloads = {}

    messages: List[str] = []
    download_manager.message_sender = lambda *args: messages.append(args[1])

    download_manager.delete_manga("10001", manga_id, None, True)

    assert any("正在下载中" in m for m in messages)
    assert pdf_path.exists()
    assert manga_repo.get(manga_id) is not None


def test_batch_delete_skips_active_download(
    tmp_path, manga_repo: MangaRepository, tag_repo: MangaTagRepository
) -> None:
    """批量删除应跳过正在下载中的漫画，保留其文件与记录。"""
    manga_id = "350238"
    pdf_path = tmp_path / f"{manga_id}-标题(1章).pdf"
    pdf_path.write_bytes(b"%PDF")
    _add_manga(manga_repo, manga_id, chapter_count=1)
    manga_repo.add_file(manga_id, str(pdf_path))

    download_manager = object.__new__(DownloadManager)
    download_manager.manga_repo = manga_repo
    download_manager.tag_repo = tag_repo
    download_manager.queued_tasks = {}
    download_manager.downloading_mangas = {manga_id: True}

    messages: List[str] = []
    executor = _build_executor(
        str(tmp_path),
        messages,
        download_manager=download_manager,
        manga_repo=manga_repo,
        tag_repo=tag_repo,
    )

    executor._delete_batch_mangas("10001", [manga_id], None, True)

    assert pdf_path.exists()
    assert manga_repo.get(manga_id) is not None
    assert "正在下载中" in messages[-1]


def test_delete_manga_skips_sending(tmp_path, manga_repo) -> None:
    """文件正在发送中的漫画不应被删除，应返回冲突错误并保留文件。"""
    manga_id = "350239"
    pdf_path = tmp_path / f"{manga_id}-标题(1章).pdf"
    pdf_path.write_bytes(b"%PDF")
    _add_manga(manga_repo, manga_id, chapter_count=1)
    manga_repo.add_file(manga_id, str(pdf_path))

    download_manager = object.__new__(DownloadManager)
    download_manager.manga_repo = manga_repo
    download_manager.tag_repo = None
    download_manager.queued_tasks = {}
    download_manager.downloading_mangas = {}
    download_manager.config = {"MANGA_DOWNLOAD_PATH": str(tmp_path)}
    download_manager.logger = SimpleNamespace(
        info=lambda *a: None, error=lambda *a: None
    )
    download_manager.task_log_repo = None
    download_manager.operation_task_service = None
    download_manager.cancelled_downloads = {}
    download_manager.send_conflict_checker = lambda _manga_id: True

    messages: List[str] = []
    download_manager.message_sender = lambda *args: messages.append(args[1])

    download_manager.delete_manga("10001", manga_id, None, True)

    assert any("正在发送中" in m for m in messages)
    assert pdf_path.exists()
    assert manga_repo.get(manga_id) is not None


def test_batch_delete_skips_sending(
    tmp_path, manga_repo: MangaRepository, tag_repo: MangaTagRepository
) -> None:
    """批量删除应跳过正在发送中的漫画，保留其文件与记录。"""
    manga_id = "350240"
    pdf_path = tmp_path / f"{manga_id}-标题(1章).pdf"
    pdf_path.write_bytes(b"%PDF")
    _add_manga(manga_repo, manga_id, chapter_count=1)
    manga_repo.add_file(manga_id, str(pdf_path))

    download_manager = object.__new__(DownloadManager)
    download_manager.manga_repo = manga_repo
    download_manager.tag_repo = tag_repo
    download_manager.queued_tasks = {}
    download_manager.downloading_mangas = {}

    messages: List[str] = []
    executor = _build_executor(
        str(tmp_path),
        messages,
        download_manager=download_manager,
        manga_repo=manga_repo,
        tag_repo=tag_repo,
    )
    executor.send_conflict_checker = lambda _manga_id: True

    executor._delete_batch_mangas("10001", [manga_id], None, True)

    assert pdf_path.exists()
    assert manga_repo.get(manga_id) is not None
    assert "正在发送中" in messages[-1]


def test_batch_delete_partial_failure_marks_task_failed(
    tmp_path,
    db_manager,
    manga_repo: MangaRepository,
    tag_repo: MangaTagRepository,
    operation_task_service,
) -> None:
    """批量删除部分失败时，任务应标记为失败并记录成功数。"""
    good_id = "350250"
    busy_id = "350251"
    for manga_id in (good_id, busy_id):
        pdf_path = tmp_path / f"{manga_id}-标题(1章).pdf"
        pdf_path.write_bytes(b"%PDF")
        _add_manga(manga_repo, manga_id, chapter_count=1)
        manga_repo.add_file(manga_id, str(pdf_path))

    download_manager = object.__new__(DownloadManager)
    download_manager.manga_repo = manga_repo
    download_manager.tag_repo = tag_repo
    download_manager.queued_tasks = {}
    download_manager.downloading_mangas = {busy_id: True}

    messages: List[str] = []
    executor = _build_executor(
        str(tmp_path),
        messages,
        download_manager=download_manager,
        manga_repo=manga_repo,
        tag_repo=tag_repo,
    )
    executor.operation_task_service = operation_task_service

    executor._delete_batch_mangas("10001", [good_id, busy_id], None, True)

    tasks = OperationTaskRepository(db_manager).list()
    assert len(tasks) == 1
    assert tasks[0].status == "failed"
    assert (tmp_path / f"{good_id}-标题(1章).pdf").exists() is False
    assert (tmp_path / f"{busy_id}-标题(1章).pdf").exists() is True
    assert manga_repo.get(busy_id) is not None
