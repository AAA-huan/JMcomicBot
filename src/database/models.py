"""SQLAlchemy ORM 模型定义，对应 SQLite 数据库中的各张表"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """所有 ORM 模型的声明式基类"""


class Manga(Base):
    """漫画元数据表，记录已下载漫画的标题、作者、标签等信息"""

    __tablename__ = "manga"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, comment="漫画ID")
    source_site: Mapped[str] = mapped_column(
        String(64), default="jmcomic", comment="来源站点"
    )
    title: Mapped[str] = mapped_column(String(255), default="", comment="漫画标题")
    author: Mapped[str] = mapped_column(String(255), default="", comment="漫画作者")
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="简介")
    tags: Mapped[str] = mapped_column(
        String(1024), default="", comment="漫画类型标签(逗号分隔)"
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
        DateTime, default=datetime.now, comment="下载完成时间"
    )
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )

    files: Mapped[list["MangaFile"]] = relationship(
        back_populates="manga",
        cascade="all, delete-orphan",
    )


class MangaFile(Base):
    """漫画PDF文件表，记录漫画对应的一个或多个PDF文件"""

    __tablename__ = "manga_file"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    manga_id: Mapped[str] = mapped_column(
        ForeignKey("manga.id", ondelete="CASCADE"), index=True
    )
    file_path: Mapped[str] = mapped_column(
        String(1024), unique=True, comment="PDF文件路径"
    )
    file_size_mb: Mapped[float] = mapped_column(
        Float, default=0.0, comment="文件大小(MB)"
    )
    relative_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    file_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    mime_type: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    file_size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    page_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, comment="记录创建时间"
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    manga: Mapped["Manga"] = relationship(back_populates="files")


class MangaTag(Base):
    """漫画标签表，记录每个标签下对应的漫画PDF文件名"""

    __tablename__ = "manga_tag"
    __table_args__ = (
        UniqueConstraint("tag", "manga_id", name="uq_manga_tag_tag_manga"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tag: Mapped[str] = mapped_column(String(128), index=True, comment="标签名")
    manga_id: Mapped[str] = mapped_column(String(32), index=True, comment="漫画ID")
    pdf_name: Mapped[str] = mapped_column(String(512), comment="漫画PDF文件名")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, comment="记录创建时间"
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
        DateTime, default=datetime.now, index=True, comment="任务创建时间"
    )


class UserInfo(Base):
    """用户信息表，缓存用户昵称以便日志展示与WebUI使用"""

    __tablename__ = "user_info"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, comment="用户QQ号")
    nickname: Mapped[str] = mapped_column(String(255), default="", comment="用户昵称")
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, comment="最近一次活跃时间"
    )


class GroupInfo(Base):
    """群组信息表，缓存群名称以便日志展示与WebUI使用"""

    __tablename__ = "group_info"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, comment="群组ID")
    group_name: Mapped[str] = mapped_column(String(255), default="", comment="群名称")
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, comment="最近一次活跃时间"
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
        DateTime, default=datetime.now, comment="记录创建时间"
    )


class Setting(Base):
    """运行时配置表，存储可通过WebUI或命令动态修改的键值配置"""

    __tablename__ = "setting"

    key: Mapped[str] = mapped_column(String(128), primary_key=True, comment="配置键")
    value: Mapped[str] = mapped_column(String(1024), default="", comment="配置值")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now, comment="更新时间"
    )
