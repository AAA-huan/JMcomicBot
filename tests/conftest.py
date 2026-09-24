"""pytest 共享夹具：提供内存SQLite数据库与各仓储实例"""

import pytest

from src.database.database import DatabaseManager
from src.database.repositories import (
    MangaRepository,
    MangaTagRepository,
    PermissionRepository,
    SettingRepository,
    TaskLogRepository,
    UserGroupRepository,
)


@pytest.fixture()
def db_manager(tmp_path) -> DatabaseManager:
    """创建基于临时目录的 SQLite 数据库管理器，测试结束后自动关闭"""
    db = DatabaseManager(db_path=str(tmp_path / "data"), echo=False)
    db.init_db()
    yield db
    db.close()


@pytest.fixture()
def manga_repo(db_manager: DatabaseManager) -> MangaRepository:
    """漫画元数据仓储实例"""
    return MangaRepository(db_manager)


@pytest.fixture()
def tag_repo(db_manager: DatabaseManager) -> MangaTagRepository:
    """漫画标签仓储实例"""
    return MangaTagRepository(db_manager)


@pytest.fixture()
def task_log_repo(db_manager: DatabaseManager) -> TaskLogRepository:
    """任务日志仓储实例"""
    return TaskLogRepository(db_manager)


@pytest.fixture()
def user_group_repo(db_manager: DatabaseManager) -> UserGroupRepository:
    """用户/群组信息仓储实例"""
    return UserGroupRepository(db_manager)


@pytest.fixture()
def permission_repo(db_manager: DatabaseManager) -> PermissionRepository:
    """权限名单仓储实例"""
    return PermissionRepository(db_manager)


@pytest.fixture()
def setting_repo(db_manager: DatabaseManager) -> SettingRepository:
    """运行时配置仓储实例"""
    return SettingRepository(db_manager)
