"""增加 WebUI 管理员与会话表。"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0003_web_tables"
down_revision: Union[str, None] = "0002_management_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建单管理员登录和会话存储表。"""
    op.create_table(
        "web_admin",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("password_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("last_login_at", sa.DateTime()),
        sa.CheckConstraint("id = 1", name="ck_web_admin_singleton"),
    )
    op.create_table(
        "web_session",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("token_hash", sa.String(128), nullable=False, unique=True),
        sa.Column("admin_id", sa.Integer(), nullable=False),
        sa.Column("password_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["admin_id"], ["web_admin.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_web_session_expires_at", "web_session", ["expires_at"])


def downgrade() -> None:
    """删除 WebUI 管理员与会话表。"""
    op.drop_index("ix_web_session_expires_at", table_name="web_session")
    op.drop_table("web_session")
    op.drop_table("web_admin")
