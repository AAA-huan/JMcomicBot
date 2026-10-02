"""正式化任务、任务事件和审计事件表。"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0019_formalize_task_audit_tables"
down_revision: Union[str, None] = "0018_use_manga_tag_composite_key"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _reject_invalid_rows(connection: sa.Connection) -> None:
    checks = (
        (
            "operation_task",
            "task_type NOT IN ('download', 'scan', 'repair', 'delete', 'backup')",
        ),
        ("operation_task", "source NOT IN ('qq', 'web', 'system')"),
        (
            "operation_task",
            "status NOT IN ('queued', 'running', 'succeeded', 'failed', 'cancelled', 'interrupted')",
        ),
        (
            "operation_task",
            "progress IS NOT NULL AND (progress < 0 OR progress > 100)",
        ),
        ("operation_task", "attempt_count < 0"),
        ("task_event", "progress IS NOT NULL AND (progress < 0 OR progress > 100)"),
        ("audit_event", "source NOT IN ('qq', 'web', 'system')"),
    )
    for table_name, condition in checks:
        count = connection.execute(
            sa.text(f"SELECT COUNT(*) FROM {table_name} WHERE {condition}")
        ).scalar_one()
        if count:
            raise RuntimeError(
                f"表 {table_name} 存在 {count} 条不符合阶段二约束的记录，迁移已停止"
            )


def upgrade() -> None:
    """增加任务和审计字段的数据库级合法性约束。"""
    _reject_invalid_rows(op.get_bind())
    with op.batch_alter_table("operation_task") as batch_op:
        batch_op.create_check_constraint(
            "ck_operation_task_type",
            "task_type IN ('download', 'scan', 'repair', 'delete', 'backup')",
        )
        batch_op.create_check_constraint(
            "ck_operation_task_source", "source IN ('qq', 'web', 'system')"
        )
        batch_op.create_check_constraint(
            "ck_operation_task_status",
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled', 'interrupted')",
        )
        batch_op.create_check_constraint(
            "ck_operation_task_progress",
            "progress IS NULL OR (progress >= 0 AND progress <= 100)",
        )
        batch_op.create_check_constraint(
            "ck_operation_task_attempt_count", "attempt_count >= 0"
        )
    with op.batch_alter_table("task_event") as batch_op:
        batch_op.create_check_constraint(
            "ck_task_event_progress",
            "progress IS NULL OR (progress >= 0 AND progress <= 100)",
        )
    with op.batch_alter_table("audit_event") as batch_op:
        batch_op.create_check_constraint(
            "ck_audit_event_source", "source IN ('qq', 'web', 'system')"
        )
    op.create_index(
        "ix_audit_event_actor_created",
        "audit_event",
        ["actor_user_id", "created_at", "id"],
    )


def downgrade() -> None:
    """移除任务和审计字段的合法性约束。"""
    op.drop_index("ix_audit_event_actor_created", table_name="audit_event")
    with op.batch_alter_table("audit_event") as batch_op:
        batch_op.drop_constraint("ck_audit_event_source", type_="check")
    with op.batch_alter_table("task_event") as batch_op:
        batch_op.drop_constraint("ck_task_event_progress", type_="check")
    with op.batch_alter_table("operation_task") as batch_op:
        for name in (
            "ck_operation_task_attempt_count",
            "ck_operation_task_progress",
            "ck_operation_task_status",
            "ck_operation_task_source",
            "ck_operation_task_type",
        ):
            batch_op.drop_constraint(name, type_="check")
