"""用户/群组信息仓储，负责昵称与群名缓存的持久化读写"""

# pylint: disable=arguments-differ

from typing import List, Optional

from sqlalchemy import select

from src.database.database import DatabaseManager
from src.database.models import GroupInfo, UserInfo
from src.database.repositories._base import BaseRepository


class UserGroupRepository(BaseRepository):
    """用户/群组信息仓储，提供昵称与群名的读写"""

    def __init__(self, db_manager: DatabaseManager) -> None:
        super().__init__(db_manager)

    def get(self, record_id: str) -> Optional[UserInfo]:
        """按ID查询用户/群组记录（兼容抽象基类接口）"""
        with self._get_session() as session:
            user = session.get(UserInfo, record_id)
            if user is not None:
                return user
            return session.get(GroupInfo, record_id)

    def list(self) -> list:
        """查询全部用户与群组记录（兼容抽象基类接口）"""
        with self._get_session() as session:
            users = session.scalars(
                select(UserInfo).order_by(UserInfo.last_seen_at)
            ).all()
            groups = session.scalars(
                select(GroupInfo).order_by(GroupInfo.last_seen_at)
            ).all()
            return list(users) + list(groups)

    def list_users(self, limit: int = 200) -> List[UserInfo]:
        """按最近活跃时间倒序查询用户昵称缓存"""
        if limit < 1:
            raise ValueError("查询数量必须大于 0")
        with self._get_session() as session:
            statement = (
                select(UserInfo)
                .order_by(UserInfo.last_seen_at.desc(), UserInfo.id)
                .limit(limit)
            )
            return list(session.scalars(statement).all())

    def list_groups(self, limit: int = 200) -> List[GroupInfo]:
        """按最近活跃时间倒序查询群组名称缓存"""
        if limit < 1:
            raise ValueError("查询数量必须大于 0")
        with self._get_session() as session:
            statement = (
                select(GroupInfo)
                .order_by(GroupInfo.last_seen_at.desc(), GroupInfo.id)
                .limit(limit)
            )
            return list(session.scalars(statement).all())

    def get_user(self, user_id: str) -> Optional[UserInfo]:
        """按用户ID查询用户昵称记录"""
        with self._get_session() as session:
            return session.get(UserInfo, user_id)

    def get_group(self, group_id: str) -> Optional[GroupInfo]:
        """按群组ID查询群名称记录"""
        with self._get_session() as session:
            return session.get(GroupInfo, group_id)

    def upsert_user(self, user_id: str, nickname: str) -> UserInfo:
        """插入或更新用户昵称缓存

        Args:
            user_id: 用户QQ号
            nickname: 用户昵称

        Returns:
            UserInfo: 已保存的用户记录
        """
        with self._get_session() as session:
            user = session.get(UserInfo, user_id)
            if user is None:
                user = UserInfo(id=user_id)
                session.add(user)
            if nickname:
                user.nickname = nickname
            session.commit()
            session.refresh(user)
            return user

    def upsert_group(self, group_id: str, group_name: str) -> GroupInfo:
        """插入或更新群名称缓存

        Args:
            group_id: 群组ID
            group_name: 群名称

        Returns:
            GroupInfo: 已保存的群组记录
        """
        with self._get_session() as session:
            group = session.get(GroupInfo, group_id)
            if group is None:
                group = GroupInfo(id=group_id)
                session.add(group)
            if group_name:
                group.group_name = group_name
            session.commit()
            session.refresh(group)
            return group
