"""增加任务、审计和维护相关表。"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002_management_tables"
down_revision: Union[str, None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建阶段 0 所需的独立管理表。"""
    op.create_table(
        "tag",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("normalized_name", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("normalized_name", name="uq_tag_normalized_name"),
    )
    op.create_table(
        "operation_task",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("task_type", sa.String(32), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("stage", sa.String(64), nullable=False, server_default="queued"),
        sa.Column("progress", sa.Integer()),
        sa.Column("manga_id", sa.String(32)),
        sa.Column("requested_by", sa.String(64), nullable=False, server_default=""),
        sa.Column("error_code", sa.String(64)),
        sa.Column("error_message", sa.Text()),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime()),
        sa.ForeignKeyConstraint(["manga_id"], ["manga.id"]),
    )
    op.create_table(
        "task_event",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("task_id", sa.String(36), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("stage", sa.String(64), nullable=False),
        sa.Column("progress", sa.Integer()),
        sa.Column("message", sa.String(1024), nullable=False, server_default=""),
        sa.Column("metadata_json", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["operation_task.id"], ondelete="CASCADE"),
    )
    op.create_table(
        "reading_progress",
        sa.Column("manga_file_id", sa.Integer(), primary_key=True),
        sa.Column("page_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("page_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("percent", sa.Float(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["manga_file_id"], ["manga_file.id"], ondelete="CASCADE"),
    )
    op.create_table(
        "audit_event",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("actor_user_id", sa.String(64)),
        sa.Column("actor_group_id", sa.String(64)),
        sa.Column("client_ip", sa.String(64)),
        sa.Column("target_type", sa.String(64)),
        sa.Column("target_id", sa.String(128)),
        sa.Column("result", sa.String(32), nullable=False),
        sa.Column("error_code", sa.String(64)),
        sa.Column("metadata_json", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "backup_record",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("file_name", sa.String(512), nullable=False),
        sa.Column("relative_path", sa.String(1024), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sha256", sa.String(64)),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "scan_record",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("task_id", sa.String(36)),
        sa.Column("path_key", sa.String(255), nullable=False),
        sa.Column("scanned_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("added_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("missing_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("repaired_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["operation_task.id"]),
    )
    op.create_table(
        "setting_history",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("old_value_masked", sa.String(1024), nullable=False),
        sa.Column("new_value_masked", sa.String(1024), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("changed_by", sa.String(64), nullable=False),
        sa.Column("changed_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_task_event_task_created", "task_event", ["task_id", "created_at", "id"])
    op.create_index("ix_operation_task_status_created", "operation_task", ["status", "created_at", "id"])
    op.create_index("ix_operation_task_manga_created", "operation_task", ["manga_id", "created_at", "id"])
    op.create_index("ix_audit_event_type_created", "audit_event", ["event_type", "created_at", "id"])


def downgrade() -> None:
    """删除阶段 0 新增的管理表。"""
    op.drop_index("ix_audit_event_type_created", table_name="audit_event")
    op.drop_index("ix_operation_task_manga_created", table_name="operation_task")
    op.drop_index("ix_operation_task_status_created", table_name="operation_task")
    op.drop_index("ix_task_event_task_created", table_name="task_event")
    for table_name in (
        "setting_history",
        "scan_record",
        "backup_record",
        "audit_event",
        "reading_progress",
        "task_event",
        "operation_task",
        "tag",
    ):
        op.drop_table(table_name)
