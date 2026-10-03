"""漫画应用服务（删除与元数据修改）测试。"""

from typing import List, Set

import pytest

from src.database.repositories import (
    AuditEventRepository,
    FavoriteRepository,
    MangaRepository,
    MangaTagRepository,
    OperationTaskRepository,
    ReadingProgressRepository,
    TaskEventRepository,
)
from src.service import MangaService, OperationContext, OperationTaskService


def _build_task_service(db_manager) -> OperationTaskService:
    """构造真实的持久化操作任务服务。"""
    return OperationTaskService(
        OperationTaskRepository(db_manager),
        TaskEventRepository(db_manager),
        AuditEventRepository(db_manager),
    )


def _build_service(
    tmp_path,
    db_manager,
    manga_repo: MangaRepository,
    tag_repo: MangaTagRepository,
    download_conflicts: Set[str] | None = None,
    send_conflicts: Set[str] | None = None,
) -> MangaService:
    """构造使用真实仓储与可配置冲突检查器的漫画服务。"""
    download_conflict_ids = download_conflicts or set()
    send_conflict_ids = send_conflicts or set()
    return MangaService(
        manga_repository=manga_repo,
        tag_repository=tag_repo,
        audit_repository=AuditEventRepository(db_manager),
        operation_task_service=_build_task_service(db_manager),
        download_root=str(tmp_path),
        download_conflict_checker=lambda manga_id: manga_id in download_conflict_ids,
        send_conflict_checker=lambda manga_id: manga_id in send_conflict_ids,
    )


def _add_manga(
    manga_repo: MangaRepository, tmp_path, manga_id: str, with_file: bool = True
) -> None:
    """写入漫画记录、可选 PDF 文件与标签。"""
    manga_repo.upsert(
        manga_id=manga_id,
        title=f"标题{manga_id}",
        author="作者",
        chapter_count=1,
        page_count=10,
    )
    if with_file:
        pdf_path = tmp_path / f"{manga_id}-标题(1章).pdf"
        pdf_path.write_bytes(b"%PDF")
        manga_repo.add_file(manga_id, str(pdf_path))


def _audit_event_types(db_manager) -> List[str]:
    return [event.event_type for event in AuditEventRepository(db_manager).list()]


def test_delete_single_cleans_records_and_writes_audit(
    tmp_path, db_manager, manga_repo: MangaRepository, tag_repo: MangaTagRepository
) -> None:
    """单个删除应清理磁盘、漫画、标签并写任务与审计。"""
    _add_manga(manga_repo, tmp_path, "100")
    tag_repo.add("纯爱", "100")
    service = _build_service(tmp_path, db_manager, manga_repo, tag_repo)

    result = service.delete(["100"], OperationContext.qq("10001"))

    outcome = result.outcomes[0]
    assert outcome.succeeded is True
    assert outcome.deleted_file_count == 1
    assert result.all_succeeded is True
    assert manga_repo.get("100") is None
    assert tag_repo.get_by_tag("纯爱") == []
    assert list(tmp_path.glob("*.pdf")) == []

    tasks = OperationTaskRepository(db_manager).list()
    assert len(tasks) == 1
    assert tasks[0].status == "succeeded"
    assert tasks[0].manga_id == "100"
    event_types = [
        event.event_type for event in TaskEventRepository(db_manager).list(tasks[0].id)
    ]
    assert event_types == ["delete.requested", "delete.started", "delete.completed"]
    audit_types = _audit_event_types(db_manager)
    assert "manga.delete_requested" in audit_types
    assert "manga.deleted" in audit_types


def test_delete_batch_partial_failure_marks_task_failed(
    tmp_path, db_manager, manga_repo: MangaRepository, tag_repo: MangaTagRepository
) -> None:
    """批量删除部分失败时任务失败，成功者清理、失败者保留。"""
    _add_manga(manga_repo, tmp_path, "100")
    _add_manga(manga_repo, tmp_path, "200")
    service = _build_service(
        tmp_path,
        db_manager,
        manga_repo,
        tag_repo,
        download_conflicts={"200"},
    )

    result = service.delete(["100", "200"], OperationContext.qq("10001"))

    assert result.succeeded_count == 1
    assert result.failed_count == 1
    assert result.outcomes[1].error_code == "download_conflict"
    assert manga_repo.get("100") is None
    assert manga_repo.get("200") is not None
    assert (tmp_path / "200-标题(1章).pdf").exists() is True

    task = OperationTaskRepository(db_manager).list()[0]
    assert task.status == "failed"
    assert task.error_code == "batch_delete_partial_failure"
    assert "manga.delete_failed" in _audit_event_types(db_manager)


def test_delete_send_conflict_preserves_records(
    tmp_path, db_manager, manga_repo: MangaRepository, tag_repo: MangaTagRepository
) -> None:
    """文件发送中的漫画应返回冲突并保留文件与记录。"""
    _add_manga(manga_repo, tmp_path, "100")
    service = _build_service(
        tmp_path, db_manager, manga_repo, tag_repo, send_conflicts={"100"}
    )

    result = service.delete(["100"], OperationContext.qq("10001"))

    assert result.outcomes[0].error_code == "send_conflict"
    assert manga_repo.get("100") is not None
    assert (tmp_path / "100-标题(1章).pdf").exists() is True
    task = OperationTaskRepository(db_manager).list()[0]
    assert task.error_code == "send_conflict"


def test_delete_missing_pdf_cleans_database_record(
    tmp_path, db_manager, manga_repo: MangaRepository, tag_repo: MangaTagRepository
) -> None:
    """磁盘没有 PDF 时仍可清理已登记漫画，不删除其他文件。"""
    manga_repo.upsert(
        manga_id="100", title="标题", author="作者", chapter_count=1, page_count=10
    )
    service = _build_service(tmp_path, db_manager, manga_repo, tag_repo)

    result = service.delete(["100"], OperationContext.qq("10001"))

    assert result.outcomes[0].succeeded is True
    assert result.outcomes[0].deleted_file_count == 0
    assert manga_repo.get("100") is None
    task = OperationTaskRepository(db_manager).list()[0]
    assert task.status == "succeeded"
    assert task.error_code is None


@pytest.mark.parametrize("relative_path", ["renamed.pdf", "nested/renamed.pdf"])
def test_delete_uses_registered_path_only(
    relative_path, tmp_path, db_manager, manga_repo, tag_repo
) -> None:
    """改名和子目录文件按登记路径删除，同前缀未登记文件必须保留。"""
    _add_manga(manga_repo, tmp_path, "100", with_file=False)
    registered = tmp_path / relative_path
    registered.parent.mkdir(parents=True, exist_ok=True)
    registered.write_bytes(b"%PDF")
    manga_repo.add_file("100", str(registered))
    unrelated = tmp_path / "100-unregistered.pdf"
    unrelated.write_bytes(b"%PDF unrelated")

    result = _build_service(tmp_path, db_manager, manga_repo, tag_repo).delete(["100"])

    assert result.all_succeeded
    assert result.deleted_file_count == 1
    assert not registered.exists()
    assert unrelated.exists()


def test_delete_missing_registered_file_cleans_progress(
    tmp_path, db_manager, manga_repo, tag_repo
) -> None:
    """文件丢失后删除应级联清理记录与阅读进度。"""
    _add_manga(manga_repo, tmp_path, "100")
    file = manga_repo.list_files("100")[0]
    progress = ReadingProgressRepository(db_manager)
    progress.upsert(file.id, 1, 10, 0.1)
    (tmp_path / file.relative_path).unlink()

    result = _build_service(tmp_path, db_manager, manga_repo, tag_repo).delete(["100"])

    assert result.all_succeeded
    assert result.deleted_file_count == 0
    assert progress.get(file.id) is None


def test_delete_rejects_symlink_escape_before_marking_deleting(
    tmp_path, db_manager, manga_repo, tag_repo
) -> None:
    """登记后被替换为越界符号链接时，保留记录和目标且明确失败。"""
    _add_manga(manga_repo, tmp_path, "100")
    registered = tmp_path / "100-标题(1章).pdf"
    outside = tmp_path.parent / f"{tmp_path.name}-outside.pdf"
    outside.write_bytes(b"%PDF outside")
    registered.unlink()
    registered.symlink_to(outside)

    result = _build_service(tmp_path, db_manager, manga_repo, tag_repo).delete(["100"])

    assert not result.all_succeeded
    assert result.outcomes[0].error_code == "delete_failed"
    assert outside.read_bytes() == b"%PDF outside"
    assert registered.is_symlink()
    assert manga_repo.list_files("100")[0].status == "ready"


def test_delete_missing_directory_reports_directory_missing(
    tmp_path, db_manager, manga_repo: MangaRepository, tag_repo: MangaTagRepository
) -> None:
    """下载目录缺失时应报告 delete_directory_missing。"""
    missing_root = tmp_path / "missing"
    service = MangaService(
        manga_repository=manga_repo,
        tag_repository=tag_repo,
        audit_repository=AuditEventRepository(db_manager),
        operation_task_service=_build_task_service(db_manager),
        download_root=str(missing_root),
        download_conflict_checker=lambda _manga_id: False,
        send_conflict_checker=lambda _manga_id: False,
    )

    result = service.delete(["100"], OperationContext.qq("10001"))

    assert result.outcomes[0].error_code == "delete_directory_missing"
    assert OperationTaskRepository(db_manager).list()[0].error_code == (
        "delete_directory_missing"
    )


def test_patch_metadata_updates_fields_tags_and_audit(
    tmp_path, db_manager, manga_repo: MangaRepository, tag_repo: MangaTagRepository
) -> None:
    """元数据修改应更新标题/作者/标签并写 manga.metadata_updated 审计。"""
    _add_manga(manga_repo, tmp_path, "100")
    tag_repo.add("旧标签", "100")
    service = _build_service(tmp_path, db_manager, manga_repo, tag_repo)

    updated = service.patch_metadata(
        "100",
        {"title": "新标题", "author": "新作者", "tags": ["冒险", "日常", "冒险"]},
        OperationContext.web("1", "127.0.0.1"),
    )

    assert updated is True
    manga = manga_repo.get("100")
    assert manga is not None
    assert manga.title == "新标题"
    assert manga.author == "新作者"
    assert tag_repo.list_for_manga("100") == ["冒险", "日常"]

    audit_events = AuditEventRepository(db_manager).list()
    updated_events = [
        event for event in audit_events if event.event_type == "manga.metadata_updated"
    ]
    assert len(updated_events) == 1
    assert updated_events[0].source == "web"
    assert updated_events[0].client_ip == "127.0.0.1"


def test_patch_metadata_rejects_unknown_field_and_invalid_types(
    tmp_path, db_manager, manga_repo: MangaRepository, tag_repo: MangaTagRepository
) -> None:
    """白名单外字段与非法类型都应明确报错。"""
    _add_manga(manga_repo, tmp_path, "100")
    service = _build_service(tmp_path, db_manager, manga_repo, tag_repo)

    with pytest.raises(ValueError, match="不允许修改的字段"):
        service.patch_metadata("100", {"status": "deleted"})

    with pytest.raises(ValueError, match="字符串列表"):
        service.patch_metadata("100", {"tags": "纯爱"})


def test_patch_metadata_returns_false_for_missing_manga(
    tmp_path, db_manager, manga_repo: MangaRepository, tag_repo: MangaTagRepository
) -> None:
    """漫画不存在时返回 False，不写审计也不写标签。"""
    service = _build_service(tmp_path, db_manager, manga_repo, tag_repo)

    updated = service.patch_metadata("999", {"title": "新标题"})

    assert updated is False
    assert _audit_event_types(db_manager) == []


@pytest.mark.parametrize(
    "context",
    [
        OperationContext.web("1", "127.0.0.1"),
        OperationContext.qq("12345"),
        OperationContext.qq("99999"),
    ],
)
def test_admin_favorite_blocks_delete_for_every_actor(
    tmp_path, db_manager, manga_repo, tag_repo, context
):
    """管理员本人和普通 QQ 删除都不能越过收藏保护，任何数据均保留。"""
    _add_manga(manga_repo, tmp_path, "100")
    file = manga_repo.get("100").files[0]
    ReadingProgressRepository(db_manager).upsert(file.id, 3, 10, 0.3)
    favorites = FavoriteRepository(db_manager)
    favorites.set_favorite("web_admin", "1", "100", True)
    favorites.set_favorite("qq", "99999", "100", True)
    favorites.set_favorite("qq", "99999", "100", False)
    service = _build_service(tmp_path, db_manager, manga_repo, tag_repo)
    result = service.delete(["100"], context)
    assert result.outcomes[0].error_code == "admin_favorite"
    assert result.deleted_file_count == 0
    assert manga_repo.get("100").files[0].status == "ready"
    assert (tmp_path / file.relative_path).exists()
    assert favorites.get("web_admin", "1", "100") is not None
    assert ReadingProgressRepository(db_manager).get(file.id).page_number == 3
    task = OperationTaskRepository(db_manager).get(result.task_id)
    assert task.status == "failed" and task.error_code == "admin_favorite"
    assert "不能删除" in task.error_message
    favorites.set_favorite("web_admin", "1", "100", False)
    assert service.delete(["100"], context).all_succeeded


def test_batch_delete_skips_admin_favorites_but_deletes_qq_favorites(
    tmp_path, db_manager, manga_repo, tag_repo
):
    """批量删除逐项保护管理员收藏，普通用户收藏不限制删除。"""
    for manga_id in ["100", "200"]:
        _add_manga(manga_repo, tmp_path, manga_id)
    favorites = FavoriteRepository(db_manager)
    favorites.set_favorite("web_admin", "1", "100", True)
    favorites.set_favorite("qq", "12345", "200", True)
    service = _build_service(tmp_path, db_manager, manga_repo, tag_repo)
    result = service.delete(["100", "200"], OperationContext.qq("12345"))
    assert result.failed_count == result.succeeded_count == 1
    assert result.outcomes[0].error_code == "admin_favorite"
    assert manga_repo.get("100") is not None
    assert manga_repo.get("200") is None
    assert favorites.get("web_admin", "1", "100") is not None
    assert favorites.get("qq", "12345", "200") is None


def test_admin_favorite_checked_before_conflicts_or_disk(
    tmp_path, db_manager, manga_repo, tag_repo
):
    """无下载目录且漫画正在下载时，也先提示收藏保护并不调用冲突检查器。"""
    _add_manga(manga_repo, tmp_path, "100", with_file=False)
    FavoriteRepository(db_manager).set_favorite("web_admin", "1", "100", True)
    service = _build_service(tmp_path, db_manager, manga_repo, tag_repo)
    service.download_root = str(tmp_path / "absent")

    def unexpected(_manga_id):
        raise AssertionError("收藏保护应先于其他检查")

    service.download_conflict_checker = unexpected
    service.send_conflict_checker = unexpected
    assert service.delete(["100"]).outcomes[0].error_code == "admin_favorite"
