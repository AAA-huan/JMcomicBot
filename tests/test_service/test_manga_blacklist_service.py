"""漫画黑名单应用服务测试。"""

from pathlib import Path

import pytest

from src.database.repositories import (
    AuditEventRepository,
    MangaBlacklistRepository,
    MangaRepository,
    MangaTagRepository,
    OperationTaskRepository,
    TaskEventRepository,
)
from src.service import MangaBlacklistService, MangaService, OperationTaskService
from src.service.operation_context import OperationContext


class _Services:
    """测试所需服务与仓储集合。"""

    def __init__(self, db_manager, root: Path, delete_binding: bool = False) -> None:
        self.manga_repo = MangaRepository(db_manager, download_root=str(root))
        self.blacklist_repo = MangaBlacklistRepository(db_manager)
        self.audit_repo = AuditEventRepository(db_manager)
        self.task_repo = OperationTaskRepository(db_manager)
        self.task_service = OperationTaskService(
            self.task_repo,
            TaskEventRepository(db_manager),
            self.audit_repo,
        )
        self.blacklist_service = MangaBlacklistService(
            blacklist_repository=self.blacklist_repo,
            manga_repository=self.manga_repo,
            audit_repository=self.audit_repo,
            task_service=self.task_service,
            manga_service_provider=lambda: self.manga_service,
            delete_binding=delete_binding,
        )
        self.manga_service = MangaService(
            manga_repository=self.manga_repo,
            tag_repository=MangaTagRepository(db_manager),
            audit_repository=self.audit_repo,
            operation_task_service=self.task_service,
            download_root=str(root),
            download_conflict_checker=lambda _manga_id: False,
            send_conflict_checker=lambda _manga_id: False,
            blacklist_service=self.blacklist_service,
            blacklist_delete_binding=delete_binding,
        )

    def audit_types(self) -> set[str]:
        """返回全部审计事件类型。"""
        return {event.event_type for event in self.audit_repo.list(page_size=100)}


@pytest.fixture()
def services(db_manager, tmp_path) -> _Services:
    """构造默认模式下的完整服务集合。"""
    return _Services(db_manager, tmp_path)


@pytest.fixture()
def bound_services(db_manager, tmp_path) -> _Services:
    """构造绑定模式下的完整服务集合。"""
    return _Services(db_manager, tmp_path, delete_binding=True)


def _add_downloaded_manga(services: _Services, manga_id: str = "100") -> Path:
    """写入漫画元数据、PDF 文件与文件记录。"""
    pdf_path = Path(services.manga_repo.download_root) / f"{manga_id}-标题.pdf"
    pdf_path.write_bytes(b"%PDF")
    services.manga_repo.upsert(
        manga_id=manga_id,
        title="标题",
        author="作者",
        chapter_count=1,
        page_count=1,
    )
    services.manga_repo.add_file(manga_id, str(pdf_path), page_count=1)
    return pdf_path


def test_add_writes_blacklist_task_and_audit(services: _Services) -> None:
    """拉黑应写表、创建 blacklist 任务并记录请求与完成审计。"""
    outcome = services.blacklist_service.add(
        "100", "违规内容", OperationContext.qq("10001", "20001")
    )

    assert outcome.changed is True
    assert outcome.status == "blacklisted"
    assert outcome.deleted is False
    assert services.blacklist_repo.exists("100")
    record = services.blacklist_repo.get("100")
    assert record is not None
    assert record.reason == "违规内容"
    assert record.requested_by == "10001"
    assert record.source == "qq"

    assert outcome.task_id is not None
    task = services.task_repo.get(outcome.task_id)
    assert task is not None
    assert task.task_type == "blacklist"
    assert task.status == "succeeded"
    assert task.stage == "done"
    assert task.summary == "漫画黑名单 100"
    assert task.requested_by == "10001"

    audit_types = services.audit_types()
    assert "manga.blacklist_requested" in audit_types
    assert "manga.blacklisted" in audit_types
    event_types = [event.event_type for event in task.events]
    assert event_types == [
        "blacklist.requested",
        "blacklist.started",
        "blacklist.completed",
    ]


def test_add_is_idempotent(services: _Services) -> None:
    """已拉黑时重复拉黑不再创建任务或写审计。"""
    first = services.blacklist_service.add("100", context=OperationContext.qq("1"))
    second = services.blacklist_service.add("100", context=OperationContext.qq("2"))

    assert first.changed is True
    assert second.changed is False
    assert second.status == "already_blacklisted"
    assert second.task_id is None
    assert len(services.task_repo.list()) == 1


def test_remove_writes_unblacklisted_audit(services: _Services) -> None:
    """解除拉黑应删除记录，并以独立审计事件完成任务。"""
    services.blacklist_service.add("100", context=OperationContext.qq("1"))
    outcome = services.blacklist_service.remove(
        "100", OperationContext.web("1", "127.0.0.1")
    )

    assert outcome.changed is True
    assert outcome.status == "unblacklisted"
    assert services.blacklist_repo.exists("100") is False
    assert outcome.task_id is not None
    task = services.task_repo.get(outcome.task_id)
    assert task is not None
    assert task.task_type == "blacklist"
    assert task.stage == "done"
    assert "manga.unblacklisted" in services.audit_types()
    events = services.audit_repo.list(page_size=100)
    unblacklist_events = [
        event for event in events if event.event_type == "manga.unblacklisted"
    ]
    assert len(unblacklist_events) == 1


def test_remove_missing_is_idempotent(services: _Services) -> None:
    """解除未拉黑漫画不创建任务。"""
    outcome = services.blacklist_service.remove("100")

    assert outcome.changed is False
    assert outcome.status == "not_blacklisted"
    assert outcome.task_id is None
    assert services.task_repo.list() == []


def test_batch_deduplicates_and_keeps_order(services: _Services) -> None:
    """批量操作应校验、去重并按首次出现顺序执行。"""
    result = services.blacklist_service.add_batch(
        ["100", "101", "100"], "原因", OperationContext.qq("1")
    )

    assert [item.manga_id for item in result.outcomes] == ["100", "101"]
    assert result.changed_count == 2
    assert result.unchanged_count == 0
    assert services.blacklist_repo.ids_for_mangas(["100", "101"]) == {"100", "101"}

    repeated = services.blacklist_service.add_batch(
        ["100"], context=OperationContext.qq("1")
    )
    assert repeated.changed_count == 0
    assert repeated.unchanged_count == 1

    removed = services.blacklist_service.remove_batch(
        ["101", "100", "101"], OperationContext.qq("1")
    )
    assert [item.manga_id for item in removed.outcomes] == ["101", "100"]
    assert removed.changed_count == 2


def test_validation_rejects_bad_ids_and_reason(services: _Services) -> None:
    """ID 必须为数字，批量上限 100，原因不能超长。"""
    with pytest.raises(ValueError, match="不能为空"):
        services.blacklist_service.add(" ")
    with pytest.raises(ValueError, match="必须是数字"):
        services.blacklist_service.add("abc")
    with pytest.raises(ValueError, match="不能超过 32 位"):
        services.blacklist_service.add("1" * 33)
    with pytest.raises(ValueError, match="至少提供一个"):
        services.blacklist_service.add_batch([])
    with pytest.raises(ValueError, match="最多操作 100"):
        services.blacklist_service.add_batch([str(index) for index in range(101)])
    with pytest.raises(ValueError, match="原因长度"):
        services.blacklist_service.add("100", "a" * 256)


def test_list_blacklisted_returns_optional_title(services: _Services) -> None:
    """列表通过 LEFT JOIN 补充标题，并支持搜索与分页。"""
    services.manga_repo.upsert(
        manga_id="100", title="有元数据", author="", chapter_count=1, page_count=1
    )
    services.blacklist_service.add("100")
    services.blacklist_service.add("200")

    page = services.blacklist_service.list_blacklisted(1, 20)
    assert page.total == 2
    by_id = {item.manga_id: item for item in page.items}
    assert by_id["100"].title == "有元数据"
    assert by_id["200"].title is None

    searched = services.blacklist_service.list_blacklisted(1, 20, "元数据")
    assert searched.total == 1
    assert searched.items[0].manga_id == "100"


def test_default_mode_does_not_delete_manga(services: _Services) -> None:
    """默认关闭绑定时拉黑只写表，不动漫画、PDF 与状态。"""
    pdf_path = _add_downloaded_manga(services)
    outcome = services.blacklist_service.add("100")

    assert outcome.deleted is False
    assert pdf_path.exists()
    manga = services.manga_repo.get("100")
    assert manga is not None
    assert manga.status == "downloaded"


def test_binding_add_deletes_manga_and_pdf(bound_services: _Services) -> None:
    """绑定模式下拉黑会同步删除漫画文件并标记 deleted。"""
    pdf_path = _add_downloaded_manga(bound_services)
    outcome = bound_services.blacklist_service.add("100")

    assert outcome.deleted is True
    assert outcome.delete_error_code is None
    assert pdf_path.exists() is False
    manga = bound_services.manga_repo.get("100", include_deleted=True)
    assert manga is not None
    assert manga.status == "deleted"
    audit_types = bound_services.audit_types()
    assert "manga.blacklisted" in audit_types
    assert "manga.deleted" in audit_types


def test_binding_add_missing_manga_skips_delete(bound_services: _Services) -> None:
    """绑定模式下未下载漫画只写黑名单，并审计删除跳过原因。"""
    outcome = bound_services.blacklist_service.add("999")

    assert outcome.changed is True
    assert outcome.deleted is False
    assert outcome.delete_error_code == "manga_not_found"
    assert bound_services.blacklist_repo.exists("999")
    events = bound_services.audit_repo.list(page_size=100)
    skipped = [event for event in events if event.event_type == "manga.delete_skipped"]
    assert len(skipped) == 1
    assert skipped[0].metadata_json is not None
    assert '"reason":"manga_not_found"' in skipped[0].metadata_json


def test_binding_delete_writes_blacklist(bound_services: _Services) -> None:
    """绑定模式下删除漫画会写入黑名单，且解除拉黑不会恢复漫画。"""
    pdf_path = _add_downloaded_manga(bound_services)
    result = bound_services.manga_service.delete(["100"], OperationContext.qq("1"))

    assert result.all_succeeded is True
    assert pdf_path.exists() is False
    assert bound_services.blacklist_repo.exists("100")
    record = bound_services.blacklist_repo.get("100")
    assert record is not None
    assert record.reason == "删除漫画时自动加入黑名单"

    removed = bound_services.blacklist_service.remove("100")
    assert removed.changed is True
    manga = bound_services.manga_repo.get("100", include_deleted=True)
    assert manga is not None
    assert manga.status == "deleted"
    assert pdf_path.exists() is False
