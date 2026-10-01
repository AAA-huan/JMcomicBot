"""权限管理应用服务，统一四类名单的读写与审计。"""

from typing import Dict, Optional, Tuple

from src.database.repositories import AuditEventRepository
from src.permission.manager import PermissionManager
from src.service.operation_context import OperationContext

# 审计目标前缀：权限名单记录以 permission 为 target_type
_TARGET_TYPE = "permission"


class PermissionService:
    """封装 PermissionManager，提供渠道无关的名单读写与变更审计。"""

    def __init__(
        self,
        permission_manager: PermissionManager,
        audit_repository: AuditEventRepository,
    ) -> None:
        self.permission_manager = permission_manager
        self.audit_repository = audit_repository

    def list(self) -> Dict[str, Tuple[str, ...]]:
        """返回四类名单的当前内存快照。"""
        return {
            scope: tuple(self.permission_manager.get_scope(scope))
            for scope in PermissionManager.SCOPES
        }

    def add(
        self,
        scope: str,
        value: str,
        context: Optional[OperationContext] = None,
    ) -> bool:
        """向指定名单添加一个 ID；已存在时返回 False 且不重复审计。"""
        normalized_scope = PermissionManager.validate_scope(scope)
        normalized_value = self._normalize_value(value)
        changed = self.permission_manager.add_to_scope(
            normalized_scope, normalized_value
        )
        if changed:
            self._record_change(normalized_scope, normalized_value, "added", context)
        return changed

    def remove(
        self,
        scope: str,
        value: str,
        context: Optional[OperationContext] = None,
    ) -> bool:
        """从指定名单移除一个 ID；不存在时返回 False 且不重复审计。"""
        normalized_scope = PermissionManager.validate_scope(scope)
        normalized_value = self._normalize_value(value)
        changed = self.permission_manager.remove_from_scope(
            normalized_scope, normalized_value
        )
        if changed:
            self._record_change(normalized_scope, normalized_value, "removed", context)
        return changed

    def _record_change(
        self,
        scope: str,
        value: str,
        action: str,
        context: Optional[OperationContext],
    ) -> None:
        """写入 permission.changed 审计，不包含秘密或原始请求正文。"""
        operation_context = context or OperationContext.system()
        self.audit_repository.record(
            event_type="permission.changed",
            source=operation_context.source,
            result="succeeded",
            actor_user_id=operation_context.actor_user_id,
            actor_group_id=operation_context.actor_group_id,
            client_ip=operation_context.client_ip,
            target_type=_TARGET_TYPE,
            target_id=f"{scope}:{value}",
            metadata={"action": action, "scope": scope},
        )

    @staticmethod
    def _normalize_value(value: str) -> str:
        """清理名单值，空值明确报错。"""
        if not isinstance(value, str):
            raise ValueError("权限名单值必须是字符串")
        normalized = value.strip()
        if not normalized:
            raise ValueError("权限名单值不能为空")
        if len(normalized) > 64:
            raise ValueError("权限名单值长度不能超过 64 个字符")
        return normalized
