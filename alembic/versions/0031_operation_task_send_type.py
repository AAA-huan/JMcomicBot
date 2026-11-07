"""操作任务类型扩展，允许发送（send）任务。

- 发送流程（下载完成后把 PDF 发给 QQ 用户、`发送` 命令批量发送等）此前只写
  `task_log`，任务管理页看不到记录；本迁移为 `operation_task.task_type`
  的 CHECK 约束增加 `send`，配合服务层补写任务记录。
- SQLite 修改 CHECK 约束通过 `batch_alter_table` 重建表实现（与 0026 一致）。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0031_operation_task_send_type"
down_revision: Union[str, None] = "0030_add_reading_setting_prefetch_pages"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TASK_TYPES = (
    "('download', 'scan', 'repair', 'delete', 'backup', 'verify', 'blacklist', 'send')"
)
_LEGACY_TASK_TYPES = (
    "('download', 'scan', 'repair', 'delete', 'backup', 'verify', 'blacklist')"
)


def upgrade() -> None:
    """允许 send 任务类型。"""
    with op.batch_alter_table("operation_task") as batch_op:
        batch_op.drop_constraint("ck_operation_task_type", type_="check")
        batch_op.create_check_constraint(
            "ck_operation_task_type",
            f"task_type IN {_TASK_TYPES}",
        )


def downgrade() -> None:
    """存在发送任务记录时拒绝降级，避免静默丢失数据。"""
    connection = op.get_bind()
    send_count = connection.execute(
        sa.text("SELECT COUNT(*) FROM operation_task WHERE task_type = 'send'")
    ).scalar_one()
    if send_count:
        raise RuntimeError(f"存在 {send_count} 条发送任务记录，请先清理后再降级")
    with op.batch_alter_table("operation_task") as batch_op:
        batch_op.drop_constraint("ck_operation_task_type", type_="check")
        batch_op.create_check_constraint(
            "ck_operation_task_type",
            f"task_type IN {_LEGACY_TASK_TYPES}",
        )
