"""阶段二任务、任务事件和审计仓储测试。"""

import json

import pytest
from sqlalchemy import inspect

from src.database.repositories import (
    AuditEventRepository,
    OperationTaskRepository,
    TaskEventRepository,
)
from src.service import (
    BackupResult,
    DatabaseMaintenanceService,
    OperationContext,
    OperationTaskService,
    TaskResult,
)


@pytest.fixture()
def operation_task_repo(db_manager) -> OperationTaskRepository:
    return OperationTaskRepository(db_manager)


@pytest.fixture()
def task_event_repo(db_manager) -> TaskEventRepository:
    return TaskEventRepository(db_manager)


@pytest.fixture()
def audit_event_repo(db_manager) -> AuditEventRepository:
    return AuditEventRepository(db_manager)


@pytest.fixture()
def operation_task_service(
    operation_task_repo, task_event_repo, audit_event_repo
) -> OperationTaskService:
    return OperationTaskService(operation_task_repo, task_event_repo, audit_event_repo)


def test_stage_two_constraints_and_indexes_exist(db_manager) -> None:
    """任务和审计表应具备状态约束及规定索引。"""
    inspector = inspect(db_manager.engine)
    task_checks = {
        item["name"] for item in inspector.get_check_constraints("operation_task")
    }
    event_checks = {
        item["name"] for item in inspector.get_check_constraints("task_event")
    }
    audit_checks = {
        item["name"] for item in inspector.get_check_constraints("audit_event")
    }
    audit_indexes = {item["name"] for item in inspector.get_indexes("audit_event")}
    task_columns = {
        item["name"]: item for item in inspector.get_columns("operation_task")
    }

    assert {
        "ck_operation_task_type",
        "ck_operation_task_source",
        "ck_operation_task_status",
        "ck_operation_task_progress",
        "ck_operation_task_attempt_count",
    } <= task_checks
    assert "ck_task_event_progress" in event_checks
    assert "ck_audit_event_source" in audit_checks
    assert "ix_audit_event_actor_created" in audit_indexes
    assert inspect(db_manager.engine).get_foreign_keys("operation_task") == []
    assert task_columns["summary"]["nullable"] is False


def test_create_task_and_find_active_download(operation_task_repo, manga_repo) -> None:
    manga_repo.upsert(
        manga_id="123", title="测试漫画", author="", chapter_count=1, page_count=1
    )
    task = operation_task_repo.create(
        task_type="download", source="qq", requested_by="10001", manga_id="123"
    )

    assert task.status == "queued"
    assert task.progress is None
    assert task.summary == "下载漫画 123"
    active = operation_task_repo.find_active_download("123")
    assert active is not None
    assert active.id == task.id


def test_invalid_task_type_and_source_are_rejected(operation_task_repo) -> None:
    with pytest.raises(ValueError, match="任务类型"):
        operation_task_repo.create("unknown", "qq")
    with pytest.raises(ValueError, match="任务来源"):
        operation_task_repo.create("scan", "api")


def test_task_event_is_ordered_and_metadata_is_whitelisted(
    operation_task_repo, task_event_repo
) -> None:
    task = operation_task_repo.create("scan", "system")
    first = task_event_repo.append(
        task.id,
        event_type="scan.started",
        stage="scanning",
        metadata={"file_count": 2},
    )
    second = task_event_repo.append(
        task.id,
        event_type="scan.progress",
        stage="scanning",
        progress=50,
        metadata={"file_count": 1, "duration_ms": 20},
    )

    assert [event.id for event in task_event_repo.list(task.id)] == [
        first.id,
        second.id,
    ]
    assert json.loads(second.metadata_json) == {"file_count": 1, "duration_ms": 20}
    with pytest.raises(ValueError, match="未允许字段"):
        task_event_repo.append(
            task.id,
            event_type="scan.failed",
            stage="failed",
            metadata={"traceback": "secret"},
        )


def test_running_tasks_are_interrupted_on_recovery(
    db_manager, operation_task_repo
) -> None:
    task = operation_task_repo.create("backup", "system")
    with db_manager.get_session() as session:
        stored = session.get(type(task), task.id)
        stored.status = "running"
        session.commit()

    assert operation_task_repo.interrupt_running() == 1
    interrupted = operation_task_repo.get(task.id)
    assert interrupted.status == "interrupted"
    assert interrupted.finished_at is not None


def test_audit_event_records_only_whitelisted_metadata(audit_event_repo) -> None:
    event = audit_event_repo.record(
        event_type="download.requested",
        source="qq",
        result="accepted",
        actor_user_id="10001",
        target_type="manga",
        target_id="123",
        metadata={"retry_count": 0},
    )

    assert json.loads(event.metadata_json) == {"retry_count": 0}
    with pytest.raises(ValueError, match="未允许字段"):
        audit_event_repo.record(
            event_type="web.login_failed",
            source="web",
            result="failed",
            metadata={"password": "secret"},
        )


def test_task_service_records_lifecycle_without_existing_manga(
    operation_task_service, operation_task_repo, task_event_repo, audit_event_repo
) -> None:
    """下载请求应能先于漫画资料入库，并完整记录生命周期。"""
    task = operation_task_service.create(
        "download", OperationContext.qq("10001", "20001"), manga_id="404"
    )
    assert isinstance(task, TaskResult)
    assert task.summary == "下载漫画 404"
    operation_task_service.start(task.id, "downloading")
    operation_task_service.succeed(
        task.id,
        metadata={"page_count": 12},
        context=OperationContext.qq("10001", "20001"),
    )

    stored = operation_task_repo.get(task.id)
    assert stored is not None
    assert stored.status == "succeeded"
    assert stored.progress == 100
    assert stored.attempt_count == 1
    assert [event.event_type for event in task_event_repo.list(task.id)] == [
        "download.requested",
        "download.started",
        "download.completed",
    ]
    assert [event.event_type for event in audit_event_repo.list()] == [
        "download.completed",
        "download.requested",
    ]


def test_duplicate_download_request_returns_existing_task(
    operation_task_service, operation_task_repo, task_event_repo, audit_event_repo
) -> None:
    """同一漫画存在活动下载时应返回原任务且不重复记录请求。"""
    context = OperationContext.qq("10001", "20001")

    first = operation_task_service.create("download", context, manga_id="404")
    duplicate = operation_task_service.create("download", context, manga_id="404")

    assert duplicate == first
    assert len(operation_task_repo.list()) == 1
    assert [event.event_type for event in task_event_repo.list(first.id)] == [
        "download.requested"
    ]
    assert [event.event_type for event in audit_event_repo.list()] == [
        "download.requested"
    ]


def test_task_state_machine_rejects_invalid_transitions(
    operation_task_service,
) -> None:
    """排队、运行和终态之间只能按明确状态机推进。"""
    context = OperationContext.qq("10001")
    cancelled = operation_task_service.create("download", context, manga_id="101")
    operation_task_service.cancel(cancelled.id)
    with pytest.raises(ValueError, match="cancelled 转换为 running"):
        operation_task_service.start(cancelled.id, "downloading")

    running = operation_task_service.create("download", context, manga_id="102")
    operation_task_service.start(running.id, "downloading")
    with pytest.raises(ValueError, match="running 转换为 cancelled"):
        operation_task_service.cancel(running.id)

    queued = operation_task_service.create("download", context, manga_id="103")
    with pytest.raises(ValueError, match="queued 转换为 succeeded"):
        operation_task_service.succeed(queued.id)


def test_failed_download_returns_persisted_result(
    operation_task_service, operation_task_repo, task_event_repo
) -> None:
    """下载失败应持久化稳定错误码，并返回渠道无关结果。"""
    context = OperationContext.web("admin", "127.0.0.1")
    task = operation_task_service.create("download", context, manga_id="500")
    operation_task_service.start(task.id, "downloading")

    result = operation_task_service.fail(
        task.id,
        error_code="download_failed",
        error_message="TimeoutError",
        context=context,
    )

    stored = operation_task_repo.get(task.id)
    assert result.status == "failed"
    assert result.error_code == "download_failed"
    assert result.error_message == "TimeoutError"
    assert stored is not None
    assert stored.finished_at is not None
    assert [event.event_type for event in task_event_repo.list(task.id)] == [
        "download.requested",
        "download.started",
        "download.failed",
    ]


def test_database_backup_uses_task_service(
    tmp_path, db_manager, operation_task_service, operation_task_repo
) -> None:
    """正式备份入口应生成可读取备份并完成持久化任务。"""
    service = DatabaseMaintenanceService(db_manager, operation_task_service)
    destination = tmp_path / "backup" / "main.db"

    result = service.create_backup(str(destination))

    assert isinstance(result, BackupResult)
    assert result.path == destination
    assert result.file_count == 1
    assert result.task_id
    assert destination.read_bytes().startswith(b"SQLite format 3\x00")
    tasks = operation_task_repo.list()
    assert tasks[0].task_type == "backup"
    assert tasks[0].status == "succeeded"


def test_web_context_records_source_actor_and_client_ip(
    operation_task_service, operation_task_repo, audit_event_repo
) -> None:
    """Web 调用应通过同一服务记录管理员身份和客户端 IP。"""
    context = OperationContext.web("admin", "203.0.113.10")
    task = operation_task_service.create("backup", context)
    operation_task_service.start(task.id, "backing_up")
    operation_task_service.succeed(task.id, context=context)

    stored = operation_task_repo.get(task.id)
    assert stored is not None
    assert stored.source == "web"
    assert stored.requested_by == "admin"
    audit_events = audit_event_repo.list()
    assert {event.source for event in audit_events} == {"web"}
    assert {event.client_ip for event in audit_events} == {"203.0.113.10"}
    assert all(event.metadata_json is None for event in audit_events)


def test_web_context_requires_client_ip() -> None:
    with pytest.raises(ValueError, match="客户端 IP"):
        OperationContext.web("admin", " ")


def test_audit_event_names_align_to_spec(
    operation_task_service, audit_event_repo
) -> None:
    """任务型审计事件名应严格对齐第 2.11 节领域前缀命名。"""
    expected = {
        "download": ("download.requested", "download.completed", "download.failed"),
        "delete": ("manga.delete_requested", "manga.deleted", "manga.delete_failed"),
        "backup": (
            "database.backup_requested",
            "database.backup_created",
            "database.backup_failed",
        ),
        "scan": (
            "library.scan_requested",
            "library.scan_completed",
            "library.scan_failed",
        ),
        "repair": (
            "library.repair_requested",
            "library.repair_completed",
            "library.repair_failed",
        ),
    }
    context = OperationContext.system()
    for task_type, (_requested, _succeeded, _failed) in expected.items():
        # 成功路径：产生 requested 与 succeeded 审计
        ok_task = operation_task_service.create(task_type, context)
        operation_task_service.start(ok_task.id, "working")
        operation_task_service.succeed(ok_task.id, context=context)
        # 失败路径：产生 requested 与 failed 审计
        bad_task = operation_task_service.create(task_type, context)
        operation_task_service.start(bad_task.id, "working")
        operation_task_service.fail(
            bad_task.id, f"{task_type}_failed", "error", context=context
        )

    event_types = {event.event_type for event in audit_event_repo.list()}
    for requested, succeeded, failed in expected.values():
        assert requested in event_types, f"缺失审计事件: {requested}"
        assert succeeded in event_types, f"缺失审计事件: {succeeded}"
        assert failed in event_types, f"缺失审计事件: {failed}"


def test_scan_task_accepts_full_metadata(
    operation_task_service, task_event_repo
) -> None:
    """扫描任务的 metadata 应支持完整扫描统计字段。"""
    context = OperationContext.system()
    task = operation_task_service.create("scan", context)
    operation_task_service.start(task.id, "scanning")
    operation_task_service.succeed(
        task.id,
        metadata={
            "file_count": 12,
            "new_count": 3,
            "updated_count": 2,
            "cleaned_count": 1,
        },
        context=context,
    )

    events = task_event_repo.list(task.id)
    assert json.loads(events[-1].metadata_json) == {
        "file_count": 12,
        "new_count": 3,
        "updated_count": 2,
        "cleaned_count": 1,
    }
