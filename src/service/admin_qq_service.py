"""WebUI 单管理员 QQ 关联服务。"""

from typing import Optional
import re

from src.database.repositories import AuditEventRepository, WebAdminRepository
from src.permission.manager import PermissionManager

from .operation_context import OperationContext


class AdminQQService:
    """管理关联关系，权限管理器每次授权读取该持久化关系。"""

    def __init__(
        self,
        repository: WebAdminRepository,
        permission_manager: PermissionManager,
        audit_repository: AuditEventRepository,
    ) -> None:
        self.repository = repository
        self.permission_manager = permission_manager
        self.audit_repository = audit_repository

    def get(self, admin_id: int = 1) -> Optional[str]:
        """获取管理员关联的 QQ，不返回账户密码或会话信息。"""
        admin = self.repository.get(admin_id)
        if admin is None:
            raise ValueError("WebUI 管理员尚未初始化")
        return admin.qq_id

    def update(
        self,
        qq_id: Optional[str],
        admin_id: int = 1,
        context: Optional[OperationContext] = None,
    ) -> bool:
        """关联、更换或解绑，重复操作无副作用。"""
        if qq_id is not None:
            if (
                not isinstance(qq_id, str)
                or re.fullmatch(r"[1-9][0-9]{0,19}", qq_id) is None
            ):
                raise ValueError("QQ 号必须是 1–20 位正整数数字，不能含前导零")
            if qq_id in self.permission_manager.global_blacklist:
                raise ValueError("该 QQ 号在全局黑名单中，请先移出黑名单再关联")
        changed = self.repository.set_qq_id(qq_id, admin_id)
        if changed:
            actor = context or OperationContext.system()
            self.audit_repository.record(
                event_type="admin.qq.changed",
                source=actor.source,
                result="succeeded",
                actor_user_id=actor.actor_user_id,
                actor_group_id=actor.actor_group_id,
                client_ip=actor.client_ip,
                target_type="web_admin",
                target_id=str(admin_id),
                metadata={
                    "action": "unlinked" if qq_id is None else "linked",
                    "qq_id": qq_id,
                },
            )
        return changed
