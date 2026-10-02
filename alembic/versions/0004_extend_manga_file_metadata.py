"""为漫画和 PDF 记录增加新版元数据字段。"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004_manga_file_metadata"
down_revision: Union[str, None] = "0003_web_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """增加兼容字段，为后续仓储切换准备数据承载。"""
    inspector = sa.inspect(op.get_bind())
    manga_columns = (
        ("source_site", sa.String(64), "jmcomic"),
        ("description", sa.Text(), None),
        ("metadata_source", sa.String(64), "jmcomic"),
        ("created_at", sa.DateTime(), None),
        ("updated_at", sa.DateTime(), None),
        ("last_verified_at", sa.DateTime(), None),
    )
    for name, column_type, default in manga_columns:
        if name not in {column["name"] for column in inspector.get_columns("manga")}:
            op.add_column(
                "manga",
                sa.Column(name, column_type, server_default=default, nullable=True),
            )

    file_columns = (
        ("relative_path", sa.String(1024)),
        ("display_name", sa.String(512)),
        ("file_type", sa.String(32)),
        ("mime_type", sa.String(128)),
        ("file_size_bytes", sa.Integer()),
        ("page_count", sa.Integer()),
        ("sha256", sa.String(64)),
        ("status", sa.String(32)),
        ("updated_at", sa.DateTime()),
        ("last_verified_at", sa.DateTime()),
        ("deleted_at", sa.DateTime()),
    )
    for name, column_type in file_columns:
        if name not in {
            column["name"] for column in inspector.get_columns("manga_file")
        }:
            op.add_column("manga_file", sa.Column(name, column_type, nullable=True))

    op.create_index(
        "ix_manga_status_downloaded", "manga", ["status", "downloaded_at", "id"]
    )
    op.create_index("ix_manga_updated", "manga", ["updated_at", "id"])
    op.create_index(
        "ix_manga_file_status_updated", "manga_file", ["status", "updated_at"]
    )
    op.create_index("ix_manga_file_verified", "manga_file", ["last_verified_at"])


def downgrade() -> None:
    """删除新版漫画和文件元数据字段。"""
    op.drop_index("ix_manga_file_verified", table_name="manga_file")
    op.drop_index("ix_manga_file_status_updated", table_name="manga_file")
    op.drop_index("ix_manga_updated", table_name="manga")
    op.drop_index("ix_manga_status_downloaded", table_name="manga")
    for name in (
        "deleted_at",
        "last_verified_at",
        "updated_at",
        "status",
        "sha256",
        "page_count",
        "file_size_bytes",
        "mime_type",
        "file_type",
        "display_name",
        "relative_path",
    ):
        op.drop_column("manga_file", name)
    for name in (
        "last_verified_at",
        "updated_at",
        "created_at",
        "metadata_source",
        "description",
        "source_site",
    ):
        op.drop_column("manga", name)
