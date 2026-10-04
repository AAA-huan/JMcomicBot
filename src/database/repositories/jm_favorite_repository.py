"""远端收藏与分页导入任务仓储。"""

# pylint: disable=arguments-differ

from typing import Dict, List, Optional, Set, Tuple

from sqlalchemy import func, select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from src.database.models import (
    JmFavoriteImport,
    JmRemoteFavorite,
    Manga,
    MangaFavorite,
    MangaFile,
    utc_now,
)

from ._base import BaseRepository


def link_imported_favorites(session: Session, manga_id: str) -> Set[int]:
    """在调用方事务中关联待处理收藏，避免下载后重新恢复手工取消的收藏。"""
    manga = session.get(Manga, manga_id)
    if manga is None or manga.status == "deleted" or manga.source_site != "jmcomic":
        return set()
    records = session.scalars(
        select(JmRemoteFavorite).where(
            JmRemoteFavorite.manga_id == manga_id,
            JmRemoteFavorite.pending_local_favorite.is_(True),
        )
    ).all()
    admin_ids = {record.admin_id for record in records}
    for admin_id in admin_ids:
        session.execute(
            insert(MangaFavorite)
            .values(
                owner_type="web_admin",
                owner_id=str(admin_id),
                manga_id=manga_id,
                created_at=utc_now(),
            )
            .on_conflict_do_nothing(
                index_elements=["owner_type", "owner_id", "manga_id"]
            )
        )
    for record in records:
        record.pending_local_favorite = False
    return admin_ids


def import_view(job: JmFavoriteImport) -> Dict[str, object]:
    """返回不包含账号会话的任务快照。"""
    return {
        "id": job.id,
        "username": job.username,
        "folder_ids": job.folder_ids,
        "status": job.status,
        "pages_done": job.pages_done,
        "imported_count": job.imported_count,
        "duplicate_count": job.duplicate_count,
        "local_count": job.local_count,
        "error_message": job.error_message,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


class JmFavoriteRepository(BaseRepository):
    """每个管理员和账号分别保存远端收藏，所有查询强制限定管理员。"""

    def get(self, admin_id: int, job_id: str) -> Optional[JmFavoriteImport]:
        with self._get_session() as session:
            return session.scalar(
                select(JmFavoriteImport).where(
                    JmFavoriteImport.id == job_id, JmFavoriteImport.admin_id == admin_id
                )
            )

    def list(self, admin_id: int) -> List[JmFavoriteImport]:
        with self._get_session() as session:
            return list(
                session.scalars(
                    select(JmFavoriteImport)
                    .where(JmFavoriteImport.admin_id == admin_id)
                    .order_by(JmFavoriteImport.created_at.desc())
                    .limit(20)
                ).all()
            )

    def create_import(
        self, admin_id: int, job_id: str, username: str, folder_ids: List[str]
    ) -> JmFavoriteImport:
        """在后台启动前登记导入任务。"""
        with self._get_session() as session:
            job = JmFavoriteImport(
                id=job_id, admin_id=admin_id, username=username, folder_ids=folder_ids
            )
            session.add(job)
            session.commit()
            return job

    def save_page(
        self,
        admin_id: int,
        job_id: str,
        folder_id: str,
        folder_name: str,
        items: List[Tuple[str, str]],
        seen: Set[str],
    ) -> None:
        """整页事务保存；跨收藏夹重复只增加成员关系，不重复累计漫画数量。"""
        with self._get_session() as session:
            job = session.scalar(
                select(JmFavoriteImport).where(
                    JmFavoriteImport.id == job_id, JmFavoriteImport.admin_id == admin_id
                )
            )
            if job is None or job.status != "running":
                raise RuntimeError("导入任务不存在或已结束")
            page_seen: Set[str] = set()
            for manga_id, title in items:
                record = session.get(
                    JmRemoteFavorite, (admin_id, job.username, manga_id)
                )
                fresh = record is None
                if record is None:
                    record = JmRemoteFavorite(
                        admin_id=admin_id,
                        username=job.username,
                        manga_id=manga_id,
                        title=title,
                        folders={},
                    )
                    session.add(record)
                record.title = title
                record.folders = {**record.folders, folder_id: folder_name}
                record.pending_local_favorite = True
                record.updated_at = utc_now()
                session.flush()
                local = admin_id in link_imported_favorites(session, manga_id)
                if manga_id not in seen and manga_id not in page_seen:
                    job.imported_count += int(fresh)
                    job.duplicate_count += int(not fresh)
                    job.local_count += int(local)
                page_seen.add(manga_id)
            job.pages_done += 1
            job.updated_at = utc_now()
            session.commit()
            seen.update(page_seen)

    def finish(
        self,
        admin_id: int,
        job_id: str,
        status: str,
        error_message: Optional[str] = None,
    ) -> None:
        """更新终态，不删除已完成页。"""
        with self._get_session() as session:
            session.execute(
                update(JmFavoriteImport)
                .where(
                    JmFavoriteImport.id == job_id,
                    JmFavoriteImport.admin_id == admin_id,
                    JmFavoriteImport.status == "running",
                )
                .values(
                    status=status, error_message=error_message, updated_at=utc_now()
                )
            )
            session.commit()

    def recover_interrupted(self) -> None:
        """进程重启不保留登录 Cookie，明确中断遗留导入任务。"""
        with self._get_session() as session:
            session.execute(
                update(JmFavoriteImport)
                .where(JmFavoriteImport.status == "running")
                .values(
                    status="interrupted",
                    error_message="服务重启，导入已中断；已导入的漫画保留，请重新登录并导入。",
                    updated_at=utc_now(),
                )
            )
            session.commit()

    def prepare_download(self, admin_id: int, manga_ids: List[str]) -> None:
        """显式从导入列表下载时重新登记收藏意图，包括曾被删除的本地漫画。"""
        with self._get_session() as session:
            records = session.scalars(
                select(JmRemoteFavorite).where(
                    JmRemoteFavorite.admin_id == admin_id,
                    JmRemoteFavorite.manga_id.in_(manga_ids),
                )
            ).all()
            if {record.manga_id for record in records} != set(manga_ids):
                raise LookupError("所选漫画不在当前管理员的导入收藏中")
            for record in records:
                record.pending_local_favorite = True
            session.commit()

    def list_favorites(
        self,
        admin_id: int,
        page: int,
        page_size: int,
        search: str = "",
        username: str = "",
        folder_id: str = "",
        download_status: str = "",
    ) -> Dict[str, object]:
        """先筛选再分页，联查本地文件状态而不创建占位漫画。"""
        local = (
            (Manga.source_site == "jmcomic")
            & (Manga.status == "downloaded")
            & (MangaFile.status == "ready")
        )
        statement = (
            select(JmRemoteFavorite, MangaFile.id, local.label("downloaded"))
            .outerjoin(Manga, Manga.id == JmRemoteFavorite.manga_id)
            .outerjoin(MangaFile, MangaFile.manga_id == Manga.id)
            .where(JmRemoteFavorite.admin_id == admin_id)
        )
        if search:
            statement = statement.where(
                JmRemoteFavorite.title.contains(search, autoescape=True)
                | JmRemoteFavorite.manga_id.contains(search, autoescape=True)
            )
        if username:
            statement = statement.where(JmRemoteFavorite.username == username)
        if folder_id:
            statement = statement.where(
                func.json_extract(JmRemoteFavorite.folders, f'$."{folder_id}"').is_not(
                    None
                )
            )
        if download_status:
            statement = (
                statement.where(local.is_(download_status == "downloaded"))
                if download_status == "downloaded"
                else statement.where(func.coalesce(local, False).is_(False))
            )
        with self._get_session() as session:
            # SQLAlchemy 动态生成聚合函数，Pylint 无法识别其可调用类型。
            # pylint: disable=not-callable
            total = session.execute(
                select(func.count()).select_from(statement.subquery())
            ).scalar_one()
            # pylint: enable=not-callable
            rows = session.execute(
                statement.order_by(
                    JmRemoteFavorite.updated_at.desc(),
                    JmRemoteFavorite.username,
                    JmRemoteFavorite.manga_id,
                )
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).all()
            return {
                "items": [
                    {
                        "manga_id": record.manga_id,
                        "title": record.title,
                        "username": record.username,
                        "folders": record.folders,
                        "downloaded": bool(downloaded),
                        "file_id": file_id if downloaded else None,
                        "imported_at": record.imported_at,
                    }
                    for record, file_id, downloaded in rows
                ],
                "total": total,
                "page": page,
                "page_size": page_size,
                "pages": (total + page_size - 1) // page_size,
            }
