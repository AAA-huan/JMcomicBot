"""漫画黑名单仓储测试。"""

from datetime import datetime

import pytest

from src.database.repositories import MangaBlacklistRepository, MangaRepository
from src.database.repositories.manga_blacklist_repository import (
    MangaBlacklistRepository as DirectMangaBlacklistRepository,
)


def _repo(db_manager) -> MangaBlacklistRepository:
    """构造黑名单仓储。"""
    return MangaBlacklistRepository(db_manager)


def test_add_get_and_idempotent(db_manager) -> None:
    """首次写入成功，重复写入不覆盖原记录。"""
    repo = _repo(db_manager)
    assert repo.get("100") is None

    assert repo.add("100", "测试原因", "10001", "qq", "task-1") is True
    assert repo.add("100", "新原因", "10002", "web", "task-2") is False

    record = repo.get("100")
    assert record is not None
    assert record.manga_id == "100"
    assert record.reason == "测试原因"
    assert record.requested_by == "10001"
    assert record.source == "qq"
    assert record.operation_task_id == "task-1"
    assert record.blacklisted_at is not None


def test_exists_and_ids_for_mangas(db_manager) -> None:
    """单点与批量命中检查应只返回真实存在的黑名单 ID。"""
    repo = _repo(db_manager)
    repo.add("100", None, "10001", "qq", None)
    repo.add("101", None, "10001", "qq", None)

    assert repo.exists("100") is True
    assert repo.exists("999") is False
    assert repo.ids_for_mangas([]) == set()
    assert repo.ids_for_mangas(["100", "101", "999"]) == {"100", "101"}


def test_list_orders_by_time_and_numeric_id(db_manager) -> None:
    """按拉黑时间倒序；同一时间按漫画 ID 数值升序，避免字符串排序。"""
    repo = _repo(db_manager)
    repo.add("10", None, None, "system", None, datetime(2026, 1, 1, 0, 0))
    repo.add("2", None, None, "system", None, datetime(2026, 1, 2, 0, 0))
    repo.add("1", None, None, "system", None, datetime(2026, 1, 2, 0, 0))

    assert [record.manga_id for record in repo.list()] == ["1", "2", "10"]
    assert [record.manga_id for record in repo.list(page=2, page_size=2)] == ["10"]


def test_search_joins_optional_manga_title(db_manager, manga_repo) -> None:
    """搜索应同时匹配漫画 ID 与可选标题，并保留无元数据的黑名单记录。"""
    manga_repo.upsert(
        manga_id="100", title="恋爱漫画", author="", chapter_count=1, page_count=1
    )
    repo = _repo(db_manager)
    repo.add("100", None, None, "system", None)
    repo.add("200", None, None, "system", None)

    rows, total = repo.search(1, 20, "恋爱")
    assert total == 1
    assert rows[0][0].manga_id == "100"
    assert rows[0][1] == "恋爱漫画"

    rows, total = repo.search(1, 20, "200")
    assert total == 1
    assert rows[0][0].manga_id == "200"
    assert rows[0][1] is None

    rows, total = repo.search(1, 20, "不存在")
    assert total == 0
    assert rows == []


def test_remove_returns_whether_deleted(db_manager) -> None:
    """删除返回是否真实命中，重复删除幂等。"""
    repo = _repo(db_manager)
    repo.add("100", None, None, "system", None)

    assert repo.remove("100") is True
    assert repo.remove("100") is False
    assert repo.exists("100") is False


def test_count(db_manager) -> None:
    """统计只计算黑名单表记录。"""
    repo = _repo(db_manager)
    assert repo.count() == 0
    repo.add("100", None, None, "system", None)
    repo.add("101", None, None, "system", None)
    assert repo.count() == 2


def test_repository_export_is_same_class() -> None:
    """仓储包导出应与模块公开类保持一致。"""
    assert MangaBlacklistRepository is DirectMangaBlacklistRepository


def test_source_check_constraint_rejects_unknown_value(db_manager) -> None:
    """来源必须受限为 qq/web/system。"""
    repo = _repo(db_manager)
    with pytest.raises(Exception, match="ck_manga_blacklist_source"):
        repo.add("100", None, None, "unknown", None)


def test_blacklisted_at_uses_supplied_value(db_manager) -> None:
    """导入或测试场景可显式指定拉黑时间。"""
    repo = _repo(db_manager)
    moment = datetime(2026, 5, 1, 12, 0)
    repo.add("100", None, None, "system", None, moment)
    record = repo.get("100")
    assert record is not None
    assert record.blacklisted_at == moment


def test_manga_repository_blacklist_only_includes_deleted(
    db_manager, manga_repo
) -> None:
    """黑名单筛选不默认排除 deleted，否则绑定删除后列表会为空。"""
    manga_repo.upsert(
        manga_id="100", title="已删除", author="", chapter_count=1, page_count=1
    )
    manga_repo.mark_manga_deleted("100")
    _repo(db_manager).add("100", None, None, "system", None)

    mangas, total = manga_repo.search(
        page=1,
        page_size=20,
        search=None,
        status=None,
        tag=None,
        sort="id_asc",
        blacklist_only=True,
    )
    assert total == 1
    assert [manga.id for manga in mangas] == ["100"]
