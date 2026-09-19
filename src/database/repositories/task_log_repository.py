"""任务日志仓储，负责下载/发送/删除等任务历史记录的读写"""

# pylint: disable=arguments-differ, too-many-positional-arguments

from typing import List, Optional

from sqlalchemy import func, select

from src.database.database import DatabaseManager
from src.database.models import TaskLog
from src.database.repositories._base import BaseRepository


class TaskLogRepository(BaseRepository):
    """任务日志仓储，提供任务历史记录的写入与查询"""

    def __init__(self, db_manager: DatabaseManager) -> None:
        super().__init__(db_manager)

    def get(self, log_id: int) -> Optional[TaskLog]:
        """按ID查询任务日志"""
        with self._get_session() as session:
            return session.get(TaskLog, log_id)

    def list(
        self,
        task_type: Optional[str] = None,
        manga_id: Optional[str] = None,
        user_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[TaskLog]:
        """按条件查询任务日志，按创建时间倒序

        Args:
            task_type: 任务类型过滤
            manga_id: 漫画ID过滤
            user_id: 用户ID过滤
            limit: 最大返回数量

        Returns:
            List[TaskLog]: 任务日志列表
        """
        with self._get_session() as session:
            stmt = select(TaskLog)
            if task_type:
                stmt = stmt.where(TaskLog.task_type == task_type)
            if manga_id:
                stmt = stmt.where(TaskLog.manga_id == manga_id)
            if user_id:
                stmt = stmt.where(TaskLog.user_id == user_id)
            stmt = stmt.order_by(TaskLog.created_at.desc()).limit(limit)
            return list(session.scalars(stmt).all())

    def count(
        self, task_type: Optional[str] = None, status: Optional[str] = None
    ) -> int:
        """统计任务日志数量

        Args:
            task_type: 任务类型过滤
            status: 任务状态过滤

        Returns:
            int: 记录数量
        """
        with self._get_session() as session:
            stmt = select(func.count(TaskLog.id))  # pylint: disable=not-callable
            if task_type:
                stmt = stmt.where(TaskLog.task_type == task_type)
            if status:
                stmt = stmt.where(TaskLog.status == status)
            return int(session.scalar(stmt) or 0)

    def add(  # pylint: disable=too-many-arguments
        self,
        task_type: str,
        status: str,
        manga_id: str = "",
        user_id: str = "",
        group_id: str = "",
        private: bool = True,
        message: str = "",
    ) -> TaskLog:
        """写入一条任务日志

        Args:
            task_type: 任务类型(download/send/delete)
            status: 任务状态(success/failed)
            manga_id: 漫画ID
            user_id: 用户ID
            group_id: 群组ID
            private: 是否为私聊
            message: 任务结果信息

        Returns:
            TaskLog: 已保存的任务日志
        """
        with self._get_session() as session:
            log = TaskLog(
                task_type=task_type,
                status=status,
                manga_id=manga_id,
                user_id=user_id,
                group_id=group_id,
                private=private,
                message=message,
            )
            session.add(log)
            session.commit()
            session.refresh(log)
            return log
