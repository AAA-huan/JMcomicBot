"""WebUI 单管理员认证与安全会话服务。"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from secrets import token_urlsafe
from uuid import uuid4

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from src.database.models import utc_now
from src.database.repositories.web_auth_repository import (
    WebAdminRepository,
    WebSessionRepository,
)

MINIMUM_PASSWORD_LENGTH = 12


@dataclass(frozen=True)
class AuthenticatedSession:
    """认证成功后的渠道无关会话结果。"""

    session_id: str
    admin_id: int
    expires_at: datetime


@dataclass(frozen=True)
class CreatedSession(AuthenticatedSession):
    """新建会话结果，原始令牌仅在创建时返回一次。"""

    token: str


class WebAuthService:
    """提供管理员初始化、登录、会话验证和密码修改。"""

    def __init__(
        self,
        admin_repository: WebAdminRepository,
        session_repository: WebSessionRepository,
        session_hours: int,
        password_hasher: PasswordHasher | None = None,
    ) -> None:
        if session_hours < 1:
            raise ValueError("WebUI 会话时长必须至少为 1 小时")
        self.admin_repository = admin_repository
        self.session_repository = session_repository
        self.session_hours = session_hours
        self.password_hasher = password_hasher or PasswordHasher()

    @staticmethod
    def _token_hash(token: str) -> str:
        return sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _validate_password(password: str) -> None:
        if len(password) < MINIMUM_PASSWORD_LENGTH:
            raise ValueError(f"管理员密码至少需要 {MINIMUM_PASSWORD_LENGTH} 个字符")

    def is_initialized(self) -> bool:
        """返回单管理员是否已经初始化。"""
        return self.admin_repository.get() is not None

    def setup(self, password: str) -> None:
        """创建唯一管理员；调用方负责限制请求来源为回环地址。"""
        self._validate_password(password)
        self.admin_repository.create(self.password_hasher.hash(password))

    def login(self, password: str) -> CreatedSession:
        """校验密码并创建新会话。"""
        admin = self.admin_repository.get()
        if admin is None:
            raise ValueError("WebUI 管理员尚未初始化")
        try:
            verified = self.password_hasher.verify(admin.password_hash, password)
        except (InvalidHashError, VerifyMismatchError) as error:
            raise ValueError("管理员密码错误") from error
        if not verified:
            raise ValueError("管理员密码错误")
        if self.password_hasher.check_needs_rehash(admin.password_hash):
            admin = self.admin_repository.change_password(
                self.password_hasher.hash(password)
            )
            self.session_repository.delete_all(admin.id)
        admin = self.admin_repository.record_login(admin.id)
        token = token_urlsafe(32)
        expires_at = utc_now() + timedelta(hours=self.session_hours)
        web_session = self.session_repository.create(
            session_id=str(uuid4()),
            token_hash=self._token_hash(token),
            admin_id=admin.id,
            password_version=admin.password_version,
            expires_at=expires_at,
        )
        return CreatedSession(
            session_id=web_session.id,
            admin_id=web_session.admin_id,
            expires_at=web_session.expires_at,
            token=token,
        )

    def authenticate(self, token: str) -> AuthenticatedSession | None:
        """验证会话令牌、有效期和密码版本。"""
        now = utc_now()
        web_session = self.session_repository.get_by_token_hash(self._token_hash(token))
        if web_session is None:
            return None
        admin = self.admin_repository.get(web_session.admin_id)
        if (
            admin is None
            or web_session.expires_at <= now
            or web_session.password_version != admin.password_version
        ):
            self.session_repository.delete(web_session.id)
            return None
        self.session_repository.touch(web_session.id, now)
        return AuthenticatedSession(
            session_id=web_session.id,
            admin_id=web_session.admin_id,
            expires_at=web_session.expires_at,
        )

    def logout(self, token: str) -> bool:
        """注销令牌对应的会话。"""
        web_session = self.session_repository.get_by_token_hash(self._token_hash(token))
        return web_session is not None and self.session_repository.delete(
            web_session.id
        )

    def change_password(self, old_password: str, new_password: str) -> None:
        """校验旧密码、更新密码并注销全部既有会话。"""
        self._validate_password(new_password)
        admin = self.admin_repository.get()
        if admin is None:
            raise ValueError("WebUI 管理员尚未初始化")
        try:
            verified = self.password_hasher.verify(admin.password_hash, old_password)
        except (InvalidHashError, VerifyMismatchError) as error:
            raise ValueError("原管理员密码错误") from error
        if not verified:
            raise ValueError("原管理员密码错误")
        self.admin_repository.change_password(self.password_hasher.hash(new_password))
        self.session_repository.delete_all(admin.id)

    def cleanup_expired_sessions(self) -> int:
        """清理全部过期会话。"""
        return self.session_repository.delete_expired(utc_now())
