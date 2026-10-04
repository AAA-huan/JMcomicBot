"""SQLAlchemy ORM 模型定义，对应 SQLite 数据库中的各张表"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """所有 ORM 模型的声明式基类"""


def utc_now() -> datetime:
    """返回使用 UTC 语义的无时区时间，兼容 SQLite DATETIME。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Manga(Base):
    """漫画元数据表，记录已下载漫画的标题、作者、标签等信息"""

    __tablename__ = "manga"
    __table_args__ = (
        CheckConstraint(
            "status IN ('downloaded', 'missing_file', 'invalid', 'deleted')",
            name="ck_manga_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, comment="漫画ID")
    source_site: Mapped[str] = mapped_column(
        String(64), default="jmcomic", comment="来源站点"
    )
    title: Mapped[str] = mapped_column(String(255), default="", comment="漫画标题")
    author: Mapped[str] = mapped_column(String(255), default="", comment="漫画作者")
    description: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="简介"
    )
    remote_metadata: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON, nullable=True, comment="站点元数据快照，与本地实际页数和章节数分离"
    )
    chapter_count: Mapped[int] = mapped_column(Integer, default=0, comment="章节数")
    page_count: Mapped[int] = mapped_column(Integer, default=0, comment="总页数")
    status: Mapped[str] = mapped_column(
        String(32), default="downloaded", comment="下载状态"
    )
    metadata_source: Mapped[str] = mapped_column(
        String(64), default="jmcomic", comment="元数据来源"
    )
    downloaded_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, comment="下载完成时间"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    last_verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )

    files: Mapped[List["MangaFile"]] = relationship(
        back_populates="manga",
        cascade="all, delete-orphan",
    )


class MangaFile(Base):
    """漫画PDF文件表，记录漫画对应的一个或多个PDF文件"""

    __tablename__ = "manga_file"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ready', 'missing', 'corrupted', 'deleting', 'deleted', 'invalid_path')",
            name="ck_manga_file_status",
        ),
        UniqueConstraint("manga_id", name="uq_manga_file_manga_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    manga_id: Mapped[str] = mapped_column(
        ForeignKey("manga.id", ondelete="CASCADE"), index=True
    )
    relative_path: Mapped[str] = mapped_column(String(1024), unique=True)
    display_name: Mapped[str] = mapped_column(String(512), default="")
    file_type: Mapped[str] = mapped_column(String(32), default="pdf")
    mime_type: Mapped[str] = mapped_column(String(128), default="application/pdf")
    file_size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="ready")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, comment="记录创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    last_verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    file_mtime: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, comment="文件修改时间，用于识别文件变化"
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    manga: Mapped["Manga"] = relationship(back_populates="files")


class ReadingProgress(Base):
    """PDF 阅读进度表，记录每本 PDF 当前阅读位置；页码从 1 开始。"""

    __tablename__ = "reading_progress"
    __table_args__ = (Index("ix_reading_progress_updated", "updated_at"),)

    manga_file_id: Mapped[int] = mapped_column(
        ForeignKey("manga_file.id", ondelete="CASCADE"),
        primary_key=True,
        comment="PDF文件ID",
    )
    page_number: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, comment="当前页码"
    )
    page_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="PDF总页数"
    )
    percent: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, comment="阅读百分比"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now, comment="更新时间"
    )


class Tag(Base):
    """规范化标签定义表。"""

    __tablename__ = "tag"
    __table_args__ = (
        UniqueConstraint("normalized_name", name="uq_tag_normalized_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class MangaTag(Base):
    """漫画与规范化标签的关系表。"""

    __tablename__ = "manga_tag"
    manga_id: Mapped[str] = mapped_column(
        ForeignKey("manga.id", ondelete="CASCADE"),
        primary_key=True,
        comment="漫画ID",
    )
    tag_id: Mapped[int] = mapped_column(
        ForeignKey("tag.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, comment="记录创建时间"
    )


class MangaFavorite(Base):
    """按归属隔离的漫画收藏，预留 QQ 用户收藏的独立命名空间。"""

    __tablename__ = "manga_favorite"
    __table_args__ = (
        CheckConstraint(
            "owner_type IN ('web_admin', 'qq')", name="ck_favorite_owner_type"
        ),
        CheckConstraint("length(owner_id) > 0", name="ck_favorite_owner_id"),
        Index("ix_manga_favorite_manga_id", "manga_id"),
    )

    owner_type: Mapped[str] = mapped_column(String(16), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    manga_id: Mapped[str] = mapped_column(
        ForeignKey("manga.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now
    )


class JmRemoteFavorite(Base):
    """远端收藏索引，不为尚未下载的漫画创建本地漫画或文件记录。"""

    __tablename__ = "jm_remote_favorite"
    __table_args__ = (
        CheckConstraint("admin_id > 0", name="ck_jm_remote_favorite_admin"),
    )

    # 与本地管理员收藏采用相同归属语义，管理员重置不删除收藏数据。
    admin_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(128), primary_key=True)
    manga_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    folders: Mapped[Dict[str, str]] = mapped_column(JSON, nullable=False)
    pending_local_favorite: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class JmFavoriteImport(Base):
    """收藏导入任务的分页进度，重启后保留已完成结果。"""

    __tablename__ = "jm_favorite_import"
    __table_args__ = (
        CheckConstraint("admin_id > 0", name="ck_jm_favorite_import_admin"),
        CheckConstraint(
            "status IN ('running', 'succeeded', 'failed', 'interrupted')",
            name="ck_jm_favorite_import_status",
        ),
        Index("ix_jm_favorite_import_admin_created", "admin_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    admin_id: Mapped[int] = mapped_column(Integer, nullable=False)
    username: Mapped[str] = mapped_column(String(128), nullable=False)
    folder_ids: Mapped[List[str]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    pages_done: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    imported_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    local_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class WebAdmin(Base):
    """WebUI 单管理员账户，只保存 Argon2 密码哈希。"""

    __tablename__ = "web_admin"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_web_admin_singleton"),
        UniqueConstraint("qq_id", name="uq_web_admin_qq_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    qq_id: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    password_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    sessions: Mapped[list["WebSession"]] = relationship(
        back_populates="admin", cascade="all, delete-orphan"
    )


class WebSession(Base):
    """WebUI 登录会话，数据库仅保存随机令牌的 SHA-256 摘要。"""

    __tablename__ = "web_session"
    __table_args__ = (Index("ix_web_session_expires_at", "expires_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    admin_id: Mapped[int] = mapped_column(
        ForeignKey("web_admin.id", ondelete="CASCADE"), nullable=False
    )
    password_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now
    )

    admin: Mapped["WebAdmin"] = relationship(back_populates="sessions")


class OperationTask(Base):
    """持久化操作任务，记录任务当前状态和执行结果。"""

    __tablename__ = "operation_task"
    __table_args__ = (
        CheckConstraint(
            "task_type IN ('download', 'scan', 'repair', 'delete', 'backup', 'verify')",
            name="ck_operation_task_type",
        ),
        CheckConstraint(
            "source IN ('qq', 'web', 'system')", name="ck_operation_task_source"
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled', 'interrupted')",
            name="ck_operation_task_status",
        ),
        CheckConstraint(
            "progress IS NULL OR (progress >= 0 AND progress <= 100)",
            name="ck_operation_task_progress",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_operation_task_attempt_count"),
        Index("ix_operation_task_status_created", "status", "created_at", "id"),
        Index(
            "ix_operation_task_type_status_created",
            "task_type",
            "status",
            "created_at",
            "id",
        ),
        Index("ix_operation_task_manga_created", "manga_id", "created_at", "id"),
        Index("ix_operation_task_source_created", "source", "created_at", "id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    stage: Mapped[str] = mapped_column(String(64), nullable=False, default="queued")
    progress: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    manga_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    requested_by: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    summary: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    error_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    events: Mapped[list["TaskEvent"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )


class TaskEvent(Base):
    """任务过程事件，用于按顺序恢复任务执行轨迹。"""

    __tablename__ = "task_event"
    __table_args__ = (
        CheckConstraint(
            "progress IS NULL OR (progress >= 0 AND progress <= 100)",
            name="ck_task_event_progress",
        ),
        Index("ix_task_event_task_created", "task_id", "created_at", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("operation_task.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    stage: Mapped[str] = mapped_column(String(64), nullable=False)
    progress: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    message: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    metadata_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now
    )

    task: Mapped["OperationTask"] = relationship(back_populates="events")


class ScanRecord(Base):
    """扫描、修复和校验任务共用的正式统计记录。"""

    __tablename__ = "scan_record"
    __table_args__ = (
        CheckConstraint(
            "task_type IN ('scan', 'repair', 'verify')",
            name="ck_scan_record_task_type",
        ),
        Index("ix_scan_record_task_id", "task_id"),
        Index("ix_scan_record_created", "created_at", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("operation_task.id", ondelete="CASCADE"),
        nullable=False,
        comment="所属任务ID",
    )
    task_type: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="任务类型: scan/repair/verify"
    )
    path_label: Mapped[str] = mapped_column(
        String(128), nullable=False, comment="路径标识，只保存配置名称"
    )
    file_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="扫描文件数"
    )
    new_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="新增数"
    )
    updated_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="更新数"
    )
    missing_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="缺失数"
    )
    repaired_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="修复数"
    )
    corrupted_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="损坏数"
    )
    error_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="错误数"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now, comment="记录时间"
    )


class BackupRecord(Base):
    """数据库备份记录，长期保留行，文件删除后仅标记 deleted。"""

    __tablename__ = "backup_record"
    __table_args__ = (
        CheckConstraint(
            "status IN ('creating', 'ready', 'failed', 'deleted')",
            name="ck_backup_record_status",
        ),
        UniqueConstraint("relative_path", name="uq_backup_record_relative_path"),
        Index("ix_backup_record_status_created", "status", "created_at"),
        Index("ix_backup_record_created", "created_at", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    filename: Mapped[str] = mapped_column(String(512), nullable=False, comment="文件名")
    relative_path: Mapped[str] = mapped_column(
        String(1024), nullable=False, comment="相对 BACKUP_PATH 的路径"
    )
    file_size_bytes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="文件字节数"
    )
    sha256: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, comment="文件SHA-256"
    )
    schema_version: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="备份时 schema 版本"
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="creating/ready/failed/deleted"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now, comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now, comment="更新时间"
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, comment="文件删除时间"
    )


class AuditEvent(Base):
    """重要操作审计事件，不保存原始消息或秘密信息。"""

    __tablename__ = "audit_event"
    __table_args__ = (
        CheckConstraint(
            "source IN ('qq', 'web', 'system')", name="ck_audit_event_source"
        ),
        Index("ix_audit_event_type_created", "event_type", "created_at", "id"),
        Index("ix_audit_event_source_created", "source", "created_at", "id"),
        Index("ix_audit_event_actor_created", "actor_user_id", "created_at", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_user_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    actor_group_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    client_ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    target_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    target_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    result: Mapped[str] = mapped_column(String(32), nullable=False)
    error_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now
    )


class TaskLog(Base):
    """任务日志表，记录下载/发送/删除等任务的执行历史"""

    __tablename__ = "task_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_type: Mapped[str] = mapped_column(String(32), index=True, comment="任务类型")
    status: Mapped[str] = mapped_column(
        String(32), default="pending", comment="任务状态"
    )
    manga_id: Mapped[str] = mapped_column(String(32), default="", comment="漫画ID")
    user_id: Mapped[str] = mapped_column(String(64), default="", comment="用户ID")
    group_id: Mapped[str] = mapped_column(
        String(64), default="", comment="群组ID(私聊为空)"
    )
    private: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否为私聊")
    message: Mapped[str] = mapped_column(Text, default="", comment="任务结果信息")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, index=True, comment="任务创建时间"
    )


class UserInfo(Base):
    """用户信息表，缓存用户昵称以便日志展示与WebUI使用"""

    __tablename__ = "user_info"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, comment="用户QQ号")
    nickname: Mapped[str] = mapped_column(String(255), default="", comment="用户昵称")
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, comment="最近一次活跃时间"
    )


class GroupInfo(Base):
    """群组信息表，缓存群名称以便日志展示与WebUI使用"""

    __tablename__ = "group_info"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, comment="群组ID")
    group_name: Mapped[str] = mapped_column(String(255), default="", comment="群名称")
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, comment="最近一次活跃时间"
    )


class Permission(Base):
    """权限表，存储群白名单/私聊白名单/全局黑名单/删除权限用户名单"""

    __tablename__ = "permission"
    __table_args__ = (
        UniqueConstraint("scope", "value", name="uq_permission_scope_value"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column(String(32), index=True, comment="名单类型")
    value: Mapped[str] = mapped_column(String(64), comment="名单内ID")
    remark: Mapped[str] = mapped_column(String(255), default="", comment="备注")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, comment="记录创建时间"
    )


class Setting(Base):
    """运行时配置表，存储可通过WebUI或命令动态修改的键值配置"""

    __tablename__ = "setting"

    key: Mapped[str] = mapped_column(String(128), primary_key=True, comment="配置键")
    value: Mapped[str] = mapped_column(String(1024), default="", comment="配置值")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now, comment="更新时间"
    )


class SettingHistory(Base):
    """运行时配置修改历史表，只保存脱敏后的前后值，不保存秘密"""

    __tablename__ = "setting_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(128), comment="配置键")
    old_value_masked: Mapped[str] = mapped_column(
        String(1024), default="", comment="修改前脱敏值"
    )
    new_value_masked: Mapped[str] = mapped_column(
        String(1024), default="", comment="修改后脱敏值"
    )
    source: Mapped[str] = mapped_column(String(16), comment="操作来源")
    changed_by: Mapped[str] = mapped_column(String(64), default="", comment="操作者")
    changed_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, comment="修改时间"
    )
