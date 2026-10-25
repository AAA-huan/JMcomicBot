"""管理员鉴权下的 JM 作者搜索与漫画概要 API 测试。"""

from jmcomic import MissingAlbumPhotoException

from tests.test_service.test_jm_search_service import (
    FakeAlbumDetail,
    FakeClient,
    FakeSearchPage,
)
from tests.test_web.support import create_client_for, setup_and_login


def _fake_search_client() -> FakeClient:
    return FakeClient(
        FakeSearchPage(
            [
                ("100", "漫画一", ["恋爱"]),
                ("200", "漫画二", []),
            ],
            total=45,
            page_count=3,
        ),
        FakeAlbumDetail(
            album_id="100",
            title="测试漫画",
            author="测试作者",
            tags=["恋爱"],
            page_count=88,
            episode_list=[("1001", "1", "第一话", "2026-01-01")],
        ),
    )


def test_jm_search_endpoints_require_login(db_manager) -> None:
    client, _context = create_client_for(db_manager)

    with client:
        assert (
            client.get(
                "/api/v1/jm/search/author", params={"author": "作者"}
            ).status_code
            == 401
        )
        assert client.get("/api/v1/jm/album/100").status_code == 401


def test_search_author_validates_parameters(db_manager) -> None:
    client, context = create_client_for(db_manager)
    context.dependencies.jm_search_service.client_factory = _fake_search_client

    with client:
        setup_and_login(client)
        missing = client.get("/api/v1/jm/search/author")
        blank = client.get("/api/v1/jm/search/author", params={"author": "   "})
        bad_page = client.get(
            "/api/v1/jm/search/author", params={"author": "作者", "page": 0}
        )

    assert missing.status_code == 400
    assert missing.json()["code"] == "JM_INVALID_AUTHOR"
    assert blank.status_code == 400
    assert bad_page.status_code == 400
    assert bad_page.json()["code"] == "JM_INVALID_PAGE"


def test_search_author_returns_page_structure(db_manager) -> None:
    client, context = create_client_for(db_manager)
    fake = _fake_search_client()
    context.dependencies.jm_search_service.client_factory = lambda: fake

    with client:
        setup_and_login(client)
        response = client.get(
            "/api/v1/jm/search/author", params={"author": "测试作者", "page": 2}
        )

    assert response.status_code == 200
    assert response.json() == {
        "results": [
            {
                "album_id": "100",
                "title": "漫画一",
                "author": "测试作者",
                "tags": ["恋爱"],
            },
            {
                "album_id": "200",
                "title": "漫画二",
                "author": "测试作者",
                "tags": [],
            },
        ],
        "page": 2,
        "page_count": 3,
        "page_size": 20,
        "total": 45,
    }
    assert fake.search_calls == [("测试作者", 2)]


def test_search_author_maps_upstream_error(db_manager) -> None:
    client, context = create_client_for(db_manager)
    context.dependencies.jm_search_service.client_factory = lambda: FakeClient(
        error=RuntimeError("cookie=secret password=private")
    )

    with client:
        setup_and_login(client)
        response = client.get("/api/v1/jm/search/author", params={"author": "作者"})

    assert response.status_code == 502
    assert response.json()["code"] == "JM_SEARCH_FAILED"
    assert "secret" not in response.text
    assert "private" not in response.text


def test_album_detail_returns_summary_and_maps_errors(db_manager) -> None:
    client, context = create_client_for(db_manager)
    fake = _fake_search_client()
    context.dependencies.jm_search_service.client_factory = lambda: fake

    with client:
        setup_and_login(client)
        detail = client.get("/api/v1/jm/album/100")
        invalid = client.get("/api/v1/jm/album/not-a-number")
        fake.error = MissingAlbumPhotoException("album 999 missing", {})
        missing = client.get("/api/v1/jm/album/999")
        fake.error = RuntimeError("cookie=secret password=private")
        failed = client.get("/api/v1/jm/album/100")

    assert detail.status_code == 200
    assert detail.json() == {
        "album_id": "100",
        "title": "测试漫画",
        "author": "测试作者",
        "tags": ["恋爱"],
        "page_count": 88,
        "chapter_ids": ["1001"],
    }
    assert fake.detail_calls[0] == "100"
    assert invalid.status_code == 400
    assert invalid.json()["code"] == "JM_INVALID_ALBUM_ID"
    assert missing.status_code == 409
    assert missing.json()["code"] == "JM_ALBUM_NOT_FOUND"
    assert failed.status_code == 502
    assert failed.json()["code"] == "JM_ALBUM_DETAIL_FAILED"
    assert "secret" not in failed.text
    assert "private" not in failed.text
