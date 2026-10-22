"""增加漫画黑名单表并扩展操作任务类型。

- 新建 `manga_blacklist`，按漫画 ID 记录拉黑元数据；
- 扩展 `operation_task.task_type` 约束，允许 `blacklist` 任务；
- 黑名单 ID 可能尚未下载，因此不与 `manga` 表建立物理外键。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0026_manga_blacklist"
down_revision: Union[str, None] = "0025_jm_favorite_import"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TASK_TYPES = (
    "('download', 'scan', 'repair', 'delete', 'backup', 'verify', 'blacklist')"
)
_LEGACY_TASK_TYPES = "('download', 'scan', 'repair', 'delete', 'backup', 'verify')"


def upgrade() -> None:
    """创建黑名单表并允许 blacklist 任务类型。"""
    op.create_table(
        "manga_blacklist",
        sa.Column("manga_id", sa.String(32), primary_key=True),
        sa.Column("reason", sa.String(255), nullable=True),
        sa.Column("requested_by", sa.String(64), nullable=True),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column(
            "blacklisted_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("operation_task_id", sa.String(36), nullable=True),
        sa.CheckConstraint(
            "source IN ('qq', 'web', 'system')",
            name="ck_manga_blacklist_source",
        ),
    )
    # 主键已提供唯一索引；额外命名索引与 ORM 声明保持一致，便于按 ID 检索。
    op.create_index(
        "ix_manga_blacklist_manga_id",
        "manga_blacklist",
        ["manga_id"],
    )
    with op.batch_alter_table("operation_task") as batch_op:
        batch_op.drop_constraint("ck_operation_task_type", type_="check")
        batch_op.create_check_constraint(
            "ck_operation_task_type",
            f"task_type IN {_TASK_TYPES}",
        )


def downgrade() -> None:
    """存在黑名单记录或 blacklist 任务时拒绝降级，避免静默丢失数据。"""
    connection = op.get_bind()
    blacklist_count = connection.execute(
        sa.text("SELECT COUNT(*) FROM manga_blacklist")
    ).scalar_one()
    if blacklist_count:
        raise RuntimeError(f"存在 {blacklist_count} 条漫画黑名单记录，请先清理后再降级")
    task_count = connection.execute(
        sa.text("SELECT COUNT(*) FROM operation_task WHERE task_type = 'blacklist'")
    ).scalar_one()
    if task_count:
        raise RuntimeError(f"存在 {task_count} 条 blacklist 任务记录，请先清理后再降级")
    with op.batch_alter_table("operation_task") as batch_op:
        batch_op.drop_constraint("ck_operation_task_type", type_="check")
        batch_op.create_check_constraint(
            "ck_operation_task_type",
            f"task_type IN {_LEGACY_TASK_TYPES}",
        )
    op.drop_index("ix_manga_blacklist_manga_id", table_name="manga_blacklist")
    op.drop_table("manga_blacklist")
