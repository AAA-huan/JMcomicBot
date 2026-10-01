"""漫画资料修复应用服务测试。"""

from sqlalchemy import text

from src.database.repositories import (
    AuditEventRepository,
    MangaRepository,
    MangaTagRepository,
    OperationTaskRepository,
    TaskEventRepository,
)
from src.service import OperationTaskService, RepairService


def test_repair_marks_orphan_manga_and_deletes_orphan_tags(
    db_manager, tmp_path
) -> None:
    """repair 应标记孤儿漫画缺失并删除孤儿标签，任务记录成功。"""
    manga_repo = MangaRepository(db_manager, download_root=str(tmp_path))
    tag_repo = MangaTagRepository(db_manager)
    task_service = OperationTaskService(
        OperationTaskRepository(db_manager),
        TaskEventRepository(db_manager),
        AuditEventRepository(db_manager),
    )
    repair_service = RepairService(manga_repo, tag_repo, task_service)

    # 磁盘有文件
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

    cleaned = repair_service.repair(str(tmp_path))

    assert cleaned == 2  # 1 个孤儿漫画 + 1 个孤儿标签
    assert manga_repo.get("350260").status == "downloaded"
    assert manga_repo.get("350261").status == "missing_file"
    assert tag_repo.list_all_tags() == []
    tasks = OperationTaskRepository(db_manager).list()
    assert len(tasks) == 1
    assert tasks[0].task_type == "repair"
    assert tasks[0].status == "succeeded"
