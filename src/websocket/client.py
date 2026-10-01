"""WebSocket客户端管理器，负责WebSocket连接和重连管理"""

from typing import Any, Callable, Dict, List, Optional

import json
import threading

import websocket

from src.logging.logger_config import logger

# 心跳参数（秒）
# ping_timeout 必须小于 ping_interval，否则库会直接抛出异常
PING_INTERVAL: float = 90.0
PING_TIMEOUT: float = 45.0

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
        self._watchdog_stop_event: threading.Event = threading.Event()
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

    def request_reconnect(self) -> bool:
        """请求断开并重建 NapCat 连接。

        关闭当前连接后由库内重连或看门狗恢复；连接从未建立时直接发起连接。
        返回是否已发出重连请求（正在关闭时返回 False）。

        Returns:
            bool: 是否已发出重连请求
        """
        if self._closing:
            return False
        with self._connect_lock:
            current_ws = self.ws
            run_thread = self.run_thread
        if current_ws is not None:
            self.logger.info("收到手动重连请求，正在断开当前连接")
            current_ws.close()
        if run_thread is not None and run_thread.is_alive():
            # 旧连接线程退出后由看门狗（轮询间隔 10 秒）重建连接
            return True
        threading.Thread(
            target=self._reconnect_worker,
            daemon=True,
            name="ws-manual-reconnect",
        ).start()
        return True

    def _reconnect_worker(self) -> None:
        """手动重连工作线程：失败仅记录，交由看门狗继续重试。"""
        try:
            self.connect()
        except RuntimeError as error:
            self.logger.error(f"手动重连失败: {error}")

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
        self._watchdog_stop_event.clear()
        self.watchdog_thread = threading.Thread(
            target=self._watchdog,
            daemon=True,
            name="ws-watchdog",
        )
        self.watchdog_thread.start()
        self.logger.info("WebSocket看门狗线程已启动")

    def stop_reconnect_manager(self, timeout: float = 1.0) -> bool:
        """停止看门狗线程并立即唤醒其等待

        Args:
            timeout: 等待线程退出的最长秒数

        Returns:
            bool: 看门狗线程是否已退出
        """
        self.watchdog_running = False
        self._watchdog_stop_event.set()
        if self.watchdog_thread is not None:
            self.watchdog_thread.join(timeout=timeout)
            if self.watchdog_thread.is_alive():
                self.logger.warning("WebSocket看门狗线程未在限定时间内停止")
                return False
        self.logger.info("WebSocket看门狗线程已停止")
        return True

    def _watchdog(self) -> None:
        """看门狗线程：仅在run_forever线程退出且非主动关闭时重建连接"""
        while not self._watchdog_stop_event.wait(WATCHDOG_INTERVAL):

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
            # 原始消息内容较长，属于高频噪音，降级到 DEBUG 仅在文件日志中保留
            self.logger.debug(f"收到WebSocket消息: {message[:100]}...")
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

    def close(self, timeout: float = 1.0) -> bool:
        """关闭连接、看门狗和 run_forever 线程

        Args:
            timeout: 等待 run_forever 线程退出的最长秒数

        Returns:
            bool: 所有 WebSocket 后台线程是否已退出
        """
        self._closing = True
        watchdog_stopped = self.stop_reconnect_manager(timeout=timeout)
        if self.ws is not None:
            self.ws.close()
        if (
            self.run_thread is not None
            and self.run_thread is not threading.current_thread()
        ):
            self.run_thread.join(timeout=timeout)
            if self.run_thread.is_alive():
                self.logger.warning("WebSocket运行线程未在限定时间内停止")
                return False
        self.logger.info("WebSocket连接与后台线程已关闭")
        return watchdog_stopped

    def set_message_handler(self, handler: Callable[[Dict[str, Any]], None]) -> None:
        """
        设置消息处理器

        Args:
            handler: 消息处理函数，接收解析后的JSON数据
        """
        self.message_handler = handler
        self.logger.info("WebSocket消息处理器已设置")
