"""登记现有 ORM schema 的 Alembic 基线。"""

from typing import Sequence, Union


revision: str = "0001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """基线不改变现有表结构。"""


def downgrade() -> None:
    """基线没有可回滚的结构变更。"""
