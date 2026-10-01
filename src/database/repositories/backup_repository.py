"""数据库备份记录仓储。"""

from datetime import datetime
from typing import List, Optional

import os

from sqlalchemy import select

from src.database.models import BackupRecord, utc_now
from src.database.repositories._base import BaseRepository

_BACKUP_STATUSES = {"creating", "ready", "failed", "deleted"}


class BackupRepository(BaseRepository):
    """备份记录仓储；记录长期保留，文件删除只标记 deleted。"""

    def get(self, record_id: int) -> Optional[BackupRecord]:
        """按主键查询备份记录。"""
        with self._get_session() as session:
            return session.get(BackupRecord, record_id)

    def list(
        self,
        page: int = 1,
        page_size: int = 50,
        status: Optional[str] = None,
    ) -> List[BackupRecord]:
        """按创建时间倒序分页查询备份记录，可按状态过滤。"""
        if status is not None and status not in _BACKUP_STATUSES:
            raise ValueError(f"不支持的备份状态: {status}")
        statement = select(BackupRecord)
        if status is not None:
            statement = statement.where(BackupRecord.status == status)
        with self._get_session() as session:
            paged = (
                statement.order_by(BackupRecord.created_at.desc(), BackupRecord.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            return list(session.scalars(paged).all())

    def list_ready_oldest_first(self) -> List[BackupRecord]:
        """按创建时间正序返回全部 ready 备份，供保留清理使用。"""
        with self._get_session() as session:
            statement = (
                select(BackupRecord)
                .where(BackupRecord.status == "ready")
                .order_by(BackupRecord.created_at, BackupRecord.id)
            )
            return list(session.scalars(statement).all())

    def create(
        self,
        filename: str,
        relative_path: str,
        schema_version: str,
        status: str = "creating",
        created_at: Optional[datetime] = None,
    ) -> BackupRecord:
        """登记一条备份记录；relative_path 必须相对 BACKUP_PATH。"""
        if status not in _BACKUP_STATUSES:
            raise ValueError(f"不支持的备份状态: {status}")
        if not filename or not relative_path:
            raise ValueError("备份文件名和相对路径不能为空")
        if os.path.isabs(relative_path):
            raise ValueError("备份相对路径不能是绝对路径")
        now = created_at or utc_now()
        record = BackupRecord(
            filename=filename,
            relative_path=relative_path,
            schema_version=schema_version,
            status=status,
            created_at=now,
            updated_at=now,
        )
        with self._get_session() as session:
            session.add(record)
            session.commit()
            session.refresh(record)
            return record

    def mark_ready(self, record_id: int, file_size_bytes: int, sha256: str) -> bool:
        """备份成功后写入大小与摘要。"""
        return self._update_status(
            record_id, "ready", file_size_bytes=file_size_bytes, sha256=sha256
        )

    def mark_failed(self, record_id: int) -> bool:
        """备份失败后标记 failed，保留记录便于诊断。"""
        with self._get_session() as session:
            record = session.get(BackupRecord, record_id)
            if record is None:
                return False
            record.status = "failed"
            record.updated_at = utc_now()
            session.commit()
            return True

    def mark_deleted(
        self, record_id: int, deleted_at: Optional[datetime] = None
    ) -> bool:
        """备份文件被清理后标记 deleted，保留记录行。"""
        with self._get_session() as session:
            record = session.get(BackupRecord, record_id)
            if record is None:
                return False
            record.status = "deleted"
            record.deleted_at = deleted_at or utc_now()
            record.updated_at = utc_now()
            session.commit()
            return True

    def _update_status(
        self,
        record_id: int,
        status: str,
        file_size_bytes: Optional[int] = None,
        sha256: Optional[str] = None,
    ) -> bool:
        """更新备份状态；仅 ready 迁移时附带大小与摘要。"""
        if status not in _BACKUP_STATUSES:
            raise ValueError(f"不支持的备份状态: {status}")
        with self._get_session() as session:
            record = session.get(BackupRecord, record_id)
            if record is None:
                return False
            record.status = status
            if file_size_bytes is not None:
                record.file_size_bytes = file_size_bytes
            if sha256 is not None:
                record.sha256 = sha256
            record.updated_at = utc_now()
            session.commit()
            return True
