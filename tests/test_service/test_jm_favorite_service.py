"""JM 收藏导入：分页完整性、会话隔离与部分失败测试，均不访问站点。"""

from dataclasses import dataclass, field
from datetime import timedelta
from threading import Event
from typing import Dict, List, Tuple

import pytest

from src.database.models import utc_now
from src.database.repositories import (
    FavoriteRepository,
    JmFavoriteRepository,
    MangaRepository,
    WebAdminRepository,
)
from src.service.jm_favorite_service import JmFavoriteError, JmFavoriteService
from src.service.web_auth_service import AuthenticatedSession


@dataclass
class FakePage:
    """收藏响应仅含接口承诺的编号、标题和收藏夹。"""

    items: List[Tuple[str, str]]
    total: int = 3
    folders: Dict[str, str] = field(default_factory=lambda: {"7": "精选", "8": "待看"})

    def iter_id_title(self):
        return iter(self.items)

    def iter_folder_id_name(self):
        return iter(self.folders.items())


class FakeClient:
    """可控制分页失败与等待，禁止真实 HTTP 请求。"""

    def __init__(self):
        self.login_calls = []
        self.requested_folders = []
        self.pages = {
            "0": [
                FakePage([("100", "漫画一"), ("200", "漫画二")]),
                FakePage([("300", "漫画三")]),
            ],
            "7": [FakePage([("100", "漫画一"), ("200", "漫画二")])],
            "8": [FakePage([("200", "漫画二")])],
        }
        self.failure = False
        self.started = Event()
        self.release = Event()
        self.block = False

    def login(self, username, password):
        self.login_calls.append((username, password))
        # 非 bool 返回值也表示成功，模拟真实客户端返回响应对象。
        return object()

    def favorite_folder(self):
        return self.pages["0"][0]

    def favorite_folder_gen(self, folder_id):
        self.requested_folders.append(folder_id)
        for index, page in enumerate(self.pages[folder_id]):
            if index == 1:
                if self.block:
                    self.started.set()
                    assert self.release.wait(5)
                if self.failure:
                    raise RuntimeError("上游响应含 password=secret cookie=private")
            yield page


def make_service(db_manager, client=None):
    WebAdminRepository(db_manager).create("test-hash")
    client = client if client is not None else FakeClient()
    service = JmFavoriteService(JmFavoriteRepository(db_manager), lambda: client)
    authenticated = AuthenticatedSession(
        "web-session", 1, utc_now() + timedelta(hours=1)
    )
    service.login(authenticated, "user", "secret")
    return service, authenticated, client


def wait_for_import(service, authenticated, job):
    assert service._worker is not None
    service._worker.join(5)
    assert not service._worker.is_alive()
    return service.repository.get(authenticated.admin_id, job["id"])


def test_all_folders_pagination_membership_and_idempotence(db_manager, tmp_path):
    service, auth, client = make_service(db_manager)
    mangas = MangaRepository(db_manager, str(tmp_path))
    mangas.upsert("100", "本地标题", "作者", 1, 5)
    pdf = tmp_path / "100.pdf"
    pdf.write_bytes(b"%PDF")
    mangas.add_file("100", str(pdf))
    mangas.upsert("999", "手工收藏", "", 1, 1)
    favorites = FavoriteRepository(db_manager)
    favorites.set_favorite("web_admin", "1", "999", True)
    favorites.set_favorite("qq", "123", "999", True)
    job = wait_for_import(service, auth, service.start_import(auth, ["0", "7", "0"]))
    assert job.status == "succeeded"
    assert (
        job.pages_done,
        job.imported_count,
        job.duplicate_count,
        job.local_count,
    ) == (4, 3, 0, 1)
    assert client.requested_folders == ["0", "7", "8"]
    rows = service.repository.list_favorites(1, 1, 20)
    by_id = {item["manga_id"]: item for item in rows["items"]}
    assert rows["total"] == 3
    assert by_id["200"]["folders"] == {"0": "全部收藏", "7": "精选", "8": "待看"}
    assert by_id["100"]["downloaded"]
    assert not by_id["200"]["downloaded"]
    assert mangas.get("200") is None
    assert favorites.get("web_admin", "1", "100") is not None
    assert favorites.get("web_admin", "1", "999") is not None
    assert favorites.get("qq", "123", "999") is not None
    repeated = wait_for_import(service, auth, service.start_import(auth, ["0"]))
    assert (
        repeated.imported_count,
        repeated.duplicate_count,
        repeated.local_count,
    ) == (0, 3, 1)
    assert mangas.get("100").title == "本地标题"
    assert mangas.get("100").page_count == 5
    assert service.repository.list_favorites(1, 1, 1)["pages"] == 3
    assert service.repository.list_favorites(1, 1, 20, folder_id="8")["total"] == 1
    assert (
        service.repository.list_favorites(1, 1, 20, download_status="not_downloaded")[
            "total"
        ]
        == 2
    )
    assert (
        service.repository.list_favorites(1, 1, 20, download_status="downloaded")[
            "total"
        ]
        == 1
    )
    assert service.repository.list_favorites(1, 1, 20, search="%")["total"] == 0


def test_partial_failure_retains_pages_without_secret(db_manager):
    service, auth, client = make_service(db_manager)
    client.failure = True
    job = wait_for_import(service, auth, service.start_import(auth, ["0"]))
    assert job.status == "failed"
    assert (job.pages_done, job.imported_count) == (1, 2)
    assert "RuntimeError" in job.error_message
    assert "secret" not in job.error_message and "private" not in job.error_message
    assert service.repository.list_favorites(1, 1, 20)["total"] == 2
    client.failure = False
    retry = wait_for_import(service, auth, service.start_import(auth, ["0"]))
    assert (retry.status, retry.imported_count, retry.duplicate_count) == (
        "succeeded",
        1,
        2,
    )


def test_session_isolation_concurrent_rejection_and_logout(db_manager):
    service, auth, client = make_service(db_manager)
    other = AuthenticatedSession("another-session", 1, auth.expires_at)
    assert service.account_status(other) == {"connected": False}
    with pytest.raises(JmFavoriteError, match="未登录"):
        service.start_import(other, ["0"])
    client.block = True
    job = service.start_import(auth, ["0"])
    assert client.started.wait(5)
    with pytest.raises(JmFavoriteError, match="正在执行"):
        service.start_import(auth, ["7"])
    with pytest.raises(JmFavoriteError, match="正在登录或导入"):
        service.login(auth, "another", "secret")
    assert service.repository.get(2, job["id"]) is None
    assert service.repository.list_favorites(2, 1, 20)["total"] == 0
    service.logout(auth.session_id)
    client.release.set()
    result = wait_for_import(service, auth, job)
    assert result.status == "interrupted"
    assert result.imported_count == 2
    assert service.account_status(auth) == {"connected": False}


def test_expired_sessions_and_invalid_folder_do_not_create_tasks(db_manager):
    service, auth, _client = make_service(db_manager)
    for folders in [[], ["unknown"], ["7", "unknown"]]:
        with pytest.raises(JmFavoriteError, match="有效的收藏夹"):
            service.start_import(auth, folders)
    assert service.repository.list(1) == []
    service._sessions[auth.session_id].expires_at = utc_now() - timedelta(seconds=1)
    service.cleanup_expired()
    assert service._sessions == {}
    with pytest.raises(JmFavoriteError, match="已过期"):
        service.start_import(auth, ["0"])


def test_new_download_links_once_and_preserves_manual_unfavorite(db_manager, tmp_path):
    service, auth, _client = make_service(db_manager)
    wait_for_import(service, auth, service.start_import(auth, ["7"]))
    mangas = MangaRepository(db_manager, str(tmp_path))
    mangas.upsert("100", "新下载", "", 1, 2)
    pdf = tmp_path / "100.pdf"
    pdf.write_bytes(b"%PDF")
    mangas.add_file("100", str(pdf))
    favorites = FavoriteRepository(db_manager)
    assert favorites.get("web_admin", "1", "100") is not None
    favorites.set_favorite("web_admin", "1", "100", False)
    mangas.add_file("100", str(pdf))
    assert favorites.get("web_admin", "1", "100") is None
    wait_for_import(service, auth, service.start_import(auth, ["7"]))
    assert favorites.get("web_admin", "1", "100") is not None


def test_accounts_deduplicate_separately_and_restart_marks_interrupted(db_manager):
    service, auth, _client = make_service(db_manager)
    wait_for_import(service, auth, service.start_import(auth, ["7"]))
    service.login(auth, "second", "secret")
    second = wait_for_import(service, auth, service.start_import(auth, ["7"]))
    assert second.imported_count == 2
    assert service.repository.list_favorites(1, 1, 20)["total"] == 4
    assert service.repository.list_favorites(1, 1, 20, username="user")["total"] == 2
    service.repository.create_import(1, "interrupted-job", "second", ["7"])
    restarted = JmFavoriteService(service.repository)
    assert restarted.repository.get(1, "interrupted-job").status == "interrupted"
    assert restarted.account_status(auth) == {"connected": False}
    assert restarted.repository.list_favorites(1, 1, 20)["total"] == 4
