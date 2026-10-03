"""扫描、修复和校验任务的统计记录仓储。"""

# 各仓储按资源定义查询参数，不要求抽象入口的可变参数签名。
# pylint: disable=arguments-differ

from datetime import datetime
from typing import List, Optional

import os

from sqlalchemy import select

from src.database.models import ScanRecord, utc_now

from ._base import BaseRepository

_MAINTENANCE_TASK_TYPES = {"scan", "repair", "verify"}


class ScanRecordRepository(BaseRepository):
    """维护任务统计记录仓储，供 WebUI 维护页查询。"""

    def get(self, record_id: int) -> Optional[ScanRecord]:
        """按主键查询统计记录。"""
        with self._get_session() as session:
            return session.get(ScanRecord, record_id)

    def list(
        self,
        page: int = 1,
        page_size: int = 50,
        task_type: Optional[str] = None,
    ) -> List[ScanRecord]:
        """按时间倒序分页查询维护记录，可按任务类型过滤。"""
        if task_type is not None and task_type not in _MAINTENANCE_TASK_TYPES:
            raise ValueError(f"不支持的维护任务类型: {task_type}")
        statement = select(ScanRecord)
        if task_type is not None:
            statement = statement.where(ScanRecord.task_type == task_type)
        with self._get_session() as session:
            paged = (
                statement.order_by(ScanRecord.created_at.desc(), ScanRecord.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            return list(session.scalars(paged).all())

    def list_by_task(self, task_id: str) -> List[ScanRecord]:
        """查询指定任务的统计记录，按创建顺序返回。"""
        with self._get_session() as session:
            statement = (
                select(ScanRecord)
                .where(ScanRecord.task_id == task_id)
                .order_by(ScanRecord.created_at, ScanRecord.id)
            )
            return list(session.scalars(statement).all())

    def create(  # pylint: disable=too-many-arguments
        self,
        task_id: str,
        task_type: str,
        path_label: str,
        file_count: int = 0,
        new_count: int = 0,
        updated_count: int = 0,
        missing_count: int = 0,
        repaired_count: int = 0,
        corrupted_count: int = 0,
        error_count: int = 0,
        created_at: Optional[datetime] = None,
    ) -> ScanRecord:
        """写入一条维护任务统计记录。

        path_label 只允许配置名称或安全摘要，绝不保存绝对路径。
        """
        if task_type not in _MAINTENANCE_TASK_TYPES:
            raise ValueError(f"不支持的维护任务类型: {task_type}")
        if not path_label:
            raise ValueError("路径标识不能为空")
        if os.path.isabs(path_label) or "/" in path_label or "\\" in path_label:
            raise ValueError("路径标识不能是路径，只允许配置名称或安全摘要")
        counts = (
            ("file_count", file_count),
            ("new_count", new_count),
            ("updated_count", updated_count),
            ("missing_count", missing_count),
            ("repaired_count", repaired_count),
            ("corrupted_count", corrupted_count),
            ("error_count", error_count),
        )
        for name, value in counts:
            if value < 0:
                raise ValueError(f"统计字段 {name} 不能为负数: {value}")

        record = ScanRecord(
            task_id=task_id,
            task_type=task_type,
            path_label=path_label,
            file_count=file_count,
            new_count=new_count,
            updated_count=updated_count,
            missing_count=missing_count,
            repaired_count=repaired_count,
            corrupted_count=corrupted_count,
            error_count=error_count,
            created_at=created_at or utc_now(),
        )
        with self._get_session() as session:
            session.add(record)
            session.commit()
            session.refresh(record)
            return record
