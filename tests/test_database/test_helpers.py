"""utils.helpers 工具函数的测试"""

from src.utils.helpers import sanitize_filename


class TestSanitizeFilename:
    """sanitize_filename 清洗函数测试"""

    def test_normal_title_unchanged(self) -> None:
        assert sanitize_filename("示例漫画") == "示例漫画"
        assert sanitize_filename("COMIC 2024") == "COMIC 2024"

    def test_path_separators_replaced(self) -> None:
        assert sanitize_filename("标题/子标题") == "标题_子标题"
        assert sanitize_filename("标题\\子标题") == "标题_子标题"

    def test_invalid_chars_replaced(self) -> None:
        assert sanitize_filename('标题:*?"<>|') == "标题_______"

    def test_trailing_dots_removed(self) -> None:
        assert sanitize_filename("标题.....") == "标题"
        assert sanitize_filename("标题...") == "标题"

    def test_long_title_truncated(self) -> None:
        # 100 个中文字节 = 300 字节，超过默认 200 字节限制，应被截断
        long_title = "仮" * 100
        result = sanitize_filename(long_title)
        assert len(result.encode("utf-8")) <= 200

    def test_long_title_not_cut_multibyte(self) -> None:
        # 截断后不应出现残缺的多字节字符（每个“仮”为3字节）
        long_title = "仮" * 70  # 210 字节
        result = sanitize_filename(long_title, max_bytes=200)
        assert result.isspace() is False or result == ""
        # 只能包含完整的"仮"
        assert all(char == "仮" for char in result)
        assert len(result.encode("utf-8")) <= 200

    def test_custom_max_bytes(self) -> None:
        title = "abcdefghij"
        assert sanitize_filename(title, max_bytes=5) == "abcde"

    def test_no_cut_partial_utf8_without_limit(self) -> None:
        # 限制要比省略号/边界安全：确保截断最后没有半个字符
        result = sanitize_filename("仮仮仮仮", max_bytes=10)
        assert len(result.encode("utf-8")) <= 10

    def test_safe_for_fs(self) -> None:
        # 与文件系统集成：清洗后的标题可直接用于创建文件名
        import os

        actual = sanitize_filename("超长标题" + "/" * 60 + "结尾")
        path = os.path.join(os.getcwd(), "test_dummy.pdf")
        try:
            name = "350234-" + actual + "(3章).pdf"
            with open(name, "w", encoding="utf-8"):
                pass
            os.remove(name)
        finally:
            if os.path.exists(path):
                os.remove(path)
