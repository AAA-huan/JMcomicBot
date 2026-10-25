"""JM 远程作者搜索与漫画概要查询，不保存 Cookie 或下载内容。"""

from typing import Callable, Dict, Iterator, List, Protocol, Tuple, cast

from jmcomic import JmOption, MissingAlbumPhotoException


class SearchPage(Protocol):
    """仅使用搜索分页结果中明确存在的字段。"""

    total: int
    page_count: int
    page_size: int

    def iter_id_title_tag(self) -> Iterator[Tuple[str, str, List[str]]]:
        """遍历漫画编号、标题和标签。"""
        raise NotImplementedError


class AlbumDetail(Protocol):
    """仅使用漫画概要中需要展示的字段。"""

    album_id: str
    title: str
    author: str
    tags: List[str]
    page_count: int
    episode_list: List[Tuple[str, ...]]


class SearchClient(Protocol):
    """可替换为真实 jmcomic 客户端或不联网的测试客户端。"""

    def search_author(self, author: str, page: int = 1) -> SearchPage:
        """按作者搜索漫画。"""
        raise NotImplementedError

    def get_album_detail(self, album_id: str) -> AlbumDetail:
        """读取漫画概要。"""
        raise NotImplementedError


def create_search_client() -> SearchClient:
    """独立客户端不共享机器人 Cookie，也不执行用户下载插件。"""
    return cast(SearchClient, JmOption.default().new_jm_client(impl="api", cache=False))


class JmSearchError(Exception):
    """稳定的中文业务错误，禁止透传可能包含凭据的第三方异常文本。"""

    def __init__(self, code: str, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


class JmSearchService:
    """每次请求使用独立客户端，避免远程搜索串用机器人登录状态。"""

    def __init__(
        self,
        client_factory: Callable[[], SearchClient] = create_search_client,
    ) -> None:
        self.client_factory = client_factory

    def search_author(self, author: str, page: int = 1) -> Dict[str, object]:
        """按作者搜索漫画，作者统一标记为本次查询值。"""
        normalized_author = author.strip()
        if not normalized_author:
            raise JmSearchError("JM_INVALID_AUTHOR", "作者不能为空", 400)
        if page < 1:
            raise JmSearchError("JM_INVALID_PAGE", "页码必须大于等于 1", 400)
        try:
            search_page = self.client_factory().search_author(normalized_author, page)
            results = [
                {
                    "album_id": str(album_id),
                    "title": str(title),
                    "author": normalized_author,
                    "tags": [str(tag) for tag in tags],
                }
                for album_id, title, tags in search_page.iter_id_title_tag()
            ]
            return {
                "results": results,
                "page": page,
                "page_count": int(search_page.page_count),
                "page_size": int(search_page.page_size),
                "total": int(search_page.total),
            }
        except JmSearchError:
            raise
        # 网络和站点接口异常可能包含原始响应，只暴露异常类型。
        except Exception as error:  # pylint: disable=broad-exception-caught
            raise JmSearchError(
                "JM_SEARCH_FAILED",
                f"作者搜索失败（{type(error).__name__}），请检查网络后重试。",
                502,
            ) from None

    def get_album_detail(self, album_id: str) -> Dict[str, object]:
        """读取远程漫画概要，不下载也不写入本地漫画库。"""
        normalized_id = album_id.strip()
        if (
            not normalized_id.isascii()
            or not normalized_id.isdecimal()
            or len(normalized_id) > 32
        ):
            raise JmSearchError(
                "JM_INVALID_ALBUM_ID", "漫画编号必须为数字且不超过 32 位", 400
            )
        try:
            detail = self.client_factory().get_album_detail(normalized_id)
            return {
                "album_id": str(detail.album_id),
                "title": str(detail.title),
                "author": str(detail.author),
                "tags": [str(tag) for tag in detail.tags],
                "page_count": int(detail.page_count),
                "chapter_ids": [str(episode[0]) for episode in detail.episode_list],
            }
        except JmSearchError:
            raise
        except MissingAlbumPhotoException:
            raise JmSearchError(
                "JM_ALBUM_NOT_FOUND", "漫画不存在或已下架", 409
            ) from None
        # 网络和站点接口异常可能包含原始响应，只暴露异常类型。
        except Exception as error:  # pylint: disable=broad-exception-caught
            raise JmSearchError(
                "JM_ALBUM_DETAIL_FAILED",
                f"漫画详情读取失败（{type(error).__name__}），请检查网络后重试。",
                502,
            ) from None
