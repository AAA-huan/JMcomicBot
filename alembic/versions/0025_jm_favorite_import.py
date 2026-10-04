"""保存 JM 远端收藏与导入进度，账号密码和 Cookie 不入库。"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0025_jm_favorite_import"
down_revision: Union[str, None] = "0024_manga_remote_metadata"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """增加独立索引，不改变本地漫画和收藏结构。"""
    op.create_table(
        "jm_remote_favorite",
        sa.Column(
            "admin_id",
            sa.Integer(),
            primary_key=True,
        ),
        sa.Column("username", sa.String(128), primary_key=True),
        sa.Column("manga_id", sa.String(32), primary_key=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("folders", sa.JSON(), nullable=False),
        sa.Column("pending_local_favorite", sa.Boolean(), nullable=False),
        sa.Column("imported_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("admin_id > 0", name="ck_jm_remote_favorite_admin"),
    )
    op.create_table(
        "jm_favorite_import",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "admin_id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column("username", sa.String(128), nullable=False),
        sa.Column("folder_ids", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("pages_done", sa.Integer(), nullable=False),
        sa.Column("imported_count", sa.Integer(), nullable=False),
        sa.Column("duplicate_count", sa.Integer(), nullable=False),
        sa.Column("local_count", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'failed', 'interrupted')",
            name="ck_jm_favorite_import_status",
        ),
        sa.CheckConstraint("admin_id > 0", name="ck_jm_favorite_import_admin"),
    )
    op.create_index(
        "ix_jm_favorite_import_admin_created",
        "jm_favorite_import",
        ["admin_id", "created_at"],
    )


def downgrade() -> None:
    """存在导入记录时拒绝静默删除用户数据。"""
    for table in ("jm_remote_favorite", "jm_favorite_import"):
        if op.get_bind().execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar_one():
            raise RuntimeError("存在 JM 收藏导入记录，请先清理后再降级")
    op.drop_index(
        "ix_jm_favorite_import_admin_created", table_name="jm_favorite_import"
    )
    op.drop_table("jm_favorite_import")
    op.drop_table("jm_remote_favorite")
