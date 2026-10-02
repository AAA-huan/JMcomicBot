"""允许下载任务在漫画资料入库前保存目标漫画ID。"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0020_allow_pending_download_task"
down_revision: Union[str, None] = "0019_formalize_task_audit_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """移除 operation_task.manga_id 外键，保留目标ID用于下载前任务。"""
    if not any(
        item["constrained_columns"] == ["manga_id"]
        for item in sa.inspect(op.get_bind()).get_foreign_keys("operation_task")
    ):
        return
    naming_convention = {
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"
    }
    with op.batch_alter_table(
        "operation_task", naming_convention=naming_convention
    ) as batch_op:
        batch_op.drop_constraint("fk_operation_task_manga_id_manga", type_="foreignkey")


def downgrade() -> None:
    """恢复任务目标漫画外键；存在未入库漫画任务时会失败。"""
    with op.batch_alter_table("operation_task") as batch_op:
        batch_op.create_foreign_key(
            "fk_operation_task_manga_id", "manga", ["manga_id"], ["id"]
        )
