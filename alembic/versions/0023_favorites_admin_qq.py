"""新增漫画收藏和单管理员 QQ 关联，保留已有账户与权限。"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0023_favorites_admin_qq"
down_revision: Union[str, None] = "0022_add_reading_maintenance_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """新增收藏表与可空关联 QQ 字段。"""
    op.create_table(
        "manga_favorite",
        sa.Column("owner_type", sa.String(16), primary_key=True),
        sa.Column("owner_id", sa.String(20), primary_key=True),
        sa.Column("manga_id", sa.String(32), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["manga_id"], ["manga.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "owner_type IN ('web_admin', 'qq')", name="ck_favorite_owner_type"
        ),
        sa.CheckConstraint("length(owner_id) > 0", name="ck_favorite_owner_id"),
    )
    op.create_index("ix_manga_favorite_manga_id", "manga_favorite", ["manga_id"])
    with op.batch_alter_table("web_admin") as batch_op:
        batch_op.add_column(sa.Column("qq_id", sa.String(20), nullable=True))
        batch_op.create_unique_constraint("uq_web_admin_qq_id", ["qq_id"])


def downgrade() -> None:
    """新增数据未清空时拒绝降级，避免静默丢失收藏或授权关系。"""
    connection = op.get_bind()
    favorites = connection.execute(
        sa.text("SELECT COUNT(*) FROM manga_favorite")
    ).scalar_one()
    bindings = connection.execute(
        sa.text("SELECT COUNT(*) FROM web_admin WHERE qq_id IS NOT NULL")
    ).scalar_one()
    if favorites or bindings:
        raise RuntimeError("存在收藏或管理员 QQ 关联，请先清理后再降级")
    with op.batch_alter_table("web_admin") as batch_op:
        batch_op.drop_constraint("uq_web_admin_qq_id", type_="unique")
        batch_op.drop_column("qq_id")
    op.drop_table("manga_favorite")
