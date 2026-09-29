"""WebUI 单管理员和登录会话仓储。"""

# pylint: disable=arguments-differ

from datetime import datetime
from typing import List, Optional

from sqlalchemy import delete, select

from src.database.models import WebAdmin, WebSession, utc_now
from src.database.repositories._base import BaseRepository


class WebAdminRepository(BaseRepository):
    """维护固定 ID 为 1 的单管理员记录。"""

    def get(self, admin_id: int = 1) -> Optional[WebAdmin]:
        with self._get_session() as session:
            return session.get(WebAdmin, admin_id)

    def list(self) -> List[WebAdmin]:
        with self._get_session() as session:
            return list(session.scalars(select(WebAdmin)).all())

    def create(self, password_hash: str) -> WebAdmin:
        """首次创建管理员；已有管理员时明确拒绝。"""
        now = utc_now()
        with self._get_session() as session:
            if session.get(WebAdmin, 1) is not None:
                raise ValueError("WebUI 管理员已经初始化")
            admin = WebAdmin(
                id=1,
                password_hash=password_hash,
                password_version=1,
                created_at=now,
                updated_at=now,
            )
            session.add(admin)
            session.commit()
            session.refresh(admin)
            return admin

    def record_login(self, admin_id: int = 1) -> WebAdmin:
        """记录管理员最近一次成功登录时间。"""
        now = utc_now()
        with self._get_session() as session:
            admin = session.get(WebAdmin, admin_id)
            if admin is None:
                raise ValueError("WebUI 管理员尚未初始化")
            admin.last_login_at = now
            admin.updated_at = now
            session.commit()
            session.refresh(admin)
            return admin

    def change_password(self, password_hash: str, admin_id: int = 1) -> WebAdmin:
        """更新密码并递增版本，使全部旧会话立即失效。"""
        with self._get_session() as session:
            admin = session.get(WebAdmin, admin_id)
            if admin is None:
                raise ValueError("WebUI 管理员尚未初始化")
            admin.password_hash = password_hash
            admin.password_version += 1
            admin.updated_at = utc_now()
            session.commit()
            session.refresh(admin)
            return admin


class WebSessionRepository(BaseRepository):
    """登录会话仓储，仅接收和查询令牌摘要。"""

    def get(self, session_id: str) -> Optional[WebSession]:
        with self._get_session() as session:
            return session.get(WebSession, session_id)

    def get_by_token_hash(self, token_hash: str) -> Optional[WebSession]:
        """按令牌摘要查询会话。"""
        with self._get_session() as session:
            return session.scalar(
                select(WebSession).where(WebSession.token_hash == token_hash)
            )

    def list(self) -> List[WebSession]:
        with self._get_session() as session:
            statement = select(WebSession).order_by(WebSession.created_at.desc())
            return list(session.scalars(statement).all())

    def create(
        self,
        session_id: str,
        token_hash: str,
        admin_id: int,
        password_version: int,
        expires_at: datetime,
    ) -> WebSession:
        """创建仅持久化令牌摘要的新会话。"""
        now = utc_now()
        web_session = WebSession(
            id=session_id,
            token_hash=token_hash,
            admin_id=admin_id,
            password_version=password_version,
            created_at=now,
            expires_at=expires_at,
            last_seen_at=now,
        )
        with self._get_session() as session:
            session.add(web_session)
            session.commit()
            session.refresh(web_session)
            return web_session

    def touch(self, session_id: str, seen_at: datetime) -> WebSession:
        """更新有效会话的最近访问时间。"""
        with self._get_session() as session:
            web_session = session.get(WebSession, session_id)
            if web_session is None:
                raise ValueError("WebUI 会话不存在")
            web_session.last_seen_at = seen_at
            session.commit()
            session.refresh(web_session)
            return web_session

    def delete(self, session_id: str) -> bool:
        """删除指定会话并返回是否实际删除。"""
        with self._get_session() as session:
            web_session = session.get(WebSession, session_id)
            if web_session is None:
                return False
            session.delete(web_session)
            session.commit()
            return True

    def delete_all(self, admin_id: int = 1) -> int:
        """删除管理员的全部会话。"""
        with self._get_session() as session:
            result = session.execute(
                delete(WebSession).where(WebSession.admin_id == admin_id)
            )
            session.commit()
            return result.rowcount or 0

    def delete_expired(self, now: datetime) -> int:
        """清理截至指定时间已经过期的会话。"""
        with self._get_session() as session:
            result = session.execute(
                delete(WebSession).where(WebSession.expires_at <= now)
            )
            session.commit()
            return result.rowcount or 0
