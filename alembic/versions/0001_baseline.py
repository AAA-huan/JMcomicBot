"""创建旧版核心 schema，供后续迁移逐步升级。"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """为空数据库创建核心表；已有旧库保持原结构不变。"""
    inspector = sa.inspect(op.get_bind())
    existing_tables = set(inspector.get_table_names())
    if "manga" not in existing_tables:
        op.create_table(
            "manga",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("title", sa.String(255), nullable=False, server_default=""),
            sa.Column("author", sa.String(255), nullable=False, server_default=""),
            sa.Column("tags", sa.String(1024), nullable=False, server_default=""),
            sa.Column(
                "chapter_count", sa.Integer(), nullable=False, server_default="0"
            ),
            sa.Column("page_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "status", sa.String(32), nullable=False, server_default="downloaded"
            ),
            sa.Column("downloaded_at", sa.DateTime(), nullable=False),
        )
    if "manga_file" not in existing_tables:
        op.create_table(
            "manga_file",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("manga_id", sa.String(32), nullable=False),
            sa.Column("file_path", sa.String(1024), nullable=False, unique=True),
            sa.Column("file_size_mb", sa.Float(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["manga_id"], ["manga.id"], ondelete="CASCADE"),
        )
        op.create_index("ix_manga_file_manga_id", "manga_file", ["manga_id"])
    if "manga_tag" not in existing_tables:
        op.create_table(
            "manga_tag",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("tag", sa.String(128), nullable=False),
            sa.Column("manga_id", sa.String(32), nullable=False),
            sa.Column("pdf_name", sa.String(512), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("tag", "manga_id", name="uq_manga_tag_tag_manga"),
        )
        op.create_index("ix_manga_tag_tag", "manga_tag", ["tag"])
        op.create_index("ix_manga_tag_manga_id", "manga_tag", ["manga_id"])
    if "task_log" not in existing_tables:
        op.create_table(
            "task_log",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("task_type", sa.String(32), nullable=False),
            sa.Column(
                "status", sa.String(32), nullable=False, server_default="pending"
            ),
            sa.Column("manga_id", sa.String(32), nullable=False, server_default=""),
            sa.Column("user_id", sa.String(64), nullable=False, server_default=""),
            sa.Column("group_id", sa.String(64), nullable=False, server_default=""),
            sa.Column(
                "private", sa.Boolean(), nullable=False, server_default=sa.true()
            ),
            sa.Column("message", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_task_log_task_type", "task_log", ["task_type"])
        op.create_index("ix_task_log_created_at", "task_log", ["created_at"])
    if "user_info" not in existing_tables:
        op.create_table(
            "user_info",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("nickname", sa.String(255), nullable=False, server_default=""),
            sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        )
    if "group_info" not in existing_tables:
        op.create_table(
            "group_info",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("group_name", sa.String(255), nullable=False, server_default=""),
            sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        )
    if "permission" not in existing_tables:
        op.create_table(
            "permission",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("scope", sa.String(32), nullable=False),
            sa.Column("value", sa.String(64), nullable=False),
            sa.Column("remark", sa.String(255), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("scope", "value", name="uq_permission_scope_value"),
        )
        op.create_index("ix_permission_scope", "permission", ["scope"])
    if "setting" not in existing_tables:
        op.create_table(
            "setting",
            sa.Column("key", sa.String(128), primary_key=True),
            sa.Column("value", sa.String(1024), nullable=False, server_default=""),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )


def downgrade() -> None:
    """基线可能登记已有旧库，因此不自动删除用户表。"""
