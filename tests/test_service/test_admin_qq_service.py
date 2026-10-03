"""管理员关联 QQ 的即时授权、撤销、黑名单优先与审计测试。"""

import pytest

from src.database.repositories import (
    AuditEventRepository,
    PermissionRepository,
    WebAdminRepository,
)
from src.permission.manager import PermissionManager
from src.service.admin_qq_service import AdminQQService
from src.service.operation_context import OperationContext


def build_service(db_manager):
    repository = WebAdminRepository(db_manager)
    repository.create("test-hash")
    manager = PermissionManager(
        PermissionRepository(db_manager), admin_repository=repository
    )
    manager.add_to_scope("private_whitelist", "999")
    manager.add_to_scope("group_whitelist", "888")
    service = AdminQQService(repository, manager, AuditEventRepository(db_manager))
    return service, manager


def test_link_replace_unlink_apply_immediately_and_persist(db_manager):
    """关联可绕过白名单、删除；更换与解绑立即撤销，重建管理器仍生效。"""
    service, manager = build_service(db_manager)
    context = OperationContext.web("1", "127.0.0.1")
    assert service.get() is None
    assert service.update("12345", context=context)
    assert not service.update("12345", context=context)
    assert manager.is_admin("12345")
    assert manager.check_user_permission("12345", private=True)
    assert manager.check_user_permission("12345", group_id="777", private=False)
    assert manager.check_delete_permission("12345")
    restarted = PermissionManager(PermissionRepository(db_manager))
    assert restarted.is_admin("12345")
    assert service.update("67890", context=context)
    assert not manager.is_admin("12345")
    with pytest.raises(ValueError):
        manager.check_user_permission("12345", private=True)
    with pytest.raises(ValueError):
        manager.check_delete_permission("12345")
    assert manager.check_delete_permission("67890")
    assert service.update(None, context=context)
    assert not service.update(None, context=context)
    assert not manager.is_admin("67890")
    with pytest.raises(ValueError):
        manager.check_delete_permission("67890")
    events = [
        event
        for event in AuditEventRepository(db_manager).list()
        if event.event_type == "admin.qq.changed"
    ]
    assert len(events) == 3
    assert all(event.source == "web" for event in events)
    assert manager.get_scope("private_whitelist") == ["999"]


def test_blacklist_blocks_admin_and_unlink_preserves_explicit_permissions(db_manager):
    """黑名单优先；解绑不修改原有单独删除授权。"""
    service, manager = build_service(db_manager)
    manager.add_to_scope("global_blacklist", "12345")
    with pytest.raises(ValueError, match="黑名单"):
        service.update("12345")
    manager.remove_from_scope("global_blacklist", "12345")
    service.update("12345")
    manager.add_to_scope("global_blacklist", "12345")
    assert not manager.is_admin("12345")
    with pytest.raises(ValueError, match="黑名单"):
        manager.check_user_permission("12345")
    with pytest.raises(ValueError, match="黑名单"):
        manager.check_delete_permission("12345")
    manager.remove_from_scope("global_blacklist", "12345")
    manager.add_to_scope("delete_permission_user", "12345")
    service.update(None)
    assert manager.check_delete_permission("12345")
    assert not manager.is_admin("12345")


@pytest.mark.parametrize(
    "qq_id",
    ["", "0", "00123", "-123", "1.2", "abc", "１２３", "123 45", "1" * 21, 12345],
)
def test_invalid_qq_rejected_without_changes(db_manager, qq_id):
    """输入非法时不修改授权或留下成功审计。"""
    service, _ = build_service(db_manager)
    with pytest.raises(ValueError, match="QQ 号"):
        service.update(qq_id)
    assert service.get() is None
    assert AuditEventRepository(db_manager).list() == []
