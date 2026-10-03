"""低内存模式文件清理不能绕过管理员收藏保护。"""

from unittest.mock import Mock

from src.database.repositories import FavoriteRepository, MangaRepository
from src.download.manager import DownloadManager


def create_manager(root, manga_repo, monkeypatch, low_memory):
    """使用真实仓储，仅禁用与本测试无关的下载队列线程。"""
    monkeypatch.setattr(
        DownloadManager, "_start_download_queue_processor", lambda _self: None
    )
    return DownloadManager(
        Mock(),
        {"MANGA_DOWNLOAD_PATH": str(root), "LOW_MEMORY_MODE": low_memory},
        lambda *_args: None,
        manga_repo=manga_repo,
    )


def test_low_memory_startup_preserves_registered_admin_favorite(
    tmp_path, db_manager, monkeypatch
):
    """改名 PDF 的保护按登记路径匹配；非管理员收藏仍按原规则清理。"""
    root = tmp_path / "downloads"
    root.mkdir()
    mangas = MangaRepository(db_manager, str(root))
    favorites = FavoriteRepository(db_manager)
    for manga_id, filename, owner in [
        ("100", "renamed.pdf", "web_admin"),
        ("200", "other.pdf", "qq"),
    ]:
        file = root / filename
        file.write_bytes(b"%PDF")
        mangas.upsert(manga_id, "漫画", "", 1, 1)
        mangas.add_file(manga_id, str(file))
        favorites.set_favorite(owner, "1", manga_id, True)
    manager = create_manager(root, mangas, monkeypatch, True)
    assert (root / "renamed.pdf").exists()
    assert not (root / "other.pdf").exists()
    favorites.set_favorite("web_admin", "1", "100", False)
    manager._clear_download_folder()
    assert not (root / "renamed.pdf").exists()


def test_delayed_cleanup_reads_latest_favorites(tmp_path, db_manager, monkeypatch):
    """定时任务排入后才收藏也能保留；取消后正常清理可删除文件。"""
    mangas = MangaRepository(db_manager, str(tmp_path))
    nested = tmp_path / "nested"
    nested.mkdir()
    file = nested / "renamed.pdf"
    file.write_bytes(b"%PDF")
    mangas.upsert("100", "漫画", "", 1, 1)
    mangas.add_file("100", str(file))
    favorites = FavoriteRepository(db_manager)
    manager = create_manager(tmp_path, mangas, monkeypatch, False)
    callbacks = []

    class DeferredThread:
        def __init__(self, target, daemon):
            del daemon
            self.target = target

        def start(self):
            callbacks.append(self.target)

    monkeypatch.setattr("src.download.manager.threading.Thread", DeferredThread)
    monkeypatch.setattr("src.download.manager.time.sleep", lambda _seconds: None)
    manager._schedule_file_deletion(str(file))
    favorites.set_favorite("web_admin", "1", "100", True)
    callbacks.pop()()
    assert file.exists()
    favorites.set_favorite("web_admin", "1", "100", False)
    manager._schedule_file_deletion(str(file))
    callbacks.pop()()
    assert not file.exists()
