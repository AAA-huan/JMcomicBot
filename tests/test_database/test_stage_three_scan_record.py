"""阶段三批次 C：scan_record 仓储与扫描统计写入测试。"""

from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
import pytest

from scan_mangas import record_scan_result
from src.database.models import utc_now
from src.database.repositories import (
    OperationTaskRepository,
    ScanRecordRepository,
)
from src.utils.manga_scanner import DOWNLOAD_PATH_LABEL, ScanResult


@pytest.fixture()
def scan_record_repo(db_manager) -> ScanRecordRepository:
    return ScanRecordRepository(db_manager)


@pytest.fixture()
def task_repo(db_manager) -> OperationTaskRepository:
    return OperationTaskRepository(db_manager)


def test_record_scan_result_persists_statistics(scan_record_repo, task_repo) -> None:
    """扫描统计应完整写入 scan_record，路径标识只含配置名。"""
    task = task_repo.create("scan", "system")
    result = ScanResult(
        scanned_files=12,
        manga_count=4,
        new_count=2,
        updated_count=1,
        pending_cleanup_count=0,
        marked_missing_count=1,
    )

    record = record_scan_result(scan_record_repo, task.id, result)

    assert record.task_id == task.id
    assert record.task_type == "scan"
    assert record.path_label == DOWNLOAD_PATH_LABEL
    assert "/" not in record.path_label
    assert record.file_count == 12
    assert record.new_count == 2
    assert record.updated_count == 1
    assert record.missing_count == 1
    assert record.corrupted_count == 0
    assert record.error_count == 0
    assert [item.id for item in scan_record_repo.list_by_task(task.id)] == [record.id]


def test_create_validates_controlled_values(scan_record_repo, task_repo) -> None:
    """任务类型、路径标识与统计值必须是受控输入。"""
    task = task_repo.create("scan", "system")

    with pytest.raises(ValueError, match="维护任务类型"):
        scan_record_repo.create(task.id, "download", "MANGA_DOWNLOAD_PATH")
    with pytest.raises(ValueError, match="路径标识不能为空"):
        scan_record_repo.create(task.id, "scan", "")
    with pytest.raises(ValueError, match="路径标识不能是路径"):
        scan_record_repo.create(task.id, "scan", "/home/user/downloads")
    with pytest.raises(ValueError, match="路径标识不能是路径"):
        scan_record_repo.create(task.id, "scan", "sub/dir")
    with pytest.raises(ValueError, match="不能为负数"):
        scan_record_repo.create(task.id, "scan", "MANGA_DOWNLOAD_PATH", file_count=-1)

    with pytest.raises(IntegrityError):
        scan_record_repo.create("missing-task", "scan", "MANGA_DOWNLOAD_PATH")


def test_list_orders_filters_and_paginates(scan_record_repo, task_repo) -> None:
    """维护记录列表应按时间倒序、支持类型过滤与分页。"""
    now = utc_now()
    scan_task = task_repo.create("scan", "system")
    repair_task = task_repo.create("repair", "system")

    oldest = scan_record_repo.create(
        scan_task.id,
        "scan",
        "MANGA_DOWNLOAD_PATH",
        file_count=1,
        created_at=now - timedelta(hours=2),
    )
    repair_record = scan_record_repo.create(
        repair_task.id,
        "repair",
        "MANGA_DOWNLOAD_PATH",
        repaired_count=2,
        created_at=now - timedelta(hours=1),
    )
    newest = scan_record_repo.create(
        scan_task.id,
        "scan",
        "MANGA_DOWNLOAD_PATH",
        file_count=3,
        created_at=now,
    )

    records = scan_record_repo.list()
    assert [item.id for item in records] == [newest.id, repair_record.id, oldest.id]
    assert [item.id for item in scan_record_repo.list(task_type="repair")] == [
        repair_record.id
    ]
    assert [item.id for item in scan_record_repo.list(page=2, page_size=2)] == [
        oldest.id
    ]
    assert [item.id for item in scan_record_repo.list_by_task(scan_task.id)] == [
        oldest.id,
        newest.id,
    ]

    with pytest.raises(ValueError, match="维护任务类型"):
        scan_record_repo.list(task_type="download")


def test_maintenance_list_uses_created_index(db_manager) -> None:
    """维护记录列表查询应命中 created_at 索引。"""
    with db_manager.get_session() as session:
        plan = session.execute(
            text(
                "EXPLAIN QUERY PLAN SELECT id FROM scan_record "
                "ORDER BY created_at DESC, id LIMIT 20"
            )
        ).all()

    details = " ".join(str(row[-1]) for row in plan)
    assert "ix_scan_record_created" in details
