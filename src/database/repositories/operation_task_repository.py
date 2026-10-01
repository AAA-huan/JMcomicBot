"""持久化操作任务与任务事件仓储。"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import uuid4

import json

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import selectinload

from src.database.models import OperationTask, TaskEvent, utc_now
from src.database.repositories._base import BaseRepository

_TASK_TYPES = {"download", "scan", "repair", "delete", "backup", "verify"}
_TASK_SOURCES = {"qq", "web", "system"}
_TASK_STATUSES = {
    "queued",
    "running",
    "succeeded",
    "failed",
    "cancelled",
    "interrupted",
}
_TASK_STATUS_TRANSITIONS = {
    "queued": {"running", "cancelled"},
    "running": {"running", "succeeded", "failed", "interrupted"},
    "succeeded": set(),
    "failed": set(),
    "cancelled": set(),
    "interrupted": set(),
}
_TASK_EVENT_METADATA_KEYS = {
    "cleaned_count",
    "corrupted_count",
    "duration_ms",
    "failed_count",
    "file_count",
    "missing_count",
    "new_count",
    "page_count",
    "retry_count",
    "succeeded_count",
    "updated_count",
}
_TASK_SUMMARIES = {
    "download": "下载漫画",
    "scan": "扫描漫画目录",
    "repair": "修复漫画资料",
    "delete": "删除漫画",
    "backup": "备份数据库",
    "verify": "校验漫画文件",
}


def serialize_metadata(
    metadata: Optional[Dict[str, Any]], allowed_keys: set[str]
) -> Optional[str]:
    """仅序列化白名单元数据字段。"""
    if metadata is None:
        return None
    unexpected = set(metadata) - allowed_keys
    if unexpected:
        raise ValueError(f"元数据包含未允许字段: {sorted(unexpected)}")
    return json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))


class OperationTaskRepository(BaseRepository):
    """操作任务仓储。"""

    def get(self, task_id: str) -> Optional[OperationTask]:
        with self._get_session() as session:
            statement = (
                select(OperationTask)
                .where(OperationTask.id == task_id)
                .options(selectinload(OperationTask.events))
            )
            return session.scalar(statement)

    def list(self, page: int = 1, page_size: int = 50) -> List[OperationTask]:
        with self._get_session() as session:
            statement = (
                select(OperationTask)
                .order_by(OperationTask.created_at.desc(), OperationTask.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            return list(session.scalars(statement).all())

    def search(
        self,
        page: int,
        page_size: int,
        task_type: Optional[str] = None,
        status: Optional[str] = None,
        manga_id: Optional[str] = None,
    ) -> tuple[List[OperationTask], int]:
        """按受控字段分页查询操作任务并返回总数。"""
        if task_type is not None and task_type not in _TASK_TYPES:
            raise ValueError(f"不支持的任务类型: {task_type}")
        if status is not None and status not in _TASK_STATUSES:
            raise ValueError(f"不支持的任务状态: {status}")
        statement = select(OperationTask)
        if task_type is not None:
            statement = statement.where(OperationTask.task_type == task_type)
        if status is not None:
            statement = statement.where(OperationTask.status == status)
        if manga_id is not None:
            statement = statement.where(OperationTask.manga_id == manga_id)
        with self._get_session() as session:
            total = session.scalar(
                select(func.count()).select_from(statement.subquery())
            )
            paged = (
                statement.order_by(OperationTask.created_at.desc(), OperationTask.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            return list(session.scalars(paged).all()), int(total or 0)

    def create(
        self,
        task_type: str,
        source: str,
        requested_by: str = "",
        manga_id: Optional[str] = None,
    ) -> OperationTask:
        """创建排队中的任务。"""
        if task_type not in _TASK_TYPES:
            raise ValueError(f"不支持的任务类型: {task_type}")
        if source not in _TASK_SOURCES:
            raise ValueError(f"不支持的任务来源: {source}")
        now = utc_now()
        summary = _TASK_SUMMARIES[task_type]
        if manga_id is not None and task_type in {"download", "delete"}:
            summary = f"{summary} {manga_id}"
        task = OperationTask(
            id=str(uuid4()),
            task_type=task_type,
            source=source,
            status="queued",
            stage="queued",
            progress=None,
            manga_id=manga_id,
            requested_by=requested_by,
            summary=summary,
            created_at=now,
            updated_at=now,
        )
        with self._get_session() as session:
            session.add(task)
            session.commit()
            session.refresh(task)
            return task

    def find_active_download(self, manga_id: str) -> Optional[OperationTask]:
        """查找同漫画尚未结束的下载任务。"""
        with self._get_session() as session:
            statement = (
                select(OperationTask)
                .where(
                    OperationTask.task_type == "download",
                    OperationTask.manga_id == manga_id,
                    OperationTask.status.in_(("queued", "running")),
                )
                .order_by(OperationTask.created_at, OperationTask.id)
                .limit(1)
            )
            return session.scalar(statement)

    def list_active_downloads(self) -> List[OperationTask]:
        """列出全部尚未结束的下载任务（queued/running），按创建时间排序。"""
        with self._get_session() as session:
            statement = (
                select(OperationTask)
                .where(
                    OperationTask.task_type == "download",
                    OperationTask.status.in_(("queued", "running")),
                )
                .order_by(OperationTask.created_at, OperationTask.id)
            )
            return list(session.scalars(statement).all())

    def update_state(
        self,
        task_id: str,
        status: str,
        stage: str,
        progress: Optional[int] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> OperationTask:
        """更新任务状态；任务不存在或字段非法时明确报错。"""
        if status not in _TASK_STATUSES:
            raise ValueError(f"不支持的任务状态: {status}")
        if progress is not None and not 0 <= progress <= 100:
            raise ValueError("任务进度必须位于 0 到 100 之间")
        now = utc_now()
        with self._get_session() as session:
            task = session.get(OperationTask, task_id)
            if task is None:
                raise ValueError(f"任务不存在: {task_id}")
            if status not in _TASK_STATUS_TRANSITIONS[task.status]:
                raise ValueError(f"不允许任务状态从 {task.status} 转换为 {status}")
            task.status = status
            task.stage = stage
            task.progress = progress
            task.error_code = error_code
            task.error_message = error_message
            task.updated_at = now
            if status == "running" and task.started_at is None:
                task.started_at = now
                task.attempt_count += 1
            if status in {"succeeded", "failed", "cancelled", "interrupted"}:
                task.finished_at = now
            session.commit()
            session.refresh(task)
            return task

    def interrupt_running(self) -> int:
        """将启动时遗留的运行中任务统一标记为中断。"""
        now = utc_now()
        with self._get_session() as session:
            result = session.execute(
                update(OperationTask)
                .where(OperationTask.status == "running")
                .values(status="interrupted", updated_at=now, finished_at=now)
            )
            session.commit()
            return result.rowcount or 0

    @staticmethod
    def _expired_condition(now: datetime, retention_days: int):
        """构造终态且超过保留期的任务过滤条件。"""
        cutoff = now - timedelta(days=retention_days)
        terminal_statuses = {"succeeded", "failed", "cancelled", "interrupted"}
        return (
            OperationTask.status.in_(terminal_statuses),
            OperationTask.finished_at < cutoff,
        )

    def count_expired(self, now: datetime, retention_days: int) -> int:
        """统计达到保留期且处于终态的任务数量。

        Args:
            now: 当前时间
            retention_days: 保留天数

        Returns:
            int: 待清理的任务数量
        """
        with self._get_session() as session:
            return int(
                session.scalar(
                    select(func.count())  # pylint: disable=not-callable
                    .select_from(OperationTask)
                    .where(*self._expired_condition(now, retention_days))
                )
                or 0
            )

    def delete_expired(
        self, now: datetime, retention_days: int, batch_size: int = 200
    ) -> int:
        """分批删除已完成超过保留期且处于终态的任务，级联删除任务事件。

        queued/running 任务永不清理；interrupted 按失败任务处理。

        Args:
            now: 当前时间
            retention_days: 保留天数
            batch_size: 每批删除的任务数量，必须大于 0

        Returns:
            int: 删除的任务数量
        """
        if batch_size <= 0:
            raise ValueError("清理批次大小必须大于 0")
        removed_total = 0
        while True:
            with self._get_session() as session:
                task_ids = session.scalars(
                    select(OperationTask.id)
                    .where(*self._expired_condition(now, retention_days))
                    .limit(batch_size)
                ).all()
                if not task_ids:
                    return removed_total
                result = session.execute(
                    delete(OperationTask).where(OperationTask.id.in_(task_ids))
                )
                session.commit()
                removed_total += result.rowcount or 0


class TaskEventRepository(BaseRepository):
    """任务事件仓储。"""

    def get(self, event_id: int) -> Optional[TaskEvent]:
        with self._get_session() as session:
            return session.get(TaskEvent, event_id)

    def list(
        self, task_id: str, page: int = 1, page_size: int = 100
    ) -> List[TaskEvent]:
        with self._get_session() as session:
            statement = (
                select(TaskEvent)
                .where(TaskEvent.task_id == task_id)
                .order_by(TaskEvent.created_at, TaskEvent.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            return list(session.scalars(statement).all())

    def append(
        self,
        task_id: str,
        event_type: str,
        stage: str,
        progress: Optional[int] = None,
        message: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TaskEvent:
        """追加一条使用白名单元数据的任务事件。"""
        if progress is not None and not 0 <= progress <= 100:
            raise ValueError("任务事件进度必须位于 0 到 100 之间")
        event = TaskEvent(
            task_id=task_id,
            event_type=event_type,
            stage=stage,
            progress=progress,
            message=message,
            metadata_json=serialize_metadata(metadata, _TASK_EVENT_METADATA_KEYS),
        )
        with self._get_session() as session:
            if session.get(OperationTask, task_id) is None:
                raise ValueError(f"任务不存在，无法追加事件: {task_id}")
            session.add(event)
            session.commit()
            session.refresh(event)
            return event
