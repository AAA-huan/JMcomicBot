"""收紧漫画标签关系的双向外键。"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0011_require_manga_tag_foreign_keys"
down_revision: Union[str, None] = "0010_remove_legacy_tag_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """清理孤儿关系并要求漫画和标签均存在。"""
    connection = op.get_bind()
    connection.execute(sa.text("""
            DELETE FROM manga_tag
            WHERE NOT EXISTS (
                SELECT 1 FROM manga WHERE manga.id = manga_tag.manga_id
            )
            """))
    connection.execute(sa.text("""
            DELETE FROM manga_tag
            WHERE tag_id IS NULL
               OR NOT EXISTS (
                   SELECT 1 FROM tag WHERE tag.id = manga_tag.tag_id
               )
            """))
    inspector = sa.inspect(connection)
    foreign_keys = inspector.get_foreign_keys("manga_tag")
    has_manga_foreign_key = any(
        item.get("referred_table") == "manga"
        and item.get("constrained_columns") == ["manga_id"]
        for item in foreign_keys
    )
    has_tag_foreign_key = any(
        item.get("referred_table") == "tag"
        and item.get("constrained_columns") == ["tag_id"]
        for item in foreign_keys
    )
    with op.batch_alter_table("manga_tag") as batch_op:
        if not has_manga_foreign_key:
            batch_op.create_foreign_key(
                "fk_manga_tag_manga_id",
                "manga",
                ["manga_id"],
                ["id"],
                ondelete="CASCADE",
            )
        if not has_tag_foreign_key:
            batch_op.create_foreign_key(
                "fk_manga_tag_tag_id", "tag", ["tag_id"], ["id"], ondelete="CASCADE"
            )
        batch_op.alter_column("tag_id", existing_type=sa.Integer(), nullable=False)


def downgrade() -> None:
    """恢复标签关系的兼容性约束。"""
    with op.batch_alter_table("manga_tag") as batch_op:
        batch_op.alter_column("tag_id", existing_type=sa.Integer(), nullable=True)
        batch_op.drop_constraint("fk_manga_tag_manga_id", type_="foreignkey")
        batch_op.drop_constraint("fk_manga_tag_tag_id", type_="foreignkey")
