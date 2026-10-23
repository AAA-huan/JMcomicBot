"""漫画状态增加 favorited，用于表示已收藏但尚未下载。

SQLite 不支持直接修改 CHECK 约束，因此通过 batch 模式重建 manga 表。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0029_add_manga_status_favorited"
down_revision: Union[str, None] = "0028_drop_backup_record"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_STATUS_CHECK = (
    "status IN ('downloaded', 'missing_file', 'invalid', 'deleted', 'favorited')"
)
_OLD_STATUS_CHECK = "status IN ('downloaded', 'missing_file', 'invalid', 'deleted')"


def upgrade() -> None:
    """重建漫画表约束，允许 favorited 状态。"""
    with op.batch_alter_table("manga") as batch_op:
        batch_op.drop_constraint("ck_manga_status", type_="check")
        batch_op.create_check_constraint("ck_manga_status", _STATUS_CHECK)


def downgrade() -> None:
    """降级前把未下载收藏转为文件缺失，避免旧约束拒绝现有数据。"""
    connection = op.get_bind()
    connection.execute(
        sa.text("UPDATE manga SET status = 'missing_file' WHERE status = 'favorited'")
    )
    with op.batch_alter_table("manga") as batch_op:
        batch_op.drop_constraint("ck_manga_status", type_="check")
        batch_op.create_check_constraint("ck_manga_status", _OLD_STATUS_CHECK)
