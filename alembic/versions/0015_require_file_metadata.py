"""收紧 PDF 文件元数据字段并回填旧记录。"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0015_require_file_metadata"
down_revision: Union[str, None] = "0014_remove_legacy_manga_tag_name"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """将可由旧字段推导的文件元数据统一为非空值。"""
    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            UPDATE manga_file
            SET display_name = COALESCE(NULLIF(display_name, ''), file_path),
                file_type = COALESCE(NULLIF(file_type, ''), 'pdf'),
                mime_type = COALESCE(NULLIF(mime_type, ''), 'application/pdf'),
                file_size_bytes = COALESCE(
                    file_size_bytes,
                    CAST(file_size_mb * 1024 * 1024 AS INTEGER),
                    0
                ),
                page_count = COALESCE(page_count, 0),
                status = COALESCE(NULLIF(status, ''), 'ready')
            """
        )
    )
    with op.batch_alter_table("manga_file") as batch_op:
        for name, column_type in (
            ("display_name", sa.String(512)),
            ("file_type", sa.String(32)),
            ("mime_type", sa.String(128)),
            ("file_size_bytes", sa.Integer()),
            ("page_count", sa.Integer()),
            ("status", sa.String(32)),
        ):
            batch_op.alter_column(name, existing_type=column_type, nullable=False)


def downgrade() -> None:
    """恢复文件元数据字段可空性。"""
    with op.batch_alter_table("manga_file") as batch_op:
        for name, column_type in (
            ("status", sa.String(32)),
            ("page_count", sa.Integer()),
            ("file_size_bytes", sa.Integer()),
            ("mime_type", sa.String(128)),
            ("file_type", sa.String(32)),
            ("display_name", sa.String(512)),
        ):
            batch_op.alter_column(name, existing_type=column_type, nullable=True)
