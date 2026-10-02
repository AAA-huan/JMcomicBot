"""漫画列表数值 ID 排序测试。"""

from datetime import datetime, timedelta

from src.database.models import Manga, utc_now


def _add_manga(db_manager, manga_id: str, downloaded_at: datetime) -> None:
    """插入一条带指定下载时间的最小漫画记录。"""
    now = utc_now()
    with db_manager.get_session() as session:
        session.add(
            Manga(
                id=manga_id,
                title=f"漫画{manga_id}",
                author="",
                chapter_count=1,
                page_count=10,
                status="downloaded",
                downloaded_at=downloaded_at,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()


def test_search_sorts_numeric_ids(db_manager, manga_repo) -> None:
    """ID 排序必须按数值比较，短 ID 不应排在长 ID 之后。"""
    same_time = utc_now()
    _add_manga(db_manager, "2556", same_time)
    _add_manga(db_manager, "101051", same_time)
    _add_manga(db_manager, "99999", same_time)

    ascending, _ = manga_repo.search(1, 10, sort="id_asc")
    descending, _ = manga_repo.search(1, 10, sort="id_desc")

    assert [manga.id for manga in ascending] == ["2556", "99999", "101051"]
    assert [manga.id for manga in descending] == ["101051", "99999", "2556"]


def test_search_same_downloaded_at_uses_numeric_id(db_manager, manga_repo) -> None:
    """下载时间相同的记录按数值 ID 稳定排序，字符串序不得打乱顺序。"""
    downloaded_at = utc_now()
    _add_manga(db_manager, "101051", downloaded_at)
    _add_manga(db_manager, "2556", downloaded_at)

    result, _ = manga_repo.search(1, 10, sort="downloaded_at_desc")

    assert [manga.id for manga in result] == ["2556", "101051"]


def test_search_sorts_by_downloaded_at(db_manager, manga_repo) -> None:
    """按下载时间排序应反映 downloaded_at 的先后而不是 ID。"""
    earlier = utc_now() - timedelta(days=1)
    later = utc_now()
    _add_manga(db_manager, "900", later)
    _add_manga(db_manager, "100", earlier)

    descending, _ = manga_repo.search(1, 10, sort="downloaded_at_desc")
    ascending, _ = manga_repo.search(1, 10, sort="downloaded_at_asc")

    assert [manga.id for manga in descending] == ["900", "100"]
    assert [manga.id for manga in ascending] == ["100", "900"]
