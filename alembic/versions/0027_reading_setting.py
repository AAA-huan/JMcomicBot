"""增加阅读器偏好设置表。

- 新建 `reading_setting`，按 Web 管理员账户保存阅读模式与显示偏好；
- 管理员删除时级联删除对应设置；
- 降级仅在表为空时允许，避免静默丢失用户设置。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0027_reading_setting"
down_revision: Union[str, None] = "0026_manga_blacklist"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建阅读设置表及模式约束。"""
    op.create_table(
        "reading_setting",
        sa.Column(
            "admin_id",
            sa.Integer(),
            sa.ForeignKey("web_admin.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "reading_mode",
            sa.String(16),
            nullable=False,
            server_default="normal",
        ),
        sa.Column(
            "continuous",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "click_to_turn",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "reverse_click",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "dark_background",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "reading_mode IN ('normal', 'manga', 'scroll')",
            name="ck_reading_setting_mode",
        ),
    )


def downgrade() -> None:
    """存在阅读设置记录时拒绝降级，避免静默丢失设置。"""
    connection = op.get_bind()
    setting_count = connection.execute(
        sa.text("SELECT COUNT(*) FROM reading_setting")
    ).scalar_one()
    if setting_count:
        raise RuntimeError(f"存在 {setting_count} 条阅读设置记录，请先清理后再降级")
    op.drop_table("reading_setting")
