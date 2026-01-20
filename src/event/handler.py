import re
import time
from typing import Any, Callable, Dict, Optional

from src.logging.logger_config import logger


class EventHandler:
    """事件处理器，负责处理WebSocket接收到的事件"""

    def __init__(
        self,
        command_handler: Callable[[str, str, Optional[str], bool], None],
        permission_checker: Callable[[str, Optional[str], bool], bool],
        self_id_getter: Callable[[], Optional[str]],
    ) -> None:
        """
        初始化事件处理器

        Args:
            command_handler: 命令处理函数
            permission_checker: 权限检查函数
            self_id_getter: 获取自身ID的函数
        """
        self.command_handler = command_handler
        self.permission_checker = permission_checker
        self.self_id_getter = self_id_getter
        self.logger = logger
        self.self_id: Optional[str] = None

    def handle_event(self, data: Dict[str, Any]) -> None:
        """
        处理WebSocket接收到的事件

        Args:
            data: 事件数据字典

        Raises:
            ValueError: 当事件数据格式错误时
        """
        try:
            event_id = hash(str(data))
            timestamp = data.get("time", time.time())

            post_type = data.get("post_type", "UNKNOWN")
            event_type = data.get("meta_event_type", data.get("message_type", "UNKNOWN"))

            self.logger.info(f"收到事件 [ID:{event_id}] - 类型: {post_type}, {event_type}, 时间戳: {timestamp}")
            self.logger.debug(f"事件详细数据: {str(data)[:200]}...")

            self_id_value = data.get("self_id")
            if self_id_value:
                if not self.self_id or self.self_id != self_id_value:
                    self.self_id = self_id_value
                    self.logger.info(f"从消息中获取到自身ID: {self.self_id}")

        except Exception as e:
            error_msg = f"处理事件时出错: {str(e)}"
            self.logger.error(error_msg)
            raise ValueError(error_msg)

        if data.get("post_type") == "meta_event":
            return

        if data.get("post_type") == "message":
            self._handle_message(data)

    def _handle_message(self, data: Dict[str, Any]) -> None:
        """
        处理消息事件

        Args:
            data: 消息数据字典
        """
        message_type = data.get("message_type")

        if message_type == "private":
            self._handle_private_message(data)
        elif message_type == "group":
            self._handle_group_message(data)

    def _handle_private_message(self, data: Dict[str, Any]) -> None:
        """
        处理私聊消息

        Args:
            data: 消息数据字典
        """
        user_id = str(data.get("user_id", ""))
        message = data.get("raw_message", "")

        if not user_id or not message:
            self.logger.warning("私聊消息缺少必要字段")
            return

        try:
            self.permission_checker(user_id, private=True)
        except ValueError as e:
            self.logger.warning(f"拒绝处理私信 - 用户 {user_id} 权限不足: {e}")
            return

        self.logger.info(f"收到私聊消息 - 用户{user_id}: {message}")
        try:
            self.command_handler(user_id, message, private=True)
            self.logger.debug(f"私聊消息处理完成 - 用户{user_id}")
        except Exception as e:
            self.logger.error(f"处理私聊消息时出错: {e}")
            raise

    def _handle_group_message(self, data: Dict[str, Any]) -> None:
        """
        处理群消息

        Args:
            data: 消息数据字典
        """
        group_id = str(data.get("group_id", ""))
        user_id = str(data.get("user_id", ""))
        message = data.get("raw_message", "")

        if not group_id or not user_id or not message:
            self.logger.warning("群消息缺少必要字段")
            return

        try:
            self.permission_checker(user_id, group_id=group_id, private=False)
        except ValueError as e:
            self.logger.warning(f"拒绝处理群消息 - 群组 {group_id} 用户 {user_id} 权限不足: {e}")
            return

        self.logger.info(f"收到群消息 - 群{group_id} 用户{user_id}: {message}")

        has_reply_format = "[CQ:reply," in message
        message = re.sub(r"\[CQ:reply,id=\d+\]", "", message)

        if has_reply_format:
            self.logger.debug("CQ:reply格式已从消息中移除")

        if not self._is_at_self(message):
            self.logger.debug("未被@，忽略消息")
            return

        message = self._remove_at_mention(message)
        self.logger.info(f"收到群消息并被@ - 群{group_id} 用户{user_id}: {message}")
        try:
            self.command_handler(user_id, message, group_id=group_id, private=False)
        except Exception as e:
            self.logger.error(f"处理群消息时出错: {e}")
            raise

    def _is_at_self(self, message: str) -> bool:
        """
        检查消息中是否@了机器人

        Args:
            message: 消息内容

        Returns:
            bool: 是否@了机器人
        """
        if not self.self_id:
            self.logger.warning("SELF_ID未初始化，无法检测@状态")
            return False

        return f"@{self.self_id}" in message or f"[CQ:at,qq={self.self_id}]" in message

    def _remove_at_mention(self, message: str) -> str:
        """
        从消息中移除@提及

        Args:
            message: 消息内容

        Returns:
            移除@提及后的消息
        """
        message = message.replace(f"[CQ:at,qq={self.self_id}]", "")
        message = message.replace(f"@{self.self_id}", "")
        message = message.strip()
        return message

    def get_self_id(self) -> Optional[str]:
        """
        获取机器人自身的ID

        Returns:
            机器人自身的ID，如果未获取到则返回None
        """
        return self.self_id
