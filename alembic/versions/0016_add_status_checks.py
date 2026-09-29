"""为漫画和 PDF 状态增加数据库级约束。"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0016_add_status_checks"
down_revision: Union[str, None] = "0015_require_file_metadata"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """归一化未知状态并建立 CHECK 约束。"""
    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            UPDATE manga
            SET status = 'invalid'
            WHERE status NOT IN ('downloaded', 'missing_file', 'invalid', 'deleted')
            """
        )
    )
    connection.execute(
        sa.text(
            """
            UPDATE manga_file
            SET status = 'invalid_path'
            WHERE status NOT IN (
                'ready', 'missing', 'corrupted', 'deleting', 'deleted', 'invalid_path'
            )
            """
        )
    )
    manga_checks = {
        item["name"]
        for item in sa.inspect(connection).get_check_constraints("manga")
    }
    file_checks = {
        item["name"]
        for item in sa.inspect(connection).get_check_constraints("manga_file")
    }
    if "ck_manga_status" not in manga_checks:
        with op.batch_alter_table("manga") as batch_op:
            batch_op.create_check_constraint(
                "ck_manga_status",
                "status IN ('downloaded', 'missing_file', 'invalid', 'deleted')",
            )
    if "ck_manga_file_status" not in file_checks:
        with op.batch_alter_table("manga_file") as batch_op:
            batch_op.create_check_constraint(
                "ck_manga_file_status",
                "status IN ('ready', 'missing', 'corrupted', 'deleting', 'deleted', 'invalid_path')",
            )


def downgrade() -> None:
    """移除状态 CHECK 约束。"""
    with op.batch_alter_table("manga_file") as batch_op:
        batch_op.drop_constraint("ck_manga_file_status", type_="check")
    with op.batch_alter_table("manga") as batch_op:
        batch_op.drop_constraint("ck_manga_status", type_="check")
