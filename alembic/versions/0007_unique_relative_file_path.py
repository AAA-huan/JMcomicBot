"""为新版文件相对路径增加唯一约束。"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0007_unique_relative_file_path"
down_revision: Union[str, None] = "0006_backfill_manga_metadata"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """阻止同一相对路径被重复登记。"""
    inspector = sa.inspect(op.get_bind())
    existing_indexes = {index["name"] for index in inspector.get_indexes("manga_file")}
    if "uq_manga_file_relative_path" not in existing_indexes:
        op.create_index(
            "uq_manga_file_relative_path",
            "manga_file",
            ["relative_path"],
            unique=True,
        )


def downgrade() -> None:
    """移除相对路径唯一约束。"""
    op.drop_index("uq_manga_file_relative_path", table_name="manga_file")
