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
    DatabaseMaintenanceService,
    OperationContext,
    OperationTaskService,
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


def test_create_task_and_find_active_download(operation_task_repo, manga_repo) -> None:
    manga_repo.upsert(
        manga_id="123", title="测试漫画", author="", chapter_count=1, page_count=1
    )
    task = operation_task_repo.create(
        task_type="download", source="qq", requested_by="10001", manga_id="123"
    )

    assert task.status == "queued"
    assert task.progress is None
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


def test_database_backup_uses_task_service(
    tmp_path, db_manager, operation_task_service, operation_task_repo
) -> None:
    """正式备份入口应生成可读取备份并完成持久化任务。"""
    service = DatabaseMaintenanceService(db_manager, operation_task_service)
    destination = tmp_path / "backup" / "main.db"

    result = service.create_backup(str(destination))

    assert result == destination
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
