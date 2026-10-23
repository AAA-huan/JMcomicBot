"""阅读设置增加连续模式预加载页数。

`prefetch_pages` 表示连续模式当前页前后保留的页数半径；默认 1 保持原有行为。
SQLite 使用 batch 模式添加非空列并写入服务端默认值。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0030_add_reading_setting_prefetch_pages"
down_revision: Union[str, None] = "0029_add_manga_status_favorited"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """为阅读设置表添加预加载页数，历史记录按默认值 1 补齐。"""
    with op.batch_alter_table("reading_setting") as batch_op:
        batch_op.add_column(
            sa.Column(
                "prefetch_pages",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("1"),
            )
        )


def downgrade() -> None:
    """降级删除预加载页数，恢复原有阅读设置结构。"""
    with op.batch_alter_table("reading_setting") as batch_op:
        batch_op.drop_column("prefetch_pages")
