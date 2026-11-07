"""本地自定义文件夹仓储回归测试。"""

import pytest
from sqlalchemy.exc import IntegrityError

from src.database.repositories import (
    FavoriteRepository,
    FolderRepository,
    MangaRepository,
)


def _add_manga(manga_repo: MangaRepository, manga_id: str) -> None:
    """插入一条最小漫画记录。"""
    manga_repo.upsert(manga_id, f"漫画{manga_id}", "作者", 1, 10)


@pytest.fixture(name="folder_repo")
def folder_repo_fixture(db_manager) -> FolderRepository:
    """基于测试数据库构造文件夹仓储。"""
    return FolderRepository(db_manager)


def test_create_rename_and_list(folder_repo: FolderRepository) -> None:
    """文件夹应支持创建、重命名与按排序稳定列出成员数。"""
    first = folder_repo.create("追更")
    second = folder_repo.create("待补")
    assert first.id != second.id

    renamed = folder_repo.rename(first.id, "长期追更")
    assert renamed is not None and renamed.name == "长期追更"

    folder_repo.set_sort_order(second.id, -1)
    listing = folder_repo.list()
    assert [folder.name for folder, count in listing] == ["待补", "长期追更"]
    assert [count for _, count in listing] == [0, 0]


def test_duplicate_name_rejected_at_database(folder_repo: FolderRepository) -> None:
    """数据库唯一约束应拒绝同名文件夹。"""
    folder_repo.create("重复名")
    with pytest.raises(IntegrityError):
        folder_repo.create("重复名")


def test_add_members_idempotent_and_reverse_lookup(
    folder_repo: FolderRepository, manga_repo: MangaRepository
) -> None:
    """成员加入返回新增数，重复加入不再新增；支持按漫画反查文件夹。"""
    _add_manga(manga_repo, "100")
    _add_manga(manga_repo, "200")
    folder = folder_repo.create("分组甲")

    added = folder_repo.add_members(folder.id, ["100", "200"])
    assert added == 2
    # 直接重复插入由联合主键拒绝，幂等语义由服务层先查 members_in_folder 保证
    with pytest.raises(IntegrityError):
        folder_repo.add_members(folder.id, ["100"])

    assert folder_repo.members_in_folder(folder.id, ["100", "300"]) == {"100"}
    assert sorted(folder_repo.member_ids(folder.id)) == ["100", "200"]
    assert folder_repo.folders_for_manga("100") == [folder.id]
    assert folder_repo.folders_for_manga("300") == []

    removed = folder_repo.remove_members(folder.id, ["100", "300"])
    assert removed == 1
    assert folder_repo.member_ids(folder.id) == ["200"]


def test_same_manga_can_join_multiple_folders(
    folder_repo: FolderRepository, manga_repo: MangaRepository
) -> None:
    """同一漫画允许多对多加入多个文件夹。"""
    _add_manga(manga_repo, "100")
    first = folder_repo.create("文件夹一")
    second = folder_repo.create("文件夹二")
    folder_repo.add_members(first.id, ["100"])
    folder_repo.add_members(second.id, ["100"])
    assert folder_repo.folders_for_manga("100") == [first.id, second.id]


def test_delete_folder_cascades_members_only(
    folder_repo: FolderRepository, manga_repo: MangaRepository
) -> None:
    """删除文件夹只清理成员关系，漫画本体保留。"""
    _add_manga(manga_repo, "100")
    folder = folder_repo.create("将被删除")
    folder_repo.add_members(folder.id, ["100"])

    assert folder_repo.delete(folder.id) is True
    assert folder_repo.get(folder.id) is None
    assert manga_repo.get("100") is not None
    assert folder_repo.folders_for_manga("100") == []
    assert folder_repo.delete(folder.id) is False


def test_manga_deletion_clears_membership(
    folder_repo: FolderRepository, manga_repo: MangaRepository
) -> None:
    """删除漫画记录时外键级联清理文件夹成员关系。"""
    _add_manga(manga_repo, "100")
    folder = folder_repo.create("级联测试")
    folder_repo.add_members(folder.id, ["100"])

    assert manga_repo.delete("100") is True
    assert folder_repo.member_ids(folder.id) == []


def test_mark_deleted_manga_clears_membership(
    folder_repo: FolderRepository, manga_repo: MangaRepository
) -> None:
    """标记删除漫画保留元数据，但文件夹成员关系必须同步清理。"""
    _add_manga(manga_repo, "100")
    folder = folder_repo.create("标记删除测试")
    folder_repo.add_members(folder.id, ["100"])

    assert manga_repo.mark_manga_deleted("100") is True
    assert folder_repo.member_ids(folder.id) == []


def test_existing_ids_skips_deleted_manga(
    folder_repo: FolderRepository, manga_repo: MangaRepository
) -> None:
    """已删除漫画不视为存在，不能加入文件夹。"""
    _add_manga(manga_repo, "100")
    _add_manga(manga_repo, "200")
    manga_repo.mark_manga_deleted("200")
    assert folder_repo.existing_ids(["100", "200", "404"]) == {"100"}


def test_search_by_folder_filter(
    folder_repo: FolderRepository, manga_repo: MangaRepository
) -> None:
    """漫画列表可按文件夹 EXISTS 筛选，且可与收藏维度组合。"""
    for manga_id in ("100", "200", "300"):
        _add_manga(manga_repo, manga_id)
    folder = folder_repo.create("筛选分组")
    folder_repo.add_members(folder.id, ["100", "300"])

    mangas, total = manga_repo.search(1, 10, folder_id=folder.id)
    assert total == 2
    assert sorted(manga.id for manga in mangas) == ["100", "300"]

    # 文件夹与收藏筛选正交：先收藏 100，再组合筛选
    favorites = FavoriteRepository(manga_repo.db_manager)
    favorites.set_favorite("web_admin", "1", "100", True)
    mangas, total = manga_repo.search(1, 10, favorite_owner_id="1", folder_id=folder.id)
    assert total == 1
    assert mangas[0].id == "100"
