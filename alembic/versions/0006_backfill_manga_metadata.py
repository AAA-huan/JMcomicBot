"""回填漫画和文件元数据的过渡字段。"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0006_backfill_manga_metadata"
down_revision: Union[str, None] = "0005_normalize_tag_relation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """为已有记录填充可由旧字段推导出的元数据。"""
    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            UPDATE manga
            SET source_site = COALESCE(NULLIF(source_site, ''), 'jmcomic'),
                metadata_source = COALESCE(NULLIF(metadata_source, ''), 'jmcomic'),
                created_at = COALESCE(created_at, downloaded_at, CURRENT_TIMESTAMP),
                updated_at = COALESCE(updated_at, downloaded_at, CURRENT_TIMESTAMP)
            """
        )
    )
    columns = {
        column["name"] for column in sa.inspect(connection).get_columns("manga_file")
    }
    if {"file_path", "file_size_mb"} <= columns:
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
                    status = COALESCE(NULLIF(status, ''), 'ready'),
                    updated_at = COALESCE(updated_at, created_at, CURRENT_TIMESTAMP)
                """
            )
        )
    else:
        connection.execute(
            sa.text(
                """
                UPDATE manga_file
                SET display_name = COALESCE(NULLIF(display_name, ''), ''),
                    file_type = COALESCE(NULLIF(file_type, ''), 'pdf'),
                    mime_type = COALESCE(NULLIF(mime_type, ''), 'application/pdf'),
                    file_size_bytes = COALESCE(file_size_bytes, 0),
                    status = COALESCE(NULLIF(status, ''), 'ready'),
                    updated_at = COALESCE(updated_at, created_at, CURRENT_TIMESTAMP)
                """
            )
        )


def downgrade() -> None:
    """回滚不清理已回填数据，避免破坏旧字段事实。"""
