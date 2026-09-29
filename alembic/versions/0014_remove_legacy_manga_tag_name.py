"""删除漫画标签关系中的冗余文本标签列。"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0014_remove_legacy_manga_tag_name"
down_revision: Union[str, None] = "0013_add_management_query_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """保留规范化标签定义，只删除关系表中的文本副本。"""
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    columns = {column["name"] for column in inspector.get_columns("manga_tag")}
    indexes = {index["name"] for index in inspector.get_indexes("manga_tag")}
    constraints = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("manga_tag")
    }
    if "ix_manga_tag_tag" in indexes:
        op.drop_index("ix_manga_tag_tag", table_name="manga_tag")
    with op.batch_alter_table("manga_tag") as batch_op:
        if "uq_manga_tag_tag_manga" in constraints:
            batch_op.drop_constraint("uq_manga_tag_tag_manga", type_="unique")
        if "tag" in columns:
            batch_op.drop_column("tag")


def downgrade() -> None:
    """恢复兼容文本标签列。"""
    op.add_column("manga_tag", sa.Column("tag", sa.String(128), nullable=True))
    op.create_index("ix_manga_tag_tag", "manga_tag", ["tag"])
