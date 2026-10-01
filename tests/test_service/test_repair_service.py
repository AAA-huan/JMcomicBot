"""漫画资料修复应用服务测试。"""

from sqlalchemy import text

from src.database.repositories import (
    AuditEventRepository,
    MangaRepository,
    MangaTagRepository,
    OperationTaskRepository,
    ScanRecordRepository,
    TaskEventRepository,
)
from src.service import OperationTaskService, RepairService
from src.utils.manga_scanner import DOWNLOAD_PATH_LABEL


def _build_repair_service(
    db_manager, download_path: str
) -> tuple[RepairService, MangaRepository, MangaTagRepository, ScanRecordRepository]:
    """构造修复服务及其仓储依赖。"""
    manga_repo = MangaRepository(db_manager, download_root=download_path)
    tag_repo = MangaTagRepository(db_manager)
    scan_record_repo = ScanRecordRepository(db_manager)
    task_service = OperationTaskService(
        OperationTaskRepository(db_manager),
        TaskEventRepository(db_manager),
        AuditEventRepository(db_manager),
    )
    return (
        RepairService(
            manga_repo,
            tag_repo,
            scan_record_repo,
            task_service,
            download_root=download_path,
        ),
        manga_repo,
        tag_repo,
        scan_record_repo,
    )


def _prepare_orphans(
    db_manager, manga_repo: MangaRepository, tag_repo, tmp_path
) -> None:
    """预置「磁盘有文件 + 孤儿漫画 + 孤儿标签」测试数据。"""
    disk_pdf = tmp_path / "350260-标题(1章).pdf"
    disk_pdf.write_bytes(b"%PDF")
    manga_repo.upsert("350260", "标题", "", 1, 1)
    manga_repo.add_file("350260", str(disk_pdf))
    # 磁盘无文件（孤儿漫画）
    manga_repo.upsert("350261", "标题2", "", 1, 1)
    # 孤儿标签：先关联再清空关系，使标签失去关联
    tag_repo.add("纯爱", "350260")
    with db_manager.get_session() as session:
        session.execute(text("DELETE FROM manga_tag"))
        session.commit()


def test_repair_marks_orphan_manga_and_deletes_orphan_tags(
    db_manager, tmp_path
) -> None:
    """repair 应标记孤儿漫画缺失并删除孤儿标签，任务与统计记录成功。"""
    repair_service, manga_repo, tag_repo, scan_record_repo = _build_repair_service(
        db_manager, str(tmp_path)
    )
    _prepare_orphans(db_manager, manga_repo, tag_repo, tmp_path)

    cleaned = repair_service.repair()

    assert cleaned == 2  # 1 个孤儿漫画 + 1 个孤儿标签
    assert manga_repo.get("350260").status == "downloaded"
    assert manga_repo.get("350261").status == "missing_file"
    assert tag_repo.list_all_tags() == []
    tasks = OperationTaskRepository(db_manager).list()
    assert len(tasks) == 1
    assert tasks[0].task_type == "repair"
    assert tasks[0].status == "succeeded"

    records = scan_record_repo.list()
    assert len(records) == 1
    assert records[0].task_id == tasks[0].id
    assert records[0].task_type == "repair"
    assert records[0].path_label == DOWNLOAD_PATH_LABEL
    assert records[0].missing_count == 1
    assert records[0].repaired_count == 2


def test_preview_reports_diff_without_writes(db_manager, tmp_path) -> None:
    """preview 应返回孤儿差异清单，且不修改数据、不创建任务。"""
    repair_service, manga_repo, tag_repo, scan_record_repo = _build_repair_service(
        db_manager, str(tmp_path)
    )
    _prepare_orphans(db_manager, manga_repo, tag_repo, tmp_path)

    diff = repair_service.preview()

    assert diff.orphan_manga_ids == ("350261",)
    assert diff.orphan_tag_names == ("纯爱",)
    assert manga_repo.get("350261").status == "downloaded"
    assert tag_repo.list_all_tags() == ["纯爱"]
    assert OperationTaskRepository(db_manager).list() == []
    assert scan_record_repo.list() == []
