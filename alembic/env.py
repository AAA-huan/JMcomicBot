"""Alembic 迁移运行环境。"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, event, pool

from src.database.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """生成不连接数据库的 SQL 迁移脚本。"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def _disable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
    """迁移连接建立时关闭 SQLite 外键强制。

    批量重建表（batch_alter_table）会 DROP 旧表；若外键强制开启，DROP 会触发
    子表的 ON DELETE CASCADE，导致文件记录被静默删除。该监听器只注册在迁移
    专用引擎上，应用连接仍由 DatabaseManager 保持外键开启。
    """
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=OFF")
    finally:
        cursor.close()


def run_migrations_online() -> None:
    """连接数据库并执行迁移。"""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    if connectable.dialect.name == "sqlite":
        event.listen(connectable, "connect", _disable_sqlite_foreign_keys)

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
