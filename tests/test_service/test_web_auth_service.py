"""WebUI 管理员认证和会话服务测试。"""

from datetime import timedelta

from argon2 import PasswordHasher

from src.database.models import WebSession, utc_now
from src.database.repositories.web_auth_repository import (
    WebAdminRepository,
    WebSessionRepository,
)
from src.service.web_auth_service import WebAuthService


def _create_service(db_manager) -> WebAuthService:
    return WebAuthService(
        WebAdminRepository(db_manager),
        WebSessionRepository(db_manager),
        session_hours=24,
        password_hasher=PasswordHasher(
            time_cost=1,
            memory_cost=8192,
            parallelism=1,
        ),
    )


def test_setup_login_and_logout_store_only_token_hash(db_manager) -> None:
    service = _create_service(db_manager)

    assert service.is_initialized() is False
    service.setup("correct-horse-battery-staple")
    created = service.login("correct-horse-battery-staple")

    assert service.is_initialized() is True
    assert service.authenticate(created.token) is not None
    with db_manager.get_session() as session:
        stored_session = session.get(WebSession, created.session_id)
        assert stored_session is not None
        assert stored_session.token_hash != created.token
        assert created.token not in stored_session.token_hash
    assert service.logout(created.token) is True
    assert service.authenticate(created.token) is None


def test_setup_rejects_duplicate_admin_and_short_password(db_manager) -> None:
    service = _create_service(db_manager)

    try:
        service.setup("short")
    except ValueError as error:
        assert "至少需要" in str(error)
    else:
        raise AssertionError("短密码应被拒绝")

    service.setup("first-secure-password")
    try:
        service.setup("second-secure-password")
    except ValueError as error:
        assert "已经初始化" in str(error)
    else:
        raise AssertionError("重复初始化管理员应被拒绝")


def test_login_rejects_wrong_password(db_manager) -> None:
    service = _create_service(db_manager)
    service.setup("correct-secure-password")

    try:
        service.login("incorrect-password")
    except ValueError as error:
        assert str(error) == "管理员密码错误"
    else:
        raise AssertionError("错误密码不应登录成功")


def test_expired_session_is_deleted(db_manager) -> None:
    service = _create_service(db_manager)
    service.setup("correct-secure-password")
    created = service.login("correct-secure-password")
    with db_manager.get_session() as session:
        stored_session = session.get(WebSession, created.session_id)
        assert stored_session is not None
        stored_session.expires_at = utc_now() - timedelta(seconds=1)
        session.commit()

    assert service.authenticate(created.token) is None
    assert WebSessionRepository(db_manager).get(created.session_id) is None


def test_password_change_invalidates_existing_sessions(db_manager) -> None:
    service = _create_service(db_manager)
    service.setup("old-secure-password")
    created = service.login("old-secure-password")

    service.change_password("old-secure-password", "new-secure-password")

    assert service.authenticate(created.token) is None
    try:
        service.login("old-secure-password")
    except ValueError as error:
        assert str(error) == "管理员密码错误"
    else:
        raise AssertionError("旧密码不应继续登录")
    assert service.login("new-secure-password").token
