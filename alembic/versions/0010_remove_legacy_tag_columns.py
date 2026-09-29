"""删除逗号标签和 PDF 名称冗余字段。"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0010_remove_legacy_tag_columns"
down_revision: Union[str, None] = "0009_formal_manga_tag_relation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """删除已不再作为事实来源的旧字段。"""
    connection = op.get_bind()
    manga_columns = {column["name"] for column in sa.inspect(connection).get_columns("manga")}
    manga_tag_columns = {
        column["name"] for column in sa.inspect(connection).get_columns("manga_tag")
    }
    if "tags" in manga_columns:
        with op.batch_alter_table("manga") as batch_op:
            batch_op.drop_column("tags")
    if "pdf_name" in manga_tag_columns:
        with op.batch_alter_table("manga_tag") as batch_op:
            batch_op.drop_column("pdf_name")


def downgrade() -> None:
    """恢复兼容列，但不恢复历史冗余数据。"""
    op.add_column("manga", sa.Column("tags", sa.String(1024), nullable=True))
    op.add_column("manga_tag", sa.Column("pdf_name", sa.String(512), nullable=True))
