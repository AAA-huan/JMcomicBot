"""option_example.yml 文件名规则回归测试

历史 bug（bug.md P0-1）：示例配置的 filename_rule 使用 Apage_count（jmcomic 的
总页数字段），却写成「章」，用户按 README 复制后文件名显示的是页数而非章节数。
本测试确保示例配置不再教用户这种错误写法，防止回归。
"""

from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OPTION_EXAMPLE = PROJECT_ROOT / "option_example.yml"


def _load_option_example() -> dict:
    """加载 option_example.yml，返回解析后的配置字典"""
    with OPTION_EXAMPLE.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


class TestOptionExampleFilenameRule:
    """option_example.yml 不得出现基于页数的文件名规则"""

    def test_file_exists(self) -> None:
        assert OPTION_EXAMPLE.is_file()

    def test_no_page_count_placeholder(self) -> None:
        # Apage_count 是 jmcomic 的总页数字段，出现在「章」的语境里即为 P0-1 根因
        content = OPTION_EXAMPLE.read_text(encoding="utf-8")
        assert "Apage_count" not in content

    def test_img2pdf_filename_rule_not_page_based(self) -> None:
        data = _load_option_example()
        plugins = data.get("plugins") or {}
        after_album = plugins.get("after_album") or []
        for plugin in after_album:
            if plugin.get("plugin") != "img2pdf":
                continue
            rule = (plugin.get("kwargs") or {}).get("filename_rule", "")
            assert "page_count" not in rule, f"示例规则仍基于页数: {rule}"
