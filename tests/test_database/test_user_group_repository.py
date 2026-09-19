"""用户/群组信息仓储的测试"""

from src.database.repositories.user_group_repository import UserGroupRepository


class TestUserGroup:
    """用户/群组信息仓储测试类"""

    def test_upsert_user(self, user_group_repo: UserGroupRepository) -> None:
        user = user_group_repo.upsert_user("u1", "小明")
        assert user.id == "u1"
        assert user.nickname == "小明"

        user_group_repo.upsert_user("u1", "大明")
        loaded = user_group_repo.get_user("u1")
        assert loaded is not None
        assert loaded.nickname == "大明"

    def test_get_user_nonexistent(self, user_group_repo: UserGroupRepository) -> None:
        assert user_group_repo.get_user("u99") is None

    def test_upsert_group(self, user_group_repo: UserGroupRepository) -> None:
        group = user_group_repo.upsert_group("g1", "测试群")
        assert group.id == "g1"
        assert group.group_name == "测试群"

        user_group_repo.upsert_group("g1", "新群名")
        loaded = user_group_repo.get_group("g1")
        assert loaded is not None
        assert loaded.group_name == "新群名"

    def test_list(self, user_group_repo: UserGroupRepository) -> None:
        user_group_repo.upsert_user("u1", "小明")
        user_group_repo.upsert_group("g1", "测试群")
        records = user_group_repo.list()
        assert len(records) == 2
