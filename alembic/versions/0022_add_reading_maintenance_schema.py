"""增加阅读进度、维护记录与文件校验所需结构。

本迁移对应 database.md 阶段三：
- operation_task 增加 verify 任务类型；
- manga_file 增加 file_mtime，用于识别文件被替换或重新生成；
- scan_record 由阶段 0 占位表重建为 scan/repair/verify 共用的正式统计表；
- backup_record 由阶段 0 占位表重建为备份记录表（含 updated_at/deleted_at 与唯一路径）；
- reading_progress 已由 0002 以目标结构创建、0013 建立索引，本迁移不做变更。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0022_add_reading_maintenance_schema"
down_revision: Union[str, None] = "0021_add_operation_task_summary"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TASK_TYPES = "('download', 'scan', 'repair', 'delete', 'backup', 'verify')"
_LEGACY_TASK_TYPES = "('download', 'scan', 'repair', 'delete', 'backup')"
_LEGACY_PLACEHOLDER_TABLES = ("scan_record", "backup_record")


def _reject_invalid_rows(connection: sa.Connection) -> None:
    """迁移前校验旧数据，发现无法安全转换的记录时停止而不是隐式丢弃。"""
    invalid_tasks = connection.execute(
        sa.text(
            "SELECT COUNT(*) FROM operation_task "
            f"WHERE task_type NOT IN {_TASK_TYPES}"
        )
    ).scalar_one()
    if invalid_tasks:
        raise RuntimeError(
            f"operation_task 存在 {invalid_tasks} 条未知任务类型记录，迁移已停止"
        )
    # scan_record 与 backup_record 是阶段 0 预留的占位表，从未被应用代码写入；
    # 若发现数据，说明存在本迁移无法安全转换的内容，停止等待人工确认。
    for table_name in _LEGACY_PLACEHOLDER_TABLES:
        count = connection.execute(
            sa.text(f"SELECT COUNT(*) FROM {table_name}")
        ).scalar_one()
        if count:
            raise RuntimeError(
                f"占位表 {table_name} 存在 {count} 条记录，无法安全重建，"
                "请先人工确认这些数据的归属"
            )


def _create_scan_record() -> None:
    """创建 scan/repair/verify 共用的正式扫描统计表。"""
    op.create_table(
        "scan_record",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("task_id", sa.String(36), nullable=False),
        sa.Column("task_type", sa.String(32), nullable=False),
        sa.Column("path_label", sa.String(128), nullable=False),
        sa.Column("file_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("new_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("missing_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("repaired_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("corrupted_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["operation_task.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "task_type IN ('scan', 'repair', 'verify')",
            name="ck_scan_record_task_type",
        ),
    )
    op.create_index("ix_scan_record_task_id", "scan_record", ["task_id"])
    op.create_index("ix_scan_record_created", "scan_record", ["created_at", "id"])


def _drop_scan_record() -> None:
    """删除 scan_record；SQLite 会随表自动删除所属索引。"""
    op.drop_table("scan_record")


def _create_backup_record() -> None:
    """创建备份记录表，记录备份文件的一致性信息。"""
    op.create_table(
        "backup_record",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column("relative_path", sa.String(1024), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sha256", sa.String(64), nullable=True),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("relative_path", name="uq_backup_record_relative_path"),
        sa.CheckConstraint(
            "status IN ('creating', 'ready', 'failed', 'deleted')",
            name="ck_backup_record_status",
        ),
    )
    op.create_index(
        "ix_backup_record_status_created", "backup_record", ["status", "created_at"]
    )
    op.create_index("ix_backup_record_created", "backup_record", ["created_at", "id"])


def _drop_backup_record() -> None:
    """删除 backup_record；SQLite 会随表自动删除所属索引。"""
    op.drop_table("backup_record")


def upgrade() -> None:
    """增加阶段三所需的表、字段、约束和索引。"""
    _reject_invalid_rows(op.get_bind())

    # operation_task：扩展 verify 任务类型
    with op.batch_alter_table("operation_task") as batch_op:
        batch_op.drop_constraint("ck_operation_task_type", type_="check")
        batch_op.create_check_constraint(
            "ck_operation_task_type",
            f"task_type IN {_TASK_TYPES}",
        )

    # manga_file：增加文件修改时间，用于识别文件被替换或重新生成
    with op.batch_alter_table("manga_file") as batch_op:
        batch_op.add_column(sa.Column("file_mtime", sa.DateTime(), nullable=True))

    # scan_record：占位表重建为 scan/repair/verify 共用的正式统计表
    _drop_scan_record()
    _create_scan_record()

    # backup_record：占位表重建为正式备份记录表
    _drop_backup_record()
    _create_backup_record()


def downgrade() -> None:
    """回退阶段三结构；存在 verify 任务时明确报错而不是破坏数据。"""
    connection = op.get_bind()
    verify_count = connection.execute(
        sa.text("SELECT COUNT(*) FROM operation_task WHERE task_type = 'verify'")
    ).scalar_one()
    if verify_count:
        raise RuntimeError(f"存在 {verify_count} 条 verify 任务，回退前请先人工处理")

    # 恢复 backup_record 的旧占位结构
    _drop_backup_record()
    op.create_table(
        "backup_record",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("file_name", sa.String(512), nullable=False),
        sa.Column("relative_path", sa.String(1024), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sha256", sa.String(64)),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    # 恢复 scan_record 的旧占位结构
    _drop_scan_record()
    op.create_table(
        "scan_record",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("task_id", sa.String(36)),
        sa.Column("path_key", sa.String(255), nullable=False),
        sa.Column("scanned_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("added_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("missing_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("repaired_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["operation_task.id"]),
    )

    # 移除 file_mtime
    with op.batch_alter_table("manga_file") as batch_op:
        batch_op.drop_column("file_mtime")

    # 恢复 operation_task 的五种任务类型
    with op.batch_alter_table("operation_task") as batch_op:
        batch_op.drop_constraint("ck_operation_task_type", type_="check")
        batch_op.create_check_constraint(
            "ck_operation_task_type",
            f"task_type IN {_LEGACY_TASK_TYPES}",
        )
