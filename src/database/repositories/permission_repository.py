"""权限仓储，负责群白名单/私聊白名单/全局黑名单/删除权限用户名单的读写"""

# pylint: disable=arguments-differ

from typing import Dict, List, Optional

from sqlalchemy import delete, select

from src.database.database import DatabaseManager
from src.database.models import Permission
from src.database.repositories._base import BaseRepository


class PermissionRepository(BaseRepository):
    """权限名单仓储，提供四类名单(scope)的增删改查与批量导入"""

    def __init__(self, db_manager: DatabaseManager) -> None:
        super().__init__(db_manager)

    def get(self, permission_id: int) -> Optional[Permission]:
        """按记录ID查询单条权限记录"""
        with self._get_session() as session:
            return session.get(Permission, permission_id)

    def list(self) -> List[Permission]:
        """查询全部权限记录"""
        with self._get_session() as session:
            stmt = select(Permission).order_by(Permission.scope, Permission.value)
            return list(session.scalars(stmt).all())

    def list_values(self, scope: str) -> List[str]:
        """查询指定名单(scope)下的全部ID值

        Args:
            scope: 名单类型，如 group_whitelist

        Returns:
            List[str]: 名单中的ID列表
        """
        with self._get_session() as session:
            stmt = select(Permission.value).where(Permission.scope == scope)
            return list(session.scalars(stmt).all())

    def get_all_scopes(self) -> Dict[str, List[str]]:
        """查询全部名单类型与其包含的ID值

        Returns:
            Dict[str, List[str]]: 名单类型到ID列表的映射
        """
        with self._get_session() as session:
            scopes: Dict[str, List[str]] = {}
            for permission in session.scalars(select(Permission)).all():
                scopes.setdefault(permission.scope, []).append(permission.value)
            return scopes

    def add(self, scope: str, value: str, remark: str = "") -> bool:
        """向指定名单添加一个ID，已存在时忽略

        Args:
            scope: 名单类型
            value: 名单内ID
            remark: 备注

        Returns:
            bool: 是否为新插入
        """
        with self._get_session() as session:
            if self._exists(session, scope, value):
                return False
            session.add(Permission(scope=scope, value=value, remark=remark))
            session.commit()
            return True

    def remove(self, scope: str, value: str) -> bool:
        """从指定名单移除一个ID

        Args:
            scope: 名单类型
            value: 名单内ID

        Returns:
            bool: 是否实际删除了记录
        """
        with self._get_session() as session:
            result = session.execute(
                delete(Permission).where(
                    Permission.scope == scope, Permission.value == value
                )
            )
            session.commit()
            return result.rowcount > 0

    def contains(self, scope: str, value: str) -> bool:
        """判断指定名单中是否包含某ID

        Args:
            scope: 名单类型
            value: 名单内ID

        Returns:
            bool: 是否包含
        """
        with self._get_session() as session:
            return self._exists(session, scope, value)

    def replace_scope(self, scope: str, values: List[str], remark: str = "") -> None:
        """整体替换指定名单的内容（用于 .env 种子导入或全量更新）

        Args:
            scope: 名单类型
            values: 名单内ID列表
            remark: 备注
        """
        with self._get_session() as session:
            session.execute(delete(Permission).where(Permission.scope == scope))
            for value in values:
                session.add(Permission(scope=scope, value=value, remark=remark))
            session.commit()

    @staticmethod
    def _exists(session, scope: str, value: str) -> bool:
        return (
            session.scalar(
                select(Permission.id).where(
                    Permission.scope == scope, Permission.value == value
                )
            )
            is not None
        )
