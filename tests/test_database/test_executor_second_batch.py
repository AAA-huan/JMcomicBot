"""第二批用户交互 bug 的 executor 层回归测试"""

from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional

from src.command.executor import CommandExecutor
from src.database.repositories import MangaRepository, MangaTagRepository
from src.download.manager import DownloadManager


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
        manga_repo=manga_repo,
        tag_repo=tag_repo,
    )


def _add_manga(manga_repo: MangaRepository, manga_id: str, chapter_count: int) -> None:
    """写入测试漫画元数据"""
    manga_repo.upsert(
        manga_id=manga_id,
        title=f"标题{manga_id}",
        author="作者",
        tags="纯爱,后宫",
        chapter_count=chapter_count,
        page_count=100,
    )


def test_unknown_command_replies(tmp_path) -> None:
    """未知命令应明确回复用户，而不是只写日志"""
    messages: List[str] = []
    executor = _build_executor(
        str(tmp_path), messages, download_manager=_DownloadManager()
    )

    executor.execute_command("10001", "哈哈哈")

    assert messages == ["❓ 未知命令，请输入'漫画帮助'查看所有可用命令"]


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
        tag_repo.add("纯爱", manga_id, pdf_path.name)

    download_manager = object.__new__(DownloadManager)
    download_manager.manga_repo = manga_repo
    download_manager.tag_repo = tag_repo

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
