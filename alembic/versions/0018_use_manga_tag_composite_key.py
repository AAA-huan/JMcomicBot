"""将漫画标签关系改为联合主键。"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0018_use_manga_tag_composite_key"
down_revision: Union[str, None] = "0017_remove_legacy_file_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """删除代理主键和重复索引，使用漫画与标签联合主键。"""
    indexes = {
        index["name"] for index in sa.inspect(op.get_bind()).get_indexes("manga_tag")
    }
    if "ix_manga_tag_manga_id" in indexes:
        op.drop_index("ix_manga_tag_manga_id", table_name="manga_tag")
    if "uq_manga_tag_manga_tag" in indexes:
        op.drop_index("uq_manga_tag_manga_tag", table_name="manga_tag")
    with op.batch_alter_table("manga_tag", recreate="always") as batch_op:
        batch_op.drop_column("id")
        batch_op.create_primary_key("pk_manga_tag", ["manga_id", "tag_id"])


def downgrade() -> None:
    """恢复代理主键和漫画ID索引。"""
    with op.batch_alter_table("manga_tag", recreate="always") as batch_op:
        batch_op.drop_constraint("pk_manga_tag", type_="primary")
        batch_op.add_column(
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True)
        )
        batch_op.create_unique_constraint(
            "uq_manga_tag_manga_tag", ["manga_id", "tag_id"]
        )
    op.create_index("ix_manga_tag_manga_id", "manga_tag", ["manga_id"])
