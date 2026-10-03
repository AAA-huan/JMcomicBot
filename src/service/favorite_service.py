"""WebUI 管理员漫画收藏服务。"""

from typing import Optional

from src.database.repositories import AuditEventRepository, FavoriteRepository

from .operation_context import OperationContext


class FavoriteService:
    """收藏只由已认证 WebUI 入口调用，归属来自服务端会话。"""

    def __init__(
        self, repository: FavoriteRepository, audit_repository: AuditEventRepository
    ) -> None:
        self.repository = repository
        self.audit_repository = audit_repository

    def set_favorite(
        self,
        admin_id: int,
        manga_id: str,
        favorite: bool,
        context: Optional[OperationContext] = None,
    ) -> bool:
        """收藏 / 取消收藏；重复操作不写重复审计。"""
        changed = self.repository.set_favorite(
            "web_admin", str(admin_id), manga_id, favorite
        )
        if changed:
            actor = context or OperationContext.system()
            self.audit_repository.record(
                event_type="favorite.changed",
                source=actor.source,
                result="succeeded",
                actor_user_id=actor.actor_user_id,
                actor_group_id=actor.actor_group_id,
                client_ip=actor.client_ip,
                target_type="manga",
                target_id=manga_id,
                metadata={
                    "action": "added" if favorite else "removed",
                    "admin_id": admin_id,
                },
            )
        return changed
