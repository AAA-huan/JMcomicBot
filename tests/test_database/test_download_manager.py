"""src.download.manager 中下载相关纯函数的测试"""

from src.download.manager import (
    build_pdf_filename,
    build_pdf_plugin_config,
    build_progress_plugin_config,
)


class TestBuildPdfFilename:
    """build_pdf_filename 构造 PDF 文件名测试"""

    def test_basic_format(self) -> None:
        assert build_pdf_filename("12345", "示例漫画", 3) == "12345-示例漫画(3章)"

    def test_no_suffix(self) -> None:
        assert build_pdf_filename("1", "abc", 1) == "1-abc(1章)"

    def test_braces_removed(self) -> None:
        # 大括号会干扰 jmcomic f-string 规则解析，应被替换为下划线
        assert build_pdf_filename("1", "标题{a}", 1) == "1-标题_a_(1章)"

    def test_chapter_count_large(self) -> None:
        assert build_pdf_filename("42", "title", 120) == "42-title(120章)"


class TestBuildPdfPluginConfig:
    """build_pdf_plugin_config 构造 img2pdf 插件配置测试"""

    def test_structure(self) -> None:
        config = build_pdf_plugin_config("123", "标题", 2, "/tmp/dl")
        assert config["plugin"] == "img2pdf"
        kwargs = config["kwargs"]
        assert kwargs["pdf_dir"] == "/tmp/dl"
        assert kwargs["delete_original_file"] is True
        assert kwargs["filename_rule"] == "123-标题(2章)"


class TestBuildProgressPluginConfig:
    """build_progress_plugin_config 构造 download_progress 插件配置测试"""

    def test_structure(self) -> None:
        config = build_progress_plugin_config("logs/jm.log")
        assert config["plugin"] == "download_progress"
        kwargs = config["kwargs"]
        assert kwargs["log_file"] == "logs/jm.log"
        assert kwargs["terminal_log_lines"] == 6
