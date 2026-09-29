"""为持久化任务增加渠道无关的中文摘要。"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0021_add_operation_task_summary"
down_revision: Union[str, None] = "0020_allow_pending_download_task"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """增加摘要字段，并为已有任务生成安全的中文摘要。"""
    with op.batch_alter_table("operation_task") as batch_op:
        batch_op.add_column(
            sa.Column("summary", sa.String(255), nullable=False, server_default="")
        )

    op.execute(sa.text("""
        UPDATE operation_task
        SET summary = CASE task_type
            WHEN 'download' THEN '下载漫画' || CASE
                WHEN manga_id IS NULL THEN '' ELSE ' ' || manga_id END
            WHEN 'scan' THEN '扫描漫画目录'
            WHEN 'repair' THEN '修复漫画资料'
            WHEN 'delete' THEN '删除漫画' || CASE
                WHEN manga_id IS NULL THEN '' ELSE ' ' || manga_id END
            WHEN 'backup' THEN '备份数据库'
            ELSE '后台任务'
        END
        WHERE summary = ''
    """))


def downgrade() -> None:
    """移除任务摘要字段。"""
    with op.batch_alter_table("operation_task") as batch_op:
        batch_op.drop_column("summary")
