"""将漫画标签关系切换为漫画 ID 与标签 ID 的正式关系。"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0009_formal_manga_tag_relation"
down_revision: Union[str, None] = "0008_unique_manga_file"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """补齐关系外键并建立正式联合唯一索引。"""
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    foreign_keys = inspector.get_foreign_keys("manga_tag")
    constrained = {
        (tuple(item["constrained_columns"]), item["referred_table"])
        for item in foreign_keys
    }
    if (tuple(["tag_id"]), "tag") not in constrained:
        with op.batch_alter_table("manga_tag") as batch_op:
            batch_op.create_foreign_key(
                "fk_manga_tag_tag_id_formal", "tag", ["tag_id"], ["id"], ondelete="CASCADE"
            )
    if "uq_manga_tag_manga_tag" not in {
        index["name"] for index in sa.inspect(connection).get_indexes("manga_tag")
    }:
        op.create_index(
            "uq_manga_tag_manga_tag",
            "manga_tag",
            ["manga_id", "tag_id"],
            unique=True,
        )


def downgrade() -> None:
    """移除正式关系联合唯一索引。"""
    op.drop_index("uq_manga_tag_manga_tag", table_name="manga_tag")
