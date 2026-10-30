"""JM 作者搜索与漫画概要服务测试，均不访问真实站点。"""

from dataclasses import dataclass, field
from typing import List, Tuple

import pytest
from jmcomic import MissingAlbumPhotoException

from src.service.jm_search_service import JmSearchError, JmSearchService


@dataclass
class FakeSearchPage:
    """搜索分页替身，字段与 JmSearchPage 保持一致。"""

    items: List[Tuple[str, str, List[str]]]
    total: int
    page_count: int
    page_size: int = 20

    def iter_id_title_tag(self):
        return iter(self.items)


@dataclass
class FakeAlbumDetail:
    """漫画概要替身，章节列表使用真实接口的元组结构。"""

    album_id: str
    title: str
    author: str
    tags: List[str]
    page_count: int
    episode_list: List[Tuple[str, str, str, str]] = field(default_factory=list)
    name: str = ""
    authors: List[str] = field(default_factory=list)
    description: str = ""
    pub_date: str = "0"
    update_date: str = "0"
    works: List[str] = field(default_factory=list)
    actors: List[str] = field(default_factory=list)


class FakeClient:
    """记录调用参数，并可注入上游异常。"""

    def __init__(
        self,
        search_page: FakeSearchPage | None = None,
        album_detail: FakeAlbumDetail | None = None,
        error: Exception | None = None,
    ) -> None:
        self.search_page = search_page or FakeSearchPage([], total=0, page_count=0)
        self.album_detail = album_detail or FakeAlbumDetail(
            "100", "测试漫画", "作者", [], 0
        )
        self.error = error
        self.search_calls: List[Tuple[str, int]] = []
        self.detail_calls: List[str] = []

    def search_author(self, author: str, page: int = 1) -> FakeSearchPage:
        self.search_calls.append((author, page))
        if self.error is not None:
            raise self.error
        return self.search_page

    def get_album_detail(self, album_id: str) -> FakeAlbumDetail:
        self.detail_calls.append(album_id)
        if self.error is not None:
            raise self.error
        return self.album_detail


def make_service(client: FakeClient) -> JmSearchService:
    return JmSearchService(lambda: client)


def test_search_author_returns_results_and_page_metadata() -> None:
    client = FakeClient(
        FakeSearchPage(
            [
                ("100", "漫画一", ["恋爱", "校园"]),
                ("200", "漫画二", []),
            ],
            total=45,
            page_count=3,
        )
    )

    result = make_service(client).search_author("测试作者", 2)

    assert client.search_calls == [("测试作者", 2)]
    assert result == {
        "results": [
            {
                "album_id": "100",
                "title": "漫画一",
                "author": "测试作者",
                "tags": ["恋爱", "校园"],
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


@pytest.mark.parametrize(
    ("author", "page", "code"),
    [
        ("", 1, "JM_INVALID_AUTHOR"),
        ("   ", 1, "JM_INVALID_AUTHOR"),
        ("作者", 0, "JM_INVALID_PAGE"),
    ],
)
def test_search_author_rejects_invalid_parameters(
    author: str, page: int, code: str
) -> None:
    client = FakeClient()

    with pytest.raises(JmSearchError) as error_info:
        make_service(client).search_author(author, page)

    assert error_info.value.code == code
    assert error_info.value.status == 400
    assert client.search_calls == []


def test_search_author_maps_upstream_error_without_leaking_text() -> None:
    client = FakeClient(error=RuntimeError("cookie=secret password=private"))

    with pytest.raises(JmSearchError) as error_info:
        make_service(client).search_author("作者")

    error = error_info.value
    assert (error.code, error.status) == ("JM_SEARCH_FAILED", 502)
    assert "secret" not in str(error)
    assert "private" not in str(error)
    assert "RuntimeError" in str(error)


def test_get_album_detail_returns_summary_and_chapter_ids() -> None:
    client = FakeClient(
        album_detail=FakeAlbumDetail(
            album_id="100",
            title="测试漫画",
            author="作者",
            tags=["标签一", "标签二"],
            page_count=88,
            episode_list=[
                ("1001", "1", "第一话", "2026-01-01"),
                ("1002", "2", "第二话", "2026-01-02"),
            ],
        )
    )

    result = make_service(client).get_album_detail("100")

    assert client.detail_calls == ["100"]
    assert result == {
        "album_id": "100",
        "title": "测试漫画",
        "author": "作者",
        "tags": ["标签一", "标签二"],
        "page_count": 88,
        "chapter_ids": ["1001", "1002"],
    }


@pytest.mark.parametrize("album_id", ["", "abc", "12a", "1" * 33])
def test_get_album_detail_rejects_invalid_id(album_id: str) -> None:
    client = FakeClient()

    with pytest.raises(JmSearchError) as error_info:
        make_service(client).get_album_detail(album_id)

    assert error_info.value.code == "JM_INVALID_ALBUM_ID"
    assert error_info.value.status == 400
    assert client.detail_calls == []


def test_get_album_detail_maps_missing_album_to_conflict() -> None:
    client = FakeClient(error=MissingAlbumPhotoException("album 100 missing", {}))

    with pytest.raises(JmSearchError) as error_info:
        make_service(client).get_album_detail("100")

    error = error_info.value
    assert (error.code, error.status) == ("JM_ALBUM_NOT_FOUND", 409)
    assert str(error) == "漫画不存在或已下架"
    assert "missing" not in str(error)


def test_get_album_detail_maps_upstream_error_without_leaking_text() -> None:
    client = FakeClient(error=RuntimeError("cookie=secret password=private"))

    with pytest.raises(JmSearchError) as error_info:
        make_service(client).get_album_detail("100")

    error = error_info.value
    assert (error.code, error.status) == ("JM_ALBUM_DETAIL_FAILED", 502)
    assert "secret" not in str(error)
    assert "private" not in str(error)
    assert "RuntimeError" in str(error)
