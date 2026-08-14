"""WebSocket客户端管理器，负责WebSocket连接和重连管理"""

import json
import threading
import time
from typing import Any, Callable, Dict, List, Optional

import websocket

from src.logging.logger_config import logger

# 心跳参数（秒）
# ping_timeout 必须小于 ping_interval，否则库会直接抛出异常
PING_INTERVAL: float = 45.0
PING_TIMEOUT: float = 20.0

# 库内置重连间隔（秒）：断线后等待该时长再尝试重建连接
RECONNECT_INTERVAL: int = 5

# 看门狗轮询间隔（秒）
WATCHDOG_INTERVAL: int = 10


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
        self.watchdog_running: bool = False
        self.watchdog_thread: Optional[threading.Thread] = None
        self.message_handler: Optional[Callable[[Dict[str, Any]], None]] = None

        # run_forever所在的线程，用于区分"库内部重连中"与"连接彻底退出"
        self.run_thread: Optional[threading.Thread] = None
        # 保护连接建立与销毁，防止多个线程同时重建连接
        self._connect_lock: threading.Lock = threading.Lock()
        # 主动关闭标记，设置后看门狗不再重建连接
        self._closing: bool = False

    def connect(self) -> None:
        """
        建立WebSocket连接（幂等）

        重连职责由WebSocketApp.run_forever(reconnect=RECONNECT_INTERVAL)承担：
        库会在同一线程内循环重建socket，重连成功后on_message等回调继续工作，
        无需外部干预。因此本方法在连接已建立或run_forever线程仍存活时会直接返回，
        避免出现多个并发连接。

        Raises:
            RuntimeError: 当连接失败时
        """
        with self._connect_lock:
            if self.is_connected():
                self.logger.debug("WebSocket已连接，跳过重复连接")
                return
            if self.run_thread is not None and self.run_thread.is_alive():
                self.logger.debug("run_forever线程存活中（可能在重连），跳过")
                return

            try:
                ws_url_display = self.config["NAPCAT_WS_URL"]
                if "token=" in ws_url_display:
                    parts = ws_url_display.split("token=")
                    ws_url_display = f"{parts[0]}token=****"

                self.logger.info(f"正在连接WebSocket: {ws_url_display}")
                header: List[str] | Dict[str, str] | None = None
                if self.config["NAPCAT_TOKEN"]:
                    header = {"Authorization": f'Bearer {self.config["NAPCAT_TOKEN"]}'}

                ws_app = websocket.WebSocketApp(
                    self.config["NAPCAT_WS_URL"],
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                    header=header,
                )
                self.ws = ws_app

                self.run_thread = threading.Thread(
                    target=lambda: ws_app.run_forever(
                        ping_interval=PING_INTERVAL,
                        ping_timeout=PING_TIMEOUT,
                        reconnect=RECONNECT_INTERVAL,
                    ),
                    daemon=True,
                    name="ws-run-forever",
                )
                self.run_thread.start()
                self.logger.info("WebSocket连接启动成功，断线后由库自动重连")
            except Exception as e:
                error_msg = f"连接WebSocket失败: {e}"
                self.logger.error(error_msg)
                raise RuntimeError(error_msg) from e

    def start_reconnect_manager(self) -> None:
        """
        启动看门狗线程

        看门狗仅处理run_forever线程意外退出这一极端情况：
        正常情况下库内置重连会在同一线程内持续工作，此处不做干预。
        """
        if self.watchdog_running:
            self.logger.warning("看门狗线程已在运行")
            return

        self.watchdog_running = True
        self.watchdog_thread = threading.Thread(
            target=self._watchdog,
            daemon=True,
            name="ws-watchdog",
        )
        self.watchdog_thread.start()
        self.logger.info("WebSocket看门狗线程已启动")

    def stop_reconnect_manager(self) -> None:
        """停止看门狗线程"""
        self.watchdog_running = False
        if self.watchdog_thread is not None:
            self.watchdog_thread.join(timeout=2)
            self.logger.info("WebSocket看门狗线程已停止")

    def _watchdog(self) -> None:
        """看门狗线程：仅在run_forever线程退出且非主动关闭时重建连接"""
        while self.watchdog_running:
            time.sleep(WATCHDOG_INTERVAL)

            if self._closing:
                continue

            run_alive = False
            with self._connect_lock:
                if self.run_thread is not None:
                    run_alive = self.run_thread.is_alive()

            if run_alive:
                continue

            self.logger.warning("检测到run_forever线程已退出，尝试重新建立连接...")
            try:
                self.connect()
            except RuntimeError as e:
                self.logger.error(f"看门狗重建连接失败: {e}")

    def _on_open(self, _ws: websocket.WebSocketApp) -> None:
        """WebSocket连接打开处理"""
        self.logger.info("WebSocket连接已打开")

    def _on_message(self, _ws: websocket.WebSocketApp, message: str) -> None:
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

    def _on_error(self, _ws: websocket.WebSocketApp, error: Exception) -> None:
        """WebSocket连接错误处理"""
        self.logger.error(f"WebSocket连接错误: {error}")

    def _on_close(
        self,
        _ws: websocket.WebSocketApp,
        close_status_code: int,
        close_msg: str,
    ) -> None:
        """WebSocket连接关闭处理"""
        self.logger.info(f"WebSocket连接已关闭: {close_status_code} - {close_msg}")

    def is_connected(self) -> bool:
        """
        检查WebSocket是否已连接

        Returns:
            bool: WebSocket是否已连接
        """
        return (
            self.ws is not None and self.ws.sock is not None and self.ws.sock.connected
        )

    def close(self) -> None:
        """关闭WebSocket连接，并标记主动关闭以阻止看门狗重建"""
        self._closing = True
        if self.ws is not None:
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
