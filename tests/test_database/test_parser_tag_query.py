"""命令解析器对按标签/作者查询参数验证的测试"""

from src.command.parser import CommandParser


class TestCommandParserTagQuery:
    """命令解析器按标签查询参数验证测试类"""

    def setup_method(self) -> None:
        self.parser = CommandParser()

    def test_single_tag(self) -> None:
        assert self.parser.validate_params("query", "-t 萌系") is True

    def test_multi_tag_with_comma(self) -> None:
        assert self.parser.validate_params("query", "-t 萌系,纯爱") is True

    def test_multi_tag_with_chinese_comma(self) -> None:
        assert self.parser.validate_params("query", "-t 萌系，纯爱") is True

    def test_tag_with_spaces(self) -> None:
        # 标签名含空格（用逗号或空格分隔标签）
        assert self.parser.validate_params("query", "-t 纯爱 后宫") is True

    def test_empty_tag_rejected(self) -> None:
        assert self.parser.validate_params("query", "-t") is False
        assert self.parser.validate_params("query", "-t ") is False

    def test_tag_query_recognized_as_query(self) -> None:
        cmd, args = self.parser.parse("查询漫画 -t 萌系")
        assert cmd == "query"
        assert args == "-t 萌系"

    def test_author_query(self) -> None:
        assert self.parser.validate_params("query", "-z しにま") is True

    def test_author_query_with_spaces(self) -> None:
        # 作者名可能含空格，取 -z 后整段
        assert self.parser.validate_params("query", "-z 佐々木 篠") is True

    def test_author_query_chinese(self) -> None:
        assert self.parser.validate_params("query", "-z 某作者") is True

    def test_empty_author_rejected(self) -> None:
        assert self.parser.validate_params("query", "-z") is False
        assert self.parser.validate_params("query", "-z ") is False

    def test_author_query_recognized_as_query(self) -> None:
        cmd, args = self.parser.parse("查询漫画 -z しにま")
        assert cmd == "query"
        assert args == "-z しにま"


class TestCommandParserCancel:
    """命令解析器下载/发送取消参数验证测试类"""

    def setup_method(self) -> None:
        self.parser = CommandParser()

    def test_cancel_all_download(self) -> None:
        assert self.parser.validate_params("download", "-c") is True
        assert self.parser.validate_params("download", "-c ") is True

    def test_cancel_single_download(self) -> None:
        assert self.parser.validate_params("download", "-c 114514") is True

    def test_cancel_multi_download(self) -> None:
        assert self.parser.validate_params("download", "-c 114514,516751") is True

    def test_cancel_multi_download_chinese_sep(self) -> None:
        assert self.parser.validate_params("download", "-c 114514，516751") is True

    def test_cancel_invalid_download(self) -> None:
        assert self.parser.validate_params("download", "-c abc") is False
        assert self.parser.validate_params("download", "-c 114514 abc") is False

    def test_cancel_all_send(self) -> None:
        assert self.parser.validate_params("send", "-c") is True

    def test_cancel_single_send(self) -> None:
        assert self.parser.validate_params("send", "-c 516751") is True

    def test_cancel_multi_send(self) -> None:
        assert self.parser.validate_params("send", "-c 114514,516751") is True

    def test_cancel_invalid_send(self) -> None:
        assert self.parser.validate_params("send", "-c abc") is False

    def test_cancel_recognized_as_download(self) -> None:
        cmd, args = self.parser.parse("漫画下载 -c 114514")
        assert cmd == "download"
        assert args == "-c 114514"

    def test_cancel_recognized_as_send(self) -> None:
        cmd, args = self.parser.parse("发送 -c 516751")
        assert cmd == "send"
        assert args == "-c 516751"
