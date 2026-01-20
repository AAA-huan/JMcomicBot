import json
import os
import time
from typing import Any, Dict, Optional

import websocket

from src.logging.logger_config import logger


class MessageManager:
    """消息管理器，负责发送文本消息和文件"""

    def __init__(self, config: Dict[str, Any], ws_client: Optional[websocket.WebSocketApp] = None) -> None:
        """
        初始化消息管理器

        Args:
            config: 配置字典，包含NAPCAT_TOKEN等信息
            ws_client: WebSocket客户端实例
        """
        self.config = config
        self.ws = ws_client
        self.logger = logger

    def set_websocket_client(self, ws_client: websocket.WebSocketApp) -> None:
        """
        设置WebSocket客户端

        Args:
            ws_client: WebSocket客户端实例
        """
        self.ws = ws_client

    def send_message(
        self,
        user_id: str,
        message: str,
        group_id: Optional[str] = None,
        private: bool = True,
    ) -> None:
        """
        发送文本消息

        Args:
            user_id: 用户ID
            message: 要发送的消息内容
            group_id: 群组ID（群聊时提供）
            private: 是否为私聊

        Raises:
            RuntimeError: 当WebSocket连接未建立时
        """
        payload: Dict[str, Any]
        if private:
            payload = {
                "action": "send_private_msg",
                "params": {"user_id": user_id, "message": message},
            }
        else:
            payload = {
                "action": "send_group_msg",
                "params": {"group_id": group_id, "message": message},
            }

        if self.config.get("NAPCAT_TOKEN"):
            payload["params"]["access_token"] = self.config["NAPCAT_TOKEN"]

        if self._is_websocket_connected():
            message_json: str = json.dumps(payload)
            self.logger.info(f"准备发送 - 用户:{user_id}, 类型:{'私聊' if private else '群聊'}")
            self.ws.send(message_json)
            self.logger.info(f"发送成功: {message[:20]}...")
        else:
            error_msg = "WebSocket连接未建立，消息发送失败"
            self.logger.warning(error_msg)
            raise RuntimeError(error_msg)

    def send_file(
        self,
        user_id: str,
        file_path: str,
        group_id: Optional[str] = None,
        private: bool = True,
    ) -> None:
        """
        发送文件

        Args:
            user_id: 用户ID
            file_path: 文件路径
            group_id: 群组ID（群聊时提供）
            private: 是否为私聊

        Raises:
            FileNotFoundError: 当文件不存在时
            PermissionError: 当文件不可读时
            RuntimeError: 当WebSocket连接未建立时
        """
        self.logger.debug(f"准备发送文件: {file_path}, 用户ID: {user_id}, 群ID: {group_id}, 私聊模式: {private}")

        if not os.path.exists(file_path):
            error_msg = f"文件不存在: {os.path.basename(file_path)}"
            self.logger.error(error_msg)
            raise FileNotFoundError(error_msg)

        if not os.access(file_path, os.R_OK):
            error_msg = f"文件不可读: {os.path.basename(file_path)}"
            self.logger.error(error_msg)
            raise PermissionError(error_msg)

        file_name = os.path.basename(file_path)
        self.logger.debug(f"原始文件名: {file_name}")

        file_path_to_send = os.path.abspath(file_path)
        self.logger.debug(f"使用原始绝对路径: {file_path_to_send}")

        self.logger.info("使用消息段数组方式发送文件")

        message_segments = [{"type": "file", "data": {"file": file_path_to_send, "name": file_name}}]

        if private:
            payload = {
                "action": "send_private_msg",
                "params": {"user_id": user_id, "message": message_segments},
            }
        else:
            payload = {
                "action": "send_group_msg",
                "params": {"group_id": group_id, "message": message_segments},
            }

        if self.config.get("NAPCAT_TOKEN"):
            payload["params"]["access_token"] = self.config["NAPCAT_TOKEN"]

        if self._is_websocket_connected():
            message_json = json.dumps(payload)
            self.logger.debug(f"发送消息段数组文件: {message_json}")
            self.ws.send(message_json)
            self.logger.info(f"文件发送请求已发送: {file_name}")
            time.sleep(1)
        else:
            error_msg = "WebSocket连接未建立，文件发送失败"
            self.logger.warning(error_msg)
            raise RuntimeError(error_msg)

    def _is_websocket_connected(self) -> bool:
        """
        检查WebSocket是否已连接

        Returns:
            bool: WebSocket是否已连接
        """
        return self.ws is not None and self.ws.sock is not None and self.ws.sock.connected
