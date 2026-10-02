"""落实一个漫画只关联一个 PDF 的唯一约束。"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0008_unique_manga_file"
down_revision: Union[str, None] = "0007_unique_relative_file_path"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """为漫画文件关系增加唯一索引。"""
    inspector = sa.inspect(op.get_bind())
    if "uq_manga_file_manga_id" not in {
        index["name"] for index in inspector.get_indexes("manga_file")
    }:
        op.create_index(
            "uq_manga_file_manga_id", "manga_file", ["manga_id"], unique=True
        )


def downgrade() -> None:
    """移除漫画文件唯一索引。"""
    op.drop_index("uq_manga_file_manga_id", table_name="manga_file")
