"""删除漫画文件的绝对路径和浮点大小兼容列。"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0017_remove_legacy_file_columns"
down_revision: Union[str, None] = "0016_add_status_checks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """删除已完成迁移的旧文件字段并收紧相对路径。"""
    connection = op.get_bind()
    columns = {
        column["name"] for column in sa.inspect(connection).get_columns("manga_file")
    }
    if "relative_path" in columns:
        missing_count = connection.execute(
            sa.text("SELECT COUNT(*) FROM manga_file WHERE relative_path IS NULL")
        ).scalar_one()
        if missing_count:
            raise RuntimeError(
                f"仍有 {missing_count} 条文件记录缺少相对路径，迁移已停止"
            )
    with op.batch_alter_table("manga_file") as batch_op:
        if "file_path" in columns:
            batch_op.drop_column("file_path")
        if "file_size_mb" in columns:
            batch_op.drop_column("file_size_mb")
        batch_op.alter_column(
            "relative_path", existing_type=sa.String(1024), nullable=False
        )


def downgrade() -> None:
    """恢复旧文件字段，但不填充历史绝对路径。"""
    op.add_column("manga_file", sa.Column("file_path", sa.String(1024), nullable=True))
    op.add_column("manga_file", sa.Column("file_size_mb", sa.Float(), nullable=True))
    with op.batch_alter_table("manga_file") as batch_op:
        batch_op.alter_column(
            "relative_path", existing_type=sa.String(1024), nullable=True
        )
