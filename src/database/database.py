"""数据库管理器，负责 SQLite 引擎创建、会话管理与建表初始化"""

from typing import Any

import os

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from src.database.models import Base
from src.database.migrations import ensure_schema_version
from src.logging.logger_config import logger


@event.listens_for(Engine, "connect")
def _set_sqlite_pragma(dbapi_connection, _connection_record) -> None:
    """SQLite 连接建立时启用外键、WAL 和并发写入配置"""
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA synchronous=NORMAL")
    finally:
        cursor.close()


class DatabaseManager:
    """SQLite 数据库管理器，负责引擎创建、建表与会话管理

    使用场景：启动时创建引擎并执行建表，运行时通过 session_factory 获取会话，
    供各仓储层读写数据。数据库文件位置由配置项 DB_PATH 决定。
    """

    def __init__(
        self,
        db_path: str = "./data",
        echo: bool = False,
        logger_instance: Any = None,
    ) -> None:
        """
        初始化数据库管理器

        Args:
            db_path: 数据库文件所在目录，默认为 ./data
            echo: 是否输出 SQL 日志，排障时使用
            logger_instance: 日志记录器实例
        """
        self.logger = logger_instance or logger
        self.db_dir = os.path.abspath(os.path.expanduser(db_path))
        self.db_file = os.path.join(self.db_dir, "main.db")

        os.makedirs(self.db_dir, exist_ok=True)

        connect_args: dict = {"check_same_thread": False}
        self.engine: Engine = create_engine(
            f"sqlite:///{self.db_file}",
            echo=echo,
            connect_args=connect_args,
        )

        self.session_factory = sessionmaker(
            bind=self.engine,
            autoflush=False,
            expire_on_commit=False,
        )

    def init_db(self) -> None:
        """创建数据库目录并初始化所有表结构"""
        os.makedirs(self.db_dir, exist_ok=True)
        Base.metadata.create_all(self.engine)
        ensure_schema_version(self.engine)
        self.logger.info(f"SQLite数据库初始化完成: {self.db_file}")

    def get_session(self) -> Session:
        """
        获取一个新的数据库会话

        Returns:
            Session: SQLAlchemy 会话实例
        """
        return self.session_factory()

    def close(self) -> None:
        """释放数据库引擎连接池资源"""
        self.engine.dispose()

    def __enter__(self) -> "DatabaseManager":
        self.init_db()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()
