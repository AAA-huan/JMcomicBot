"""只请求 jmcomic 详情数据，不下载漫画图片。"""

from typing import Any, Dict, List, Optional, TYPE_CHECKING

from src.database.models import utc_now
from src.logging.logger_config import logger

if TYPE_CHECKING:
    from .manga_scanner import MangaScanEntry


def enrich_entries(
    entries: List["MangaScanEntry"],
    option: Optional[Any],
    only_missing: bool,
    check_chapters: bool,
) -> int:
    """补充在线快照，章节检查失败独立报告，不掩盖缺失或请求失败。"""
    import jmcomic  # pylint: disable=import-outside-toplevel

    if option is None:
        # 复用机器人配置；配置缺失或无效直接暴露，不使用默认配置掩盖错误。
        option = jmcomic.create_option_by_file("option.yml")
    client = option.new_jm_client()
    succeeded = 0
    for entry in entries:
        if only_missing and entry.remote_metadata is not None:
            continue
        try:
            album = client.get_album_detail(entry.manga_id)
        except jmcomic.JmcomicException as error:
            entry.enrich_error = str(error)
            logger.warning(f"漫画 {entry.manga_id} 联网补全失败: {error}")
            continue
        chapters: List[Dict[str, Any]] = [
            {"id": chapter[0], "index": int(chapter[1]), "title": chapter[2]}
            for chapter in album.episode_list
        ]
        entry.remote_metadata = {
            "source": "jmcomic",
            "fetched_at": utc_now().isoformat(),
            "title": album.name,
            "authors": album.authors,
            "tags": album.tags,
            "description": album.description,
            "chapter_count": len(album),
            "page_count": album.page_count if album.page_count > 0 else None,
            "pub_date": album.pub_date if album.pub_date not in ("", "0") else None,
            "update_date": (
                album.update_date if album.update_date not in ("", "0") else None
            ),
            "works": album.works,
            "actors": album.actors,
            "chapters": chapters,
        }
        if album.name:
            entry.title = album.name
        entry.author = ",".join(album.authors)
        entry.tags = ",".join(album.tags)
        succeeded += 1
        if not check_chapters:
            continue
        for chapter in chapters:
            try:
                photo = client.get_photo_detail(
                    chapter["id"], fetch_album=False, fetch_scramble_id=False
                )
                chapter["page_count"] = len(photo)
            except jmcomic.JmcomicException as error:
                entry.chapter_errors += 1
                entry.warnings.append(f"章节 {chapter['id']} 查询失败: {error}")
        if entry.chapter_errors == 0:
            total = sum(chapter["page_count"] for chapter in chapters)
            entry.remote_metadata["chapter_page_count"] = total
            if album.page_count > 0 and album.page_count != total:
                entry.warnings.append(
                    f"站点总页数 {album.page_count} 与逐章图片数 {total} 不一致"
                )
    return succeeded
