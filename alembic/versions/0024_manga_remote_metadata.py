"""独立保存漫画站点元数据，避免覆盖本地下载信息。"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0024_manga_remote_metadata"
down_revision: Union[str, None] = "0023_favorites_admin_qq"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """新增可空 JSON 快照，已有记录无需联网或修改页数。"""
    with op.batch_alter_table("manga") as batch_op:
        batch_op.add_column(sa.Column("remote_metadata", sa.JSON(), nullable=True))


def downgrade() -> None:
    """存在快照时拒绝丢失已保存的站点信息。"""
    count = (
        op.get_bind()
        .execute(
            sa.text("SELECT COUNT(*) FROM manga WHERE remote_metadata IS NOT NULL")
        )
        .scalar_one()
    )
    if count:
        raise RuntimeError("存在站点元数据，请先清理后再降级")
    with op.batch_alter_table("manga") as batch_op:
        batch_op.drop_column("remote_metadata")
