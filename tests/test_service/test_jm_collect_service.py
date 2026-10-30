"""JM 收藏入库与本地状态服务测试，均不访问真实站点。"""

from pathlib import Path
from typing import List

import pytest
from jmcomic import MissingAlbumPhotoException

from src.database.repositories import FavoriteRepository, MangaRepository
from src.service.jm_collect_service import JmCollectError, JmCollectService
from src.service.jm_search_service import JmSearchError
from tests.test_service.test_jm_search_service import FakeAlbumDetail, FakeClient


def make_detail(album_id: str = "100") -> FakeAlbumDetail:
    """构造带完整站点快照字段的漫画详情替身。"""
    return FakeAlbumDetail(
        album_id=album_id,
        title="远程标题",
        author="作者甲,作者乙",
        tags=["恋爱", "校园"],
        page_count=88,
        episode_list=[
            ("1001", "1", "第一话", "2026-01-01"),
            ("1002", "2", "第二话", "2026-01-02"),
        ],
        name="远程标题",
        authors=["作者甲", "作者乙"],
        description="远程简介",
        pub_date="2026-01-01",
        update_date="0",
        works=["作品"],
        actors=["声优"],
    )


class RecordingClient(FakeClient):
    """记录并可按漫画编号抛出异常的客户端替身。"""

    def __init__(self, details: List[FakeAlbumDetail]) -> None:
        super().__init__()
        self.details = {detail.album_id: detail for detail in details}
        self.requested_ids: List[str] = []

    def get_album_detail(self, album_id: str) -> FakeAlbumDetail:
        self.requested_ids.append(album_id)
        if self.error is not None:
            raise self.error
        if album_id not in self.details:
            raise MissingAlbumPhotoException(f"album {album_id} missing", {})
        return self.details[album_id]


def make_service(
    manga_repo: MangaRepository,
    tag_repo,
    favorite_repo: FavoriteRepository,
    client: RecordingClient,
) -> JmCollectService:
    """绑定真实仓储与本地客户端替身。"""
    return JmCollectService(
        manga_repo, tag_repo, favorite_repo, client_factory=lambda: client
    )


def test_collect_new_album_writes_favorited_snapshot_and_tags(
    manga_repo: MangaRepository, tag_repo, db_manager
) -> None:
    """本地不存在时联网取信息，以收藏态入库并写入完整站点快照。"""
    favorite_repo = FavoriteRepository(db_manager)
    client = RecordingClient([make_detail()])
    service = make_service(manga_repo, tag_repo, favorite_repo, client)

    result = service.collect_albums(["100", "100"], admin_id=1)

    assert result == {"collected_count": 1, "already_count": 0, "failed": []}
    assert client.requested_ids == ["100"]
    manga = manga_repo.get("100")
    assert manga is not None
    assert manga.status == "favorited"
    assert manga.title == "远程标题"
    assert manga.author == "作者甲,作者乙"
    assert manga.chapter_count == 0
    assert manga.page_count == 0
    assert manga.description == "远程简介"
    assert manga.remote_metadata["chapter_count"] == 2
    assert manga.remote_metadata["page_count"] == 88
    assert manga.remote_metadata["chapters"][0]["id"] == "1001"
    assert tag_repo.list_for_manga("100") == ["恋爱", "校园"]
    assert favorite_repo.has_admin_favorite("100") is True


def test_collect_existing_downloaded_only_adds_favorite(
    manga_repo: MangaRepository, tag_repo, db_manager, tmp_path
) -> None:
    """已下载漫画只补管理员收藏，不覆盖标题与文件元数据。"""
    favorite_repo = FavoriteRepository(db_manager)
    pdf = tmp_path / "100.pdf"
    pdf.write_bytes(b"%PDF")
    manga_repo.upsert("100", "用户标题", "用户作者", 5, 99, status="downloaded")
    manga_repo.add_file("100", str(pdf))
    client = RecordingClient([])
    service = make_service(manga_repo, tag_repo, favorite_repo, client)

    result = service.collect_albums(["100"], admin_id=2)

    assert result == {"collected_count": 0, "already_count": 1, "failed": []}
    assert client.requested_ids == []
    manga = manga_repo.get("100")
    assert manga is not None
    assert manga.status == "downloaded"
    assert manga.title == "用户标题"
    assert manga.chapter_count == 5
    assert manga.page_count == 99
    assert favorite_repo.has_admin_favorite("100") is True


def test_collect_favorited_album_is_idempotent(
    manga_repo: MangaRepository, tag_repo, db_manager
) -> None:
    """重复收藏同一本已入库漫画不重复联网，也不重复创建记录。"""
    favorite_repo = FavoriteRepository(db_manager)
    client = RecordingClient([make_detail()])
    service = make_service(manga_repo, tag_repo, favorite_repo, client)

    first = service.collect_albums(["100"], admin_id=1)
    second = service.collect_albums(["100"], admin_id=1)

    assert first == {"collected_count": 1, "already_count": 0, "failed": []}
    assert second == {"collected_count": 0, "already_count": 1, "failed": []}
    assert client.requested_ids == ["100"]
    assert manga_repo.count() == 1


def test_collect_batch_keeps_successes_when_one_album_fails(
    manga_repo: MangaRepository, tag_repo, db_manager
) -> None:
    """批量收藏逐项返回失败，不因单本不存在中断其他漫画。"""
    favorite_repo = FavoriteRepository(db_manager)
    client = RecordingClient([make_detail("100")])
    service = make_service(manga_repo, tag_repo, favorite_repo, client)

    result = service.collect_albums(["100", "200"], admin_id=1)

    assert result["collected_count"] == 1
    assert result["already_count"] == 0
    assert result["failed"] == [{"album_id": "200", "error": "漫画不存在或已下架"}]
    assert manga_repo.get("100") is not None
    assert manga_repo.get("200") is None


def test_collect_maps_upstream_error_without_leaking_text(
    manga_repo: MangaRepository, tag_repo, db_manager
) -> None:
    """上游异常只暴露类型，不透传可能含凭据的原始文本。"""
    favorite_repo = FavoriteRepository(db_manager)
    client = RecordingClient([])
    client.error = RuntimeError("cookie=secret password=private")
    service = make_service(manga_repo, tag_repo, favorite_repo, client)

    result = service.collect_albums(["100"], admin_id=1)

    failed = result["failed"]
    assert failed == [{"album_id": "100", "error": "收藏失败（RuntimeError）"}]
    assert "secret" not in str(failed)
    assert "private" not in str(failed)


@pytest.mark.parametrize(
    ("album_ids", "code"),
    [
        ([], "JM_INVALID_ALBUM_IDS"),
        (["abc"], "JM_INVALID_ALBUM_ID"),
        (["1" * 33], "JM_INVALID_ALBUM_ID"),
        ([str(index) for index in range(101)], "JM_TOO_MANY_ALBUMS"),
    ],
)
def test_collect_rejects_invalid_requests(
    manga_repo: MangaRepository, tag_repo, db_manager, album_ids, code
) -> None:
    """非法编号与超限请求在联网前直接返回中文错误。"""
    favorite_repo = FavoriteRepository(db_manager)
    client = RecordingClient([])
    service = make_service(manga_repo, tag_repo, favorite_repo, client)

    with pytest.raises(JmCollectError) as error_info:
        service.collect_albums(album_ids, admin_id=1)

    assert error_info.value.code == code
    assert client.requested_ids == []


def test_local_statuses_reports_exists_favorited_and_downloaded(
    manga_repo: MangaRepository, tag_repo, db_manager, tmp_path
) -> None:
    """本地状态供列表和详情复用，删除文件后不再判定为已下载。"""
    favorite_repo = FavoriteRepository(db_manager)
    pdf = Path(tmp_path) / "100.pdf"
    pdf.write_bytes(b"%PDF")
    manga_repo.upsert("100", "已下载", "", 1, 10, status="downloaded")
    manga_repo.add_file("100", str(pdf))
    favorite_repo.set_favorite("web_admin", "1", "100", True)
    manga_repo.upsert("200", "已收藏", "", 0, 0, status="favorited")
    favorite_repo.set_favorite("web_admin", "1", "200", True)
    client = RecordingClient([])
    service = make_service(manga_repo, tag_repo, favorite_repo, client)

    statuses = service.local_statuses(["100", "200", "300"])

    assert statuses["100"] == {
        "exists": True,
        "status": "downloaded",
        "favorited": True,
        "downloaded": True,
    }
    assert statuses["200"] == {
        "exists": True,
        "status": "favorited",
        "favorited": True,
        "downloaded": False,
    }
    assert statuses["300"] == {
        "exists": False,
        "status": None,
        "favorited": False,
        "downloaded": False,
    }

    pdf.unlink()
    assert service.local_status("100")["downloaded"] is False


def test_collect_reuses_search_error_types() -> None:
    """收藏服务与搜索服务使用相互独立的稳定错误类型。"""
    assert not issubclass(JmCollectError, JmSearchError)
