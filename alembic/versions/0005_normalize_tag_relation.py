"""为旧标签关系增加规范化标签外键。"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0005_normalize_tag_relation"
down_revision: Union[str, None] = "0004_manga_file_metadata"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """回填 tag 定义并建立漫画标签外键，保留旧列供过渡读取。"""
    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            INSERT INTO tag(name, normalized_name, created_at)
            SELECT DISTINCT tag, trim(tag), CURRENT_TIMESTAMP
            FROM manga_tag
            WHERE trim(tag) <> ''
              AND trim(tag) NOT IN (SELECT normalized_name FROM tag)
            """
        )
    )
    inspector = sa.inspect(connection)
    columns = {column["name"] for column in inspector.get_columns("manga_tag")}
    foreign_keys = inspector.get_foreign_keys("manga_tag")
    has_tag_foreign_key = any(
        foreign_key.get("referred_table") == "tag"
        and foreign_key.get("constrained_columns") == ["tag_id"]
        for foreign_key in foreign_keys
    )
    if "tag_id" not in columns or not has_tag_foreign_key:
        with op.batch_alter_table("manga_tag") as batch_op:
            if "tag_id" not in columns:
                batch_op.add_column(sa.Column("tag_id", sa.Integer(), nullable=True))
            batch_op.create_foreign_key(
                "fk_manga_tag_tag_id", "tag", ["tag_id"], ["id"], ondelete="CASCADE"
            )
    connection.execute(
        sa.text(
            """
            UPDATE manga_tag
            SET tag_id = (
                SELECT id FROM tag
                WHERE tag.normalized_name = trim(manga_tag.tag)
            )
            WHERE tag_id IS NULL
            """
        )
    )
    op.create_index("ix_manga_tag_tag_id_manga_id", "manga_tag", ["tag_id", "manga_id"])


def downgrade() -> None:
    """移除规范化标签外键和索引，保留旧文本标签列。"""
    op.drop_index("ix_manga_tag_tag_id_manga_id", table_name="manga_tag")
    with op.batch_alter_table("manga_tag") as batch_op:
        batch_op.drop_constraint("fk_manga_tag_tag_id", type_="foreignkey")
        batch_op.drop_column("tag_id")
