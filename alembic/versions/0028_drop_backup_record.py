"""移除数据库备份记录表。

备份功能已由数据导出替代，`backup_record` 不再使用；降级不重建该表，
因为旧备份功能同时依赖服务、仓储与前端，单独恢复表结构没有意义。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0028_drop_backup_record"
down_revision: Union[str, None] = "0027_reading_setting"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """删除备份记录表。"""
    table_names = sa.inspect(op.get_bind()).get_table_names()
    if "backup_record" in table_names:
        op.drop_table("backup_record")


def downgrade() -> None:
    """不重建已移除的备份记录表。"""
