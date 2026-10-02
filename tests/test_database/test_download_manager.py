"""src.download.manager 中下载相关纯函数的测试"""

from typing import Any, Dict, Optional

from src.download.manager import (
    build_pdf_filename,
    build_pdf_plugin_config,
    build_progress_plugin_config,
    inject_img2pdf_plugin,
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


class _FakeOption:
    """仅暴露 plugins 字段的最小 option 替身，用于隔离测试插件注入逻辑"""

    def __init__(self, plugins: Optional[Dict[str, Any]] = None) -> None:
        self.plugins: Dict[str, Any] = plugins if plugins is not None else {}


class TestInjectImg2pdfPlugin:
    """inject_img2pdf_plugin 注入/覆盖逻辑测试（bug.md P0-2 根因回归）"""

    def test_inject_when_absent(self) -> None:
        """用户未配置 img2pdf 时，注入使用真实章节数的插件配置"""
        option = _FakeOption()
        inject_img2pdf_plugin(option, "123", "标题", 25, "/dl")

        after_album = option.plugins["after_album"]
        assert len(after_album) == 1
        kwargs = after_album[0]["kwargs"]
        assert kwargs["pdf_dir"] == "/dl"
        assert kwargs["filename_rule"] == "123-标题(25章)"

    def test_override_user_page_based_rule(self) -> None:
        """用户已配置基于页数的 img2pdf 规则时，必须被真实章节数覆盖"""
        option = _FakeOption(
            {
                "after_album": [
                    {
                        "plugin": "img2pdf",
                        "kwargs": {
                            "pdf_dir": "./downloads",
                            "filename_rule": "{Aid}-{Aname}({Apage_count}章)",
                            "delete_original_file": True,
                        },
                    }
                ]
            }
        )
        inject_img2pdf_plugin(option, "350234", "标题", 25, "/dl")

        after_album = option.plugins["after_album"]
        assert len(after_album) == 1  # 不重复注入
        kwargs = after_album[0]["kwargs"]
        assert kwargs["filename_rule"] == "350234-标题(25章)"  # 覆盖，不再是页数
        assert kwargs["pdf_dir"] == "/dl"
        assert kwargs["delete_original_file"] is True  # 保留用户其余配置
