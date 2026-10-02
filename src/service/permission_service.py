"""权限管理应用服务，统一四类名单的读写、缓存展示与审计。"""

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional, Tuple

from src.database.models import GroupInfo, UserInfo
from src.database.repositories import AuditEventRepository, UserGroupRepository
from src.permission.manager import PermissionManager
from src.service.operation_context import OperationContext

# 审计目标前缀：权限名单记录以 permission 为 target_type
_TARGET_TYPE = "permission"
# 缓存展示的默认上限，避免一次返回过多历史身份
DEFAULT_IDENTITY_LIMIT = 200


@dataclass(frozen=True)
class CachedUser:
    """已缓存的 QQ 用户公开信息。"""

    id: str
    nickname: str
    last_seen_at: datetime


@dataclass(frozen=True)
class CachedGroup:
    """已缓存的 QQ 群公开信息。"""

    id: str
    group_name: str
    last_seen_at: datetime


class PermissionService:
    """封装 PermissionManager，提供渠道无关的名单读写与变更审计。"""

    def __init__(
        self,
        permission_manager: PermissionManager,
        audit_repository: AuditEventRepository,
        user_group_repository: UserGroupRepository,
    ) -> None:
        self.permission_manager = permission_manager
        self.audit_repository = audit_repository
        self.user_group_repository = user_group_repository

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

    def list_cached_users(
        self, limit: int = DEFAULT_IDENTITY_LIMIT
    ) -> Tuple[CachedUser, ...]:
        """按最近活跃时间返回已缓存的 QQ 用户。"""
        users = self.user_group_repository.list_users(limit)
        return tuple(self._to_cached_user(user) for user in users)

    def list_cached_groups(
        self, limit: int = DEFAULT_IDENTITY_LIMIT
    ) -> Tuple[CachedGroup, ...]:
        """按最近活跃时间返回已缓存的 QQ 群。"""
        groups = self.user_group_repository.list_groups(limit)
        return tuple(self._to_cached_group(group) for group in groups)

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
    def _to_cached_user(user: UserInfo) -> CachedUser:
        return CachedUser(
            id=user.id, nickname=user.nickname, last_seen_at=user.last_seen_at
        )

    @staticmethod
    def _to_cached_group(group: GroupInfo) -> CachedGroup:
        return CachedGroup(
            id=group.id, group_name=group.group_name, last_seen_at=group.last_seen_at
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
