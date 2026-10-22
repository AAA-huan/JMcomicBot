"""阅读设置仓储测试：默认值、更新、CHECK 约束与外键级联。"""

from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
import pytest

from src.database.database import DatabaseManager
from src.database.models import WebAdmin
from src.database.repositories import ReadingSettingRepository, WebAdminRepository


def _create_admin(db_manager: DatabaseManager) -> None:
    """创建单管理员记录，满足阅读设置外键。"""
    WebAdminRepository(db_manager).create("password-hash")


def test_reading_setting_insert_and_update(db_manager) -> None:
    """首次 upsert 插入记录，再次 upsert 整体更新。"""
    _create_admin(db_manager)
    repository = ReadingSettingRepository(db_manager)

    assert repository.get(1) is None
    assert repository.exists(1) is False
    created = repository.upsert(
        admin_id=1,
        reading_mode="normal",
        continuous=False,
        click_to_turn=False,
        reverse_click=False,
        dark_background=False,
    )
    assert created.reading_mode == "normal"
    assert created.continuous is False
    assert created.updated_at is not None
    assert repository.exists(1) is True

    updated = repository.upsert(
        admin_id=1,
        reading_mode="manga",
        continuous=True,
        click_to_turn=True,
        reverse_click=True,
        dark_background=True,
    )
    assert updated.admin_id == 1
    assert updated.reading_mode == "manga"
    assert updated.continuous is True
    assert updated.click_to_turn is True
    assert updated.reverse_click is True
    assert updated.dark_background is True


def test_reading_setting_mode_check_constraint(db_manager) -> None:
    """非法阅读模式必须被数据库 CHECK 拒绝。"""
    _create_admin(db_manager)
    repository = ReadingSettingRepository(db_manager)
    with pytest.raises(IntegrityError):
        repository.upsert(
            admin_id=1,
            reading_mode="invalid",
            continuous=False,
            click_to_turn=False,
            reverse_click=False,
            dark_background=False,
        )


def test_reading_setting_cascades_with_admin_delete(db_manager) -> None:
    """删除管理员时数据库级联删除对应阅读设置。"""
    _create_admin(db_manager)
    repository = ReadingSettingRepository(db_manager)
    repository.upsert(
        admin_id=1,
        reading_mode="scroll",
        continuous=True,
        click_to_turn=True,
        reverse_click=False,
        dark_background=True,
    )
    with db_manager.get_session() as session:
        session.execute(delete(WebAdmin).where(WebAdmin.id == 1))
        session.commit()

    assert repository.get(1) is None
