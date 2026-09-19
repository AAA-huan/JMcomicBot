"""运行时配置仓储的测试"""

from src.database.repositories.setting_repository import SettingRepository


class TestSetting:
    """运行时配置仓储测试类"""

    def test_set_and_get(self, setting_repo: SettingRepository) -> None:
        setting_repo.set("key1", "value1")
        assert setting_repo.get("key1") == "value1"
        assert setting_repo.get("key1", "default") == "value1"

    def test_get_default(self, setting_repo: SettingRepository) -> None:
        assert setting_repo.get("missing") == ""
        assert setting_repo.get("missing", "fallback") == "fallback"

    def test_get_int(self, setting_repo: SettingRepository) -> None:
        setting_repo.set("num", "42")
        assert setting_repo.get_int("num") == 42
        assert setting_repo.get_int("num", 99) == 42
        assert setting_repo.get_int("bad", 5) == 5

    def test_get_bool(self, setting_repo: SettingRepository) -> None:
        setting_repo.set("flag", "true")
        assert setting_repo.get_bool("flag") is True
        setting_repo.set("flag2", "false")
        assert setting_repo.get_bool("flag2") is False
        assert setting_repo.get_bool("missing", True) is True

    def test_list_and_delete(self, setting_repo: SettingRepository) -> None:
        setting_repo.set("a", "1")
        setting_repo.set("b", "2")
        assert len(setting_repo.list()) == 2

        assert setting_repo.delete("a") is True
        assert setting_repo.delete("a") is False
        assert len(setting_repo.list()) == 1
