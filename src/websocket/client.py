import json
import threading
import time
from typing import Any, Callable, Dict, List, Optional

import websocket

from src.logging.logger_config import logger


class WebSocketClient:
    """WebSocket客户端管理器，负责WebSocket连接和重连管理"""

    def __init__(self, config: Dict[str, Any]) -> None:
        """
        初始化WebSocket客户端

        Args:
            config: 配置字典，包含NAPCAT_WS_URL和NAPCAT_TOKEN
        """
        self.config = config
        self.ws: Optional[websocket.WebSocketApp] = None
        self.logger = logger
        self.reconnect_running = False
        self.reconnect_thread: Optional[threading.Thread] = None
        self.message_handler: Optional[Callable[[Dict[str, Any]], None]] = None

    def connect(self) -> None:
        """
        连接WebSocket服务器

        Raises:
            RuntimeError: 当连接失败时
        """
        try:
            ws_url_display = self.config["NAPCAT_WS_URL"]
            if "token=" in ws_url_display:
                parts = ws_url_display.split("token=")
                ws_url_display = f"{parts[0]}token=****"

            self.logger.info(f"正在连接WebSocket: {ws_url_display}")
            header: List[str] | Dict[str, str] | None = None
            if self.config["NAPCAT_TOKEN"]:
                header = {"Authorization": f'Bearer {self.config["NAPCAT_TOKEN"]}'}

            self.ws = websocket.WebSocketApp(
                self.config["NAPCAT_WS_URL"],
                on_open=self._on_open,
                on_message=self._on_message,
                on_error=self._on_error,
                on_close=self._on_close,
                header=header,
            )

            threading.Thread(
                target=lambda: self.ws.run_forever(ping_interval=30, ping_timeout=10, reconnect=5),
                daemon=True,
            ).start()
            self.logger.info("WebSocket连接启动成功，将自动尝试重连")
        except Exception as e:
            error_msg = f"连接WebSocket失败: {e}"
            self.logger.error(error_msg)
            raise RuntimeError(error_msg)

    def start_reconnect_manager(self) -> None:
        """启动WebSocket重连管理线程"""
        if self.reconnect_running:
            self.logger.warning("重连管理器已在运行")
            return

        self.reconnect_running = True
        self.reconnect_thread = threading.Thread(target=self._reconnect_manager, daemon=True)
        self.reconnect_thread.start()
        self.logger.info("WebSocket重连管理器已启动")

    def stop_reconnect_manager(self) -> None:
        """停止WebSocket重连管理线程"""
        self.reconnect_running = False
        if self.reconnect_thread:
            self.reconnect_thread.join(timeout=2)
            self.logger.info("WebSocket重连管理器已停止")

    def _reconnect_manager(self) -> None:
        """WebSocket重连管理线程"""
        while self.reconnect_running:
            time.sleep(10)

            if self.ws and (not self.ws.sock or not self.ws.sock.connected):
                self.logger.info("检测到WebSocket未连接，尝试重新连接...")
                try:
                    if self.ws:
                        self.ws.close()
                    self.connect()
                except Exception as e:
                    self.logger.error(f"重连WebSocket失败: {e}")

    def _on_open(self, ws: websocket.WebSocketApp) -> None:
        """WebSocket连接打开处理"""
        self.logger.info("WebSocket连接已打开")

    def _on_message(self, ws: websocket.WebSocketApp, message: str) -> None:
        """WebSocket消息处理"""
        try:
            self.logger.info(f"收到WebSocket消息: {message[:100]}...")
            data = json.loads(message)
            
            # 如果有设置消息处理器，则调用它
            if self.message_handler:
                self.message_handler(data)
        except json.JSONDecodeError as e:
            self.logger.error(f"解析WebSocket消息失败: {e}")
            raise

    def _on_error(self, ws: websocket.WebSocketApp, error: Exception) -> None:
        """WebSocket连接错误处理"""
        self.logger.error(f"WebSocket连接错误: {error}")

    def _on_close(self, ws: websocket.WebSocketApp, close_status_code: int, close_msg: str) -> None:
        """WebSocket连接关闭处理"""
        self.logger.info(f"WebSocket连接已关闭: {close_status_code} - {close_msg}")

    def is_connected(self) -> bool:
        """
        检查WebSocket是否已连接

        Returns:
            bool: WebSocket是否已连接
        """
        return self.ws is not None and self.ws.sock is not None and self.ws.sock.connected

    def close(self) -> None:
        """关闭WebSocket连接"""
        if self.ws:
            self.ws.close()
            self.logger.info("WebSocket连接已关闭")

    def set_message_handler(self, handler: Callable[[Dict[str, Any]], None]) -> None:
        """
        设置消息处理器

        Args:
            handler: 消息处理函数，接收解析后的JSON数据
        """
        self.message_handler = handler
        self.logger.info("WebSocket消息处理器已设置")
