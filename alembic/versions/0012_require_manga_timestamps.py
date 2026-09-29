"""收紧漫画和文件记录的更新时间字段。"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0012_require_manga_timestamps"
down_revision: Union[str, None] = "0011_require_manga_tag_foreign_keys"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """先回填时间，再建立非空约束。"""
    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            UPDATE manga
            SET created_at = COALESCE(created_at, downloaded_at, CURRENT_TIMESTAMP),
                updated_at = COALESCE(updated_at, created_at, downloaded_at, CURRENT_TIMESTAMP)
            """
        )
    )
    connection.execute(
        sa.text(
            """
            UPDATE manga_file
            SET updated_at = COALESCE(updated_at, created_at, CURRENT_TIMESTAMP)
            """
        )
    )
    with op.batch_alter_table("manga") as batch_op:
        batch_op.alter_column("created_at", existing_type=sa.DateTime(), nullable=False)
        batch_op.alter_column("updated_at", existing_type=sa.DateTime(), nullable=False)
    with op.batch_alter_table("manga_file") as batch_op:
        batch_op.alter_column("updated_at", existing_type=sa.DateTime(), nullable=False)


def downgrade() -> None:
    """恢复时间字段可空性。"""
    with op.batch_alter_table("manga_file") as batch_op:
        batch_op.alter_column("updated_at", existing_type=sa.DateTime(), nullable=True)
    with op.batch_alter_table("manga") as batch_op:
        batch_op.alter_column("updated_at", existing_type=sa.DateTime(), nullable=True)
        batch_op.alter_column("created_at", existing_type=sa.DateTime(), nullable=True)
