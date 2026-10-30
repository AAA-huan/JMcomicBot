"""管理员收藏远程漫画与本地状态 API 测试。"""

from pathlib import Path

from src.database.repositories import FavoriteRepository, MangaRepository
from tests.test_service.test_jm_collect_service import RecordingClient, make_detail
from tests.test_service.test_jm_search_service import FakeSearchPage
from tests.test_web.support import csrf_headers, create_client_for, setup_and_login


def _set_client(context, client: RecordingClient) -> None:
    context.dependencies.jm_collect_service.client_factory = lambda: client


def test_favorite_album_writes_favorited_record_and_metadata(db_manager) -> None:
    """收藏接口联网取信息后以收藏态入库，不下载漫画本体。"""
    client, context = create_client_for(db_manager)
    fake = RecordingClient([make_detail()])
    _set_client(context, fake)

    with client:
        setup_and_login(client)
        response = client.post(
            "/api/v1/jm/albums/favorite",
            json={"album_ids": ["100", "100"]},
            headers=csrf_headers(client),
        )

    assert response.status_code == 200
    assert response.json() == {
        "collected_count": 1,
        "already_count": 0,
        "failed": [],
    }
    assert fake.requested_ids == ["100"]
    repo = MangaRepository(
        db_manager, download_root=str(Path(db_manager.db_dir).parent)
    )
    manga = repo.get("100")
    assert manga is not None
    assert manga.status == "favorited"
    assert manga.title == "远程标题"
    assert manga.chapter_count == 0
    assert manga.page_count == 0
    assert manga.remote_metadata["chapter_count"] == 2
    assert FavoriteRepository(db_manager).has_admin_favorite("100") is True


def test_favorite_existing_downloaded_only_adds_favorite(db_manager, tmp_path) -> None:
    """已下载漫画再次收藏时只补收藏，不联网覆盖元数据。"""
    client, context = create_client_for(db_manager)
    repo = MangaRepository(db_manager, download_root=str(tmp_path))
    pdf = tmp_path / "100.pdf"
    pdf.write_bytes(b"%PDF")
    repo.upsert("100", "本地标题", "本地作者", 3, 30, status="downloaded")
    repo.add_file("100", str(pdf))
    fake = RecordingClient([])
    _set_client(context, fake)

    with client:
        setup_and_login(client)
        response = client.post(
            "/api/v1/jm/albums/favorite",
            json={"album_ids": ["100"]},
            headers=csrf_headers(client),
        )

    assert response.status_code == 200
    assert response.json() == {
        "collected_count": 0,
        "already_count": 1,
        "failed": [],
    }
    assert fake.requested_ids == []
    manga = repo.get("100")
    assert manga is not None
    assert manga.title == "本地标题"
    assert manga.status == "downloaded"
    assert FavoriteRepository(db_manager).has_admin_favorite("100") is True


def test_favorite_album_reports_partial_failure(db_manager) -> None:
    """单本不存在时在 failed 中返回中文原因，其余漫画继续收藏。"""
    client, context = create_client_for(db_manager)
    _set_client(context, RecordingClient([make_detail("100")]))

    with client:
        setup_and_login(client)
        response = client.post(
            "/api/v1/jm/albums/favorite",
            json={"album_ids": ["100", "200"]},
            headers=csrf_headers(client),
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["collected_count"] == 1
    assert payload["failed"] == [{"album_id": "200", "error": "漫画不存在或已下架"}]


def test_favorite_album_rejects_invalid_id(db_manager) -> None:
    """非法编号返回 400 中文错误，不触发联网。"""
    client, context = create_client_for(db_manager)
    fake = RecordingClient([])
    _set_client(context, fake)

    with client:
        setup_and_login(client)
        response = client.post(
            "/api/v1/jm/albums/favorite",
            json={"album_ids": ["abc"]},
            headers=csrf_headers(client),
        )

    assert response.status_code == 400
    assert response.json()["code"] == "JM_INVALID_ALBUM_ID"
    assert fake.requested_ids == []


def test_search_and_detail_include_local_status(db_manager, tmp_path) -> None:
    """作者搜索与详情均附带本地存在、收藏、下载状态。"""
    client, context = create_client_for(db_manager)
    repo = MangaRepository(db_manager, download_root=str(tmp_path))
    favorite_repo = FavoriteRepository(db_manager)
    pdf = tmp_path / "100.pdf"
    pdf.write_bytes(b"%PDF")
    repo.upsert("100", "已下载", "", 1, 10, status="downloaded")
    repo.add_file("100", str(pdf))
    favorite_repo.set_favorite("web_admin", "1", "100", True)
    repo.upsert("200", "已收藏", "", 0, 0, status="favorited")
    favorite_repo.set_favorite("web_admin", "1", "200", True)
    fake = RecordingClient([make_detail("100"), make_detail("200")])
    fake.search_page = FakeSearchPage(
        [("100", "漫画一", []), ("200", "漫画二", [])],
        total=2,
        page_count=1,
    )
    _set_client(context, fake)
    context.dependencies.jm_search_service.client_factory = lambda: fake

    with client:
        setup_and_login(client)
        search = client.get("/api/v1/jm/search/author", params={"author": "作者"})
        detail = client.get("/api/v1/jm/album/100")

    assert search.status_code == 200
    results = {item["album_id"]: item["local"] for item in search.json()["results"]}
    assert results["100"] == {
        "exists": True,
        "status": "downloaded",
        "favorited": True,
        "downloaded": True,
    }
    assert results["200"] == {
        "exists": True,
        "status": "favorited",
        "favorited": True,
        "downloaded": False,
    }
    assert detail.status_code == 200
    assert detail.json()["local"] == {
        "exists": True,
        "status": "downloaded",
        "favorited": True,
        "downloaded": True,
    }
