from typing import Dict, List, Optional, Pattern, Tuple
import re


class CommandParser:
    """
    命令解析器类，负责解析和验证用户输入的命令和参数
    提供标准化的命令处理接口，强化输入校验，防止错误输入
    """

    def __init__(self) -> None:
        """初始化命令解析器，定义命令别名映射和参数验证规则"""
        # 定义命令别名映射，便于统一处理同义命令
        self.command_aliases: Dict[str, List[str]] = {
            "help": ["漫画帮助", "帮助漫画"],
            "download": ["漫画下载", "下载漫画", "下载"],
            "send": ["发送", "发送漫画", "漫画发送"],
            "list": ["漫画列表", "列表漫画"],
            "query": ["查询漫画", "漫画查询"],
            "version": ["漫画版本", "版本", "version"],
            "progress": ["下载进度", "漫画进度", "进度"],
            "test_id": ["测试id"],
            "test_file": ["测试文件"],
            "delete": ["删除", "删除漫画", "漫画删除"],
        }

        # 支持批量操作的命令
        self.batch_commands = {"download", "send", "query", "delete"}

    def parse(self, message: str) -> Tuple[str, str]:
        """
        解析用户输入的消息，提取命令和参数
        :param message: 用户输入的原始消息
        :return: Tuple[str, str]: (标准化的命令名, 参数部分)
        :Raises: ValueError: 当消息为空或格式错误时
        """
        if not message or not message.strip():
            raise ValueError("空消息或仅包含空白字符")

        # 提取命令和参数
        parts = message.strip().split(" ", 1)
        raw_command = parts[0].strip().lower() if parts else ""
        params = parts[1].strip() if len(parts) > 1 else ""

        if not raw_command:
            raise ValueError("未提供命令")

        # 标准化命令名
        standard_command = self._normalize_command(raw_command)

        return standard_command, params

    def _normalize_command(self, raw_command: str) -> str:
        """
        将原始命令名标准化，处理别名

        Args:
            raw_command: 原始命令名

        Returns:
            str: 标准化后的命令名
        """
        # 检查是否是已知命令的别名
        for standard, aliases in self.command_aliases.items():
            if raw_command in aliases:
                return standard

        # 检查是否是标准命令
        if raw_command in self.command_aliases:
            return raw_command

        # 检查是否是欢迎语
        welcome_keywords = ["你好", "hi", "hello", "在吗"]
        if any(keyword in raw_command for keyword in welcome_keywords):
            return "welcome"

        # 未知命令
        return "unknown"

    def validate_params(self, command: str, params: str) -> bool:
        """
        严格验证命令参数是否符合要求

        Args:
            command: 标准化的命令名
            params: 参数部分

        Returns:
            bool: 参数是否有效
        """
        # 清理参数，移除首尾空格
        params = params.strip()

        # 定义不需要参数的命令列表
        no_param_commands = [
            "help",
            "list",
            "version",
            "progress",
            "test_id",
            "test_file",
            "unknown",
        ]

        # 如果命令不需要参数，但提供了参数，返回False
        if command in no_param_commands and params:
            return False

        # 如果命令不需要参数且没有提供参数，返回True
        if command in no_param_commands:
            return True

        # 如果命令需要参数但没有提供参数，返回False
        if command not in no_param_commands and not params:
            return False

        # 批量操作命令的参数验证
        if command in self.batch_commands:
            # 支持 --all 参数
            if params == "--all":
                return True

            # 支持逗号句号分隔的ID列表，模糊匹配中英文符号
            # 允许空格，例如 "350234, 350235, 350236"
            # 先把逗号句号替换为空格，再按空格分割
            if "," in params or "." in params or "，" in params or "。" in params:
                ids = [id.strip() for id in params.replace(",", " ").replace(".", " ").replace("，", " ").replace("。", " ").split() if id.strip()]
                if not ids:
                    return False
                return all(id.isdigit() for id in ids)

            # 支持单个数字ID
            if params.isdigit():
                return True

            return False

        return True

    def get_error_message(self, command: str) -> str:
        """
        获取参数错误时的友好提示消息

        Args:
            command: 标准化的命令名

        Returns:
            str: 错误提示消息
        """
        error_messages = {
            "download": "❌ 参数错误！请提供有效的漫画ID（纯数字）\n"
            "支持格式：\n"
            "  - 单个ID：漫画下载 350234\n"
            "  - 多个ID（逗号分隔）：漫画下载 350234,350235,350236",
            "send": "❌ 参数错误！请提供有效的漫画ID（纯数字）\n"
            "支持格式：\n"
            "  - 单个ID：发送 350234\n"
            "  - 多个ID（逗号分隔）：发送 350234,350235,350236\n"
            "  - 所有已下载漫画：发送 --all",
            "query": "❌ 参数错误！请提供有效的漫画ID（纯数字）\n"
            "支持格式：\n"
            "  - 单个ID：查询漫画 350234\n"
            "  - 多个ID（逗号分隔）：查询漫画 350234,350235,350236\n"
            "  - 所有已下载漫画：查询漫画 --all",
            "delete": "❌ 参数错误！请提供有效的漫画ID（纯数字）\n"
            "支持格式：\n"
            "  - 单个ID：删除 350234\n"
            "  - 多个ID（逗号分隔）：删除 350234,350235,350236\n"
            "  - 所有已下载漫画：删除 --all",
            "help": "❌ 命令格式错误！'漫画帮助'命令不需要额外参数\n直接输入：漫画帮助",
            "list": "❌ 命令格式错误！'漫画列表'命令不需要额外参数\n直接输入：漫画列表",
            "version": "❌ 命令格式错误！'漫画版本'命令不需要额外参数\n直接输入：漫画版本",
            "progress": "❌ 命令格式错误！'下载进度'命令不需要额外参数\n直接输入：下载进度",
            "test_id": "❌ 命令格式错误！'测试id'命令不需要额外参数\n直接输入：测试id",
            "test_file": "❌ 命令格式错误！'测试文件'命令不需要额外参数\n直接输入：测试文件",
            "unknown": "❓ 未知命令，请输入'漫画帮助'查看所有可用命令",
        }

        return error_messages.get(command, "❌ 命令格式错误，请检查输入")
