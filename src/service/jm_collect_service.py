"""JM 远程漫画收藏入库与本地状态查询，不下载漫画本体。"""

from typing import Callable, Dict, List, Optional

from jmcomic import MissingAlbumPhotoException

from src.database.repositories import (
    FavoriteRepository,
    MangaRepository,
    MangaTagRepository,
)
from src.utils.manga_enrichment import build_remote_metadata

from .jm_search_service import AlbumDetail, SearchClient, create_search_client

# 单次收藏请求的漫画数量上限，与前端选择上限保持一致
COLLECT_REQUEST_LIMIT = 100


class JmCollectError(Exception):
    """稳定的中文业务错误，禁止透传可能包含凭据的第三方异常文本。"""

    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


class JmCollectService:
    """把远程漫画信息以收藏态写入本地库，已存在的漫画不改动元数据。"""

    def __init__(
        self,
        manga_repository: MangaRepository,
        tag_repository: MangaTagRepository,
        favorite_repository: FavoriteRepository,
        client_factory: Callable[[], SearchClient] = create_search_client,
    ) -> None:
        self.manga_repository = manga_repository
        self.tag_repository = tag_repository
        self.favorite_repository = favorite_repository
        self.client_factory = client_factory

    def collect_albums(self, album_ids: List[str], admin_id: int) -> Dict[str, object]:
        """批量收藏远程漫画，逐项返回失败原因而不中断整个批次。"""
        normalized_ids = self._normalize_album_ids(album_ids)
        client: Optional[SearchClient] = None
        collected_count = 0
        already_count = 0
        failed: List[Dict[str, str]] = []
        for album_id in normalized_ids:
            try:
                manga = self.manga_repository.get(album_id)
                if manga is None or manga.status == "deleted":
                    if client is None:
                        client = self.client_factory()
                    detail: AlbumDetail = client.get_album_detail(album_id)
                    # 未下载漫画的本地章节/页数保持 0，真实站点数据写入在线快照
                    self.manga_repository.upsert(
                        album_id,
                        title=detail.name,
                        author=",".join(detail.authors),
                        chapter_count=0,
                        page_count=0,
                        status="favorited",
                    )
                    self.manga_repository.update_scan_metadata(
                        album_id, build_remote_metadata(detail)
                    )
                    for tag in dict.fromkeys(detail.tags):
                        self.tag_repository.add_for_existing_manga(tag, album_id)
                    collected_count += 1
                else:
                    # 已有本地记录时只补收藏，保留下载态与用户编辑过的元数据
                    already_count += 1
                self.favorite_repository.set_favorite(
                    "web_admin", str(admin_id), album_id, True
                )
            except MissingAlbumPhotoException:
                failed.append({"album_id": album_id, "error": "漫画不存在或已下架"})
            # 网络与站点异常可能包含原始响应，只暴露异常类型
            except Exception as error:  # pylint: disable=broad-exception-caught
                failed.append(
                    {
                        "album_id": album_id,
                        "error": f"收藏失败（{type(error).__name__}）",
                    }
                )
        return {
            "collected_count": collected_count,
            "already_count": already_count,
            "failed": failed,
        }

    def local_status(self, album_id: str) -> Dict[str, object]:
        """返回单本漫画的本地存在、状态、收藏与可读下载状态。"""
        return self.local_statuses([album_id])[album_id]

    def local_statuses(self, album_ids: List[str]) -> Dict[str, Dict[str, object]]:
        """批量查询本地状态，供作者搜索结果与详情对话框共用。"""
        unique_ids = list(dict.fromkeys(album_ids))
        downloaded = self.manga_repository.are_downloaded(unique_ids)
        statuses: Dict[str, Dict[str, object]] = {}
        for album_id in unique_ids:
            manga = self.manga_repository.get(album_id)
            statuses[album_id] = {
                "exists": manga is not None,
                "status": manga.status if manga is not None else None,
                "favorited": self.favorite_repository.has_admin_favorite(album_id),
                "downloaded": downloaded.get(album_id, False),
            }
        return statuses

    @staticmethod
    def _normalize_album_ids(album_ids: List[str]) -> List[str]:
        """校验数量与编号格式，并按首次出现顺序去重。"""
        if not album_ids:
            raise JmCollectError("JM_INVALID_ALBUM_IDS", "请至少选择一本漫画")
        if len(album_ids) > COLLECT_REQUEST_LIMIT:
            raise JmCollectError(
                "JM_TOO_MANY_ALBUMS",
                f"单次最多收藏 {COLLECT_REQUEST_LIMIT} 本漫画",
            )
        normalized_ids: List[str] = []
        seen: set[str] = set()
        for raw_album_id in album_ids:
            album_id = raw_album_id.strip()
            if not album_id.isascii() or not album_id.isdecimal() or len(album_id) > 32:
                raise JmCollectError(
                    "JM_INVALID_ALBUM_ID", "漫画编号必须为数字且不超过 32 位"
                )
            if album_id in seen:
                continue
            seen.add(album_id)
            normalized_ids.append(album_id)
        return normalized_ids
