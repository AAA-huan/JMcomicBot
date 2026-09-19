"""权限名单仓储的测试"""

from src.database.repositories.permission_repository import PermissionRepository


class TestPermission:
    """权限名单仓储测试类"""

    def test_add_and_contains(self, permission_repo: PermissionRepository) -> None:
        assert permission_repo.add("group_whitelist", "123") is True
        assert permission_repo.add("group_whitelist", "123") is False
        assert permission_repo.contains("group_whitelist", "123") is True
        assert permission_repo.contains("group_whitelist", "999") is False

    def test_list_values(self, permission_repo: PermissionRepository) -> None:
        permission_repo.add("group_whitelist", "1")
        permission_repo.add("group_whitelist", "2")
        assert sorted(permission_repo.list_values("group_whitelist")) == ["1", "2"]
        assert permission_repo.list_values("private_whitelist") == []

    def test_get_all_scopes(self, permission_repo: PermissionRepository) -> None:
        permission_repo.add("group_whitelist", "1")
        permission_repo.add("private_whitelist", "2")
        scopes = permission_repo.get_all_scopes()
        assert scopes["group_whitelist"] == ["1"]
        assert scopes["private_whitelist"] == ["2"]

    def test_remove(self, permission_repo: PermissionRepository) -> None:
        permission_repo.add("global_blacklist", "1")
        assert permission_repo.remove("global_blacklist", "1") is True
        assert permission_repo.remove("global_blacklist", "1") is False
        assert permission_repo.contains("global_blacklist", "1") is False

    def test_replace_scope(self, permission_repo: PermissionRepository) -> None:
        permission_repo.add("group_whitelist", "1")
        permission_repo.replace_scope("group_whitelist", ["2", "3"])
        assert sorted(permission_repo.list_values("group_whitelist")) == ["2", "3"]

    def test_get(self, permission_repo: PermissionRepository) -> None:
        permission_repo.add("group_whitelist", "1")
        records = permission_repo.list()
        assert len(records) == 1
        assert permission_repo.get(records[0].id) is not None
