"""数据库管理器初始化与表结构创建测试"""

from sqlalchemy import inspect

from src.database.database import DatabaseManager


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
