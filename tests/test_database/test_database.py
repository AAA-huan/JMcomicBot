"""数据库管理器初始化与表结构创建测试"""

import pytest
from sqlalchemy import inspect, text

from src.database.database import DatabaseManager
from src.database.migrations import backup_database


class TestDatabaseManager:
    """数据库管理器测试类"""

    def test_init_db_creates_tables(self, db_manager: DatabaseManager) -> None:
        """初始化后应创建全部预期的表"""
        tables = set(inspect(db_manager.engine).get_table_names())
        expected = {
            "manga",
            "manga_file",
            "task_log",
            "user_info",
            "group_info",
            "permission",
            "setting",
        }
        assert expected.issubset(tables)

    def test_management_schema_constraints_exist(
        self, db_manager: DatabaseManager
    ) -> None:
        """管理表应包含关键外键、唯一约束和复合索引"""
        inspector = inspect(db_manager.engine)

        assert "uq_tag_normalized_name" in {
            constraint["name"]
            for constraint in inspector.get_unique_constraints("tag")
        }
        assert {
            tuple(foreign_key["constrained_columns"])
            for foreign_key in inspector.get_foreign_keys("task_event")
        } == {("task_id",)}
        assert {
            index["name"] for index in inspector.get_indexes("operation_task")
        } >= {
            "ix_operation_task_status_created",
            "ix_operation_task_manga_created",
        }

    def test_database_backup_uses_consistent_sqlite_copy(self, tmp_path) -> None:
        """迁移前备份应可被 SQLite 正常打开并读取。"""
        db = DatabaseManager(db_path=str(tmp_path / "data"))
        db.init_db()
        backup_path = tmp_path / "backup" / "main.db.bak"
        backup_database(db.engine, str(backup_path))
        db.close()

        assert backup_path.exists()
        with backup_path.open("rb") as backup_file:
            assert backup_file.read(16) == b"SQLite format 3\x00"

    def test_session_can_write(self, db_manager: DatabaseManager) -> None:
        """会话应能执行插入操作"""
        from src.database.models import Setting

        session = db_manager.get_session()
        try:
            session.add(Setting(key="test", value="ok"))
            session.commit()
            assert session.get(Setting, "test").value == "ok"
        finally:
            session.close()

    def test_db_file_created(self, tmp_path) -> None:
        """数据库文件路径应指向 data 目录下的 main.db"""
        db = DatabaseManager(db_path=str(tmp_path / "data"))
        db.init_db()
        assert (tmp_path / "data" / "main.db").exists()
        db.close()

    def test_close_is_idempotent(self, db_manager: DatabaseManager) -> None:
        """close 调用两次不应抛出异常"""
        db_manager.close()
        db_manager.close()

    def test_sqlite_reliability_pragmas_are_enabled(
        self, db_manager: DatabaseManager
    ) -> None:
        """每个连接都应启用外键、WAL、忙等待和合理同步级别"""
        with db_manager.get_session() as session:
            values = {
                name: session.execute(text(f"PRAGMA {name}")).scalar()
                for name in (
                    "foreign_keys",
                    "journal_mode",
                    "busy_timeout",
                    "synchronous",
                )
            }

        assert values == {
            "foreign_keys": 1,
            "journal_mode": "wal",
            "busy_timeout": 5000,
            "synchronous": 1,
        }

    def test_schema_version_is_recorded(self, db_manager: DatabaseManager) -> None:
        """初始化数据库时应记录当前 schema 版本"""
        with db_manager.get_session() as session:
            alembic_version = session.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar()
            version = session.execute(
                text("SELECT MAX(version) FROM schema_version")
            ).scalar()

        assert alembic_version == "0013_add_management_query_indexes"
        assert version == 1

    def test_unknown_schema_version_is_rejected(self, tmp_path) -> None:
        """数据库版本高于代码支持范围时必须停止初始化"""
        db = DatabaseManager(db_path=str(tmp_path / "data"))
        db.init_db()
        db.close()

        with db.engine.begin() as connection:
            connection.execute(text("DELETE FROM schema_version"))
            connection.execute(
                text(
                    "INSERT INTO schema_version(version, applied_at) "
                    "VALUES (999, CURRENT_TIMESTAMP)"
                )
            )

        try:
            with pytest.raises(RuntimeError, match="高于当前代码支持的版本"):
                db.init_db()
        finally:
            db.close()

    def test_init_db_is_idempotent_with_alembic(self, tmp_path) -> None:
        """重复初始化同一个数据库不应重复应用迁移。"""
        db = DatabaseManager(db_path=str(tmp_path / "data"))
        try:
            db.init_db()
            db.init_db()

            with db.get_session() as session:
                versions = session.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalars().all()

            assert versions == ["0013_add_management_query_indexes"]
        finally:
            db.close()

    def test_management_query_indexes_exist(self, db_manager: DatabaseManager) -> None:
        """管理列表的筛选和稳定排序应有对应索引。"""
        inspector = inspect(db_manager.engine)
        expected = {
            "operation_task": {
                "ix_operation_task_type_status_created",
                "ix_operation_task_source_created",
            },
            "audit_event": {"ix_audit_event_source_created"},
            "reading_progress": {"ix_reading_progress_updated"},
            "user_info": {"ix_user_info_last_seen"},
            "group_info": {"ix_group_info_last_seen"},
        }
        for table_name, index_names in expected.items():
            actual = {index["name"] for index in inspector.get_indexes(table_name)}
            assert index_names <= actual
