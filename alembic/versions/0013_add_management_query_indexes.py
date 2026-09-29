"""补齐管理列表查询所需的复合索引。"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0013_add_management_query_indexes"
down_revision: Union[str, None] = "0012_require_manga_timestamps"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_INDEXES = (
    ("ix_operation_task_type_status_created", "operation_task", ("task_type", "status", "created_at", "id")),
    ("ix_operation_task_source_created", "operation_task", ("source", "created_at", "id")),
    ("ix_audit_event_source_created", "audit_event", ("source", "created_at", "id")),
    ("ix_reading_progress_updated", "reading_progress", ("updated_at",)),
    ("ix_user_info_last_seen", "user_info", ("last_seen_at", "id")),
    ("ix_group_info_last_seen", "group_info", ("last_seen_at", "id")),
)


def upgrade() -> None:
    """为阶段 0 规定的分页和筛选查询建立索引。"""
    connection = op.get_bind()
    existing = {
        index["name"]
        for table_name in {item[1] for item in _INDEXES}
        for index in sa.inspect(connection).get_indexes(table_name)
    }
    for name, table_name, columns in _INDEXES:
        if name not in existing:
            op.create_index(name, table_name, list(columns))


def downgrade() -> None:
    """移除管理列表查询索引。"""
    for name, table_name, _columns in reversed(_INDEXES):
        op.drop_index(name, table_name=table_name)
