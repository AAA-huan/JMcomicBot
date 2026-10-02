"""权限管理应用服务测试。"""

import pytest

from src.database.repositories import (
    AuditEventRepository,
    PermissionRepository,
    UserGroupRepository,
)
from src.permission.manager import PermissionManager
from src.service import OperationContext, PermissionService


def _build_service(db_manager) -> tuple[PermissionService, PermissionManager]:
    """构造使用真实仓储的权限服务，权限表为空时无预置名单。"""
    manager = PermissionManager(PermissionRepository(db_manager))
    service = PermissionService(
        manager, AuditEventRepository(db_manager), UserGroupRepository(db_manager)
    )
    return service, manager


def test_add_and_remove_refresh_memory_immediately(db_manager) -> None:
    """名单增删后内存缓存应立即生效。"""
    service, manager = _build_service(db_manager)

    assert service.add("group_whitelist", "10001") is True
    assert manager.group_whitelist == ["10001"]

    assert service.remove("group_whitelist", "10001") is True
    assert manager.group_whitelist == []


def test_invalid_scope_is_rejected_without_change(db_manager) -> None:
    """非法 scope 必须明确报错，且不写库、不写审计。"""
    service, manager = _build_service(db_manager)

    with pytest.raises(ValueError, match="不支持的权限类型"):
        service.add("unknown_scope", "10001")

    assert manager.get_scope("group_whitelist") == []
    assert AuditEventRepository(db_manager).list() == []


def test_duplicate_add_does_not_write_duplicate_audit(db_manager) -> None:
    """重复添加返回 False，且不会重复记录审计。"""
    service, _manager = _build_service(db_manager)

    assert service.add("private_whitelist", "10001") is True
    assert service.add("private_whitelist", "10001") is False

    events = AuditEventRepository(db_manager).list()
    changed_events = [
        event for event in events if event.event_type == "permission.changed"
    ]
    assert len(changed_events) == 1


def test_permission_change_writes_audit_with_actor(db_manager) -> None:
    """权限变更审计应携带来源、操作者、客户端 IP 与目标。"""
    service, _manager = _build_service(db_manager)

    service.add("global_blacklist", "10002", OperationContext.web("1", "192.168.1.10"))

    event = AuditEventRepository(db_manager).list()[0]
    assert event.event_type == "permission.changed"
    assert event.source == "web"
    assert event.actor_user_id == "1"
    assert event.client_ip == "192.168.1.10"
    assert event.target_type == "permission"
    assert event.target_id == "global_blacklist:10002"


def test_permission_change_takes_effect_for_qq_immediately(db_manager) -> None:
    """私信白名单修改后，QQ 权限检查应立即按新名单执行。"""
    service, manager = _build_service(db_manager)
    service.add("private_whitelist", "10001")

    assert manager.check_user_permission("10001", private=True) is True

    with pytest.raises(ValueError, match="不在私信白名单"):
        manager.check_user_permission("10002", private=True)
