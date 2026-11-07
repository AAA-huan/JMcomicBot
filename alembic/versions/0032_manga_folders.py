"""新增本地自定义漫画文件夹。

- `manga_folder` 保存文件夹名称（唯一）与排序；
- `manga_folder_member` 为文件夹与漫画的多对多关系，同一漫画可加入多个文件夹；
- 两个外键均级联删除：删除文件夹或漫画时成员关系自动清理；
- 本地分组为全新功能，与 JM 站远端收藏夹（jm_remote_favorite）不联动。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0032_manga_folders"
down_revision: Union[str, None] = "0031_operation_task_send_type"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建文件夹表与成员关系表。"""
    op.create_table(
        "manga_folder",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_manga_folder_name"),
    )
    op.create_table(
        "manga_folder_member",
        sa.Column("folder_id", sa.Integer(), nullable=False),
        sa.Column("manga_id", sa.String(32), nullable=False),
        sa.Column("added_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("folder_id", "manga_id"),
        sa.ForeignKeyConstraint(["folder_id"], ["manga_folder.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["manga_id"], ["manga.id"], ondelete="CASCADE"),
    )
    # 主键只能按文件夹维度检索，反向查询（漫画所在文件夹）与列表筛选需要此索引
    op.create_index(
        "ix_manga_folder_member_manga_id", "manga_folder_member", ["manga_id"]
    )


def downgrade() -> None:
    """存在文件夹数据时拒绝降级，避免静默丢失用户分组。"""
    connection = op.get_bind()
    folder_count = connection.execute(
        sa.text("SELECT COUNT(*) FROM manga_folder")
    ).scalar_one()
    if folder_count:
        raise RuntimeError(f"存在 {folder_count} 个漫画文件夹，请先清理后再降级")
    op.drop_index("ix_manga_folder_member_manga_id", table_name="manga_folder_member")
    op.drop_table("manga_folder_member")
    op.drop_table("manga_folder")
