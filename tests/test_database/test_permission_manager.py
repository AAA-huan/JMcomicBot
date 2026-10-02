"""权限管理器（.env种子导入 + 动态增删）的测试"""

import pytest

from src.database.repositories.permission_repository import PermissionRepository
from src.permission.manager import PermissionManager


class TestPermissionManager:
    """权限管理器测试类"""

    def test_seed_if_empty(self, permission_repo: PermissionRepository) -> None:
        manager = PermissionManager(
            permission_repo=permission_repo,
            seed_group_whitelist=["1", "2"],
            seed_private_whitelist=["3"],
            seed_global_blacklist=["4"],
            seed_delete_permission_user=["5"],
        )
        assert manager.group_whitelist == ["1", "2"]
        assert manager.private_whitelist == ["3"]
        assert manager.global_blacklist == ["4"]
        assert manager.delete_permission_user == ["5"]

    def test_seed_not_overwrite_existing(
        self, permission_repo: PermissionRepository
    ) -> None:
        permission_repo.add("group_whitelist", "100")
        manager = PermissionManager(
            permission_repo=permission_repo,
            seed_group_whitelist=["1", "2"],
        )
        assert manager.group_whitelist == ["100"]

    def test_add_to_scope_and_effect(
        self, permission_repo: PermissionRepository
    ) -> None:
        manager = PermissionManager(permission_repo=permission_repo)
        assert manager.add_to_scope("group_whitelist", "999") is True
        assert "999" in manager.group_whitelist
        assert permission_repo.contains("group_whitelist", "999") is True

        assert manager.add_to_scope("group_whitelist", "999") is False

    def test_remove_from_scope_and_effect(
        self, permission_repo: PermissionRepository
    ) -> None:
        manager = PermissionManager(permission_repo=permission_repo)
        manager.add_to_scope("global_blacklist", "888")
        assert manager.remove_from_scope("global_blacklist", "888") is True
        assert "888" not in manager.global_blacklist

        assert manager.remove_from_scope("global_blacklist", "888") is False

    def test_update_whitelist(self, permission_repo: PermissionRepository) -> None:
        manager = PermissionManager(permission_repo=permission_repo)
        manager.update_whitelist(group_whitelist=["a", "b"])
        assert manager.group_whitelist == ["a", "b"]
        assert sorted(permission_repo.list_values("group_whitelist")) == ["a", "b"]

    def test_check_user_permission(self, permission_repo: PermissionRepository) -> None:
        manager = PermissionManager(
            permission_repo=permission_repo,
            seed_private_whitelist=["u1"],
            seed_global_blacklist=["bad"],
        )
        # 白名单内用户通过
        assert manager.check_user_permission("u1", private=True) is True
        # 黑名单内用户被拒绝
        with pytest.raises(ValueError):
            manager.check_user_permission("bad", private=True)
        # 不在私聊白名单内的用户被拒绝
        with pytest.raises(ValueError):
            manager.check_user_permission("free", private=True)

    def test_check_user_permission_empty_whitelist_allows(
        self, permission_repo: PermissionRepository
    ) -> None:
        """白名单为空表示不限制，任意用户均可通过"""
        manager = PermissionManager(permission_repo=permission_repo)
        assert manager.check_user_permission("anyone", private=True) is True

    def test_check_delete_permission(
        self, permission_repo: PermissionRepository
    ) -> None:
        manager = PermissionManager(
            permission_repo=permission_repo,
            seed_delete_permission_user=["admin"],
        )
        assert manager.check_delete_permission("admin") is True

        with pytest.raises(ValueError):
            manager.check_delete_permission("other")

    def test_check_delete_disabled_when_empty(
        self, permission_repo: PermissionRepository
    ) -> None:
        manager = PermissionManager(permission_repo=permission_repo)
        with pytest.raises(ValueError) as exc_info:
            manager.check_delete_permission("admin")
        assert "未配置删除权限用户" in str(exc_info.value)
