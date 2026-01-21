import platform
import signal
import sys
import time
from typing import Any, Dict, Optional

from src.command.executor import CommandExecutor
from src.config.manager import ConfigManager
from src.download.manager import DownloadManager
from src.event.handler import EventHandler
from src.logging.logger_config import logger
from src.message.manager import MessageManager
from src.permission.manager import PermissionManager
from src.platform.compatibility import PlatformChecker
from src.utils.helpers import cleanup_failed_downloads
from src.websocket.client import WebSocketClient


class MangaBot:
    """JMComic QQ机器人主类，整合所有功能模块"""

    VERSION = "3.0.0"

    def __init__(self) -> None:
        """初始化MangaBot机器人"""
        logger.info(f"JMComic QQ机器人 版本 {self.VERSION} 启动中...")

        self._check_platform_compatibility()

        self.config_manager = ConfigManager()
        self.config_manager.load_config()
        self.config_manager.make_download_dir()

        self.permission_manager = PermissionManager(
            group_whitelist=self.config_manager.group_whitelist,
            private_whitelist=self.config_manager.private_whitelist,
            global_blacklist=self.config_manager.global_blacklist,
            delete_permission_user=self.config_manager.delete_permission_user,
        )

        self.ws_client = WebSocketClient(self.config_manager.config_dict)
        self.message_manager = MessageManager(
            config=self.config_manager.config_dict, ws_client=self.ws_client
        )

        self.download_manager = DownloadManager(
            logger_instance=logger,
            config=self.config_manager.config_dict,
            message_sender=self.message_manager.send_message,
            file_sender=self.message_manager.send_file,
        )

        self.command_executor = CommandExecutor(
            message_sender=self.message_manager.send_message,
            file_sender=self.message_manager.send_file,
            download_manager=self.download_manager,
            config=self.config_manager.config_dict,
            self_id_getter=lambda: self.SELF_ID,
            permission_manager=self.permission_manager,
        )

        self.SELF_ID: Optional[str] = None

        def handle_command(
            user_id: str,
            message: str,
            group_id: Optional[str] = None,
            private: bool = True,
        ) -> None:
            self.command_executor.execute_command(user_id, message, group_id, private)

        def get_self_id() -> Optional[str]:
            return self.SELF_ID

        self.event_handler = EventHandler(
            command_handler=handle_command,
            permission_checker=self.permission_manager.check_user_permission,
            self_id_getter=get_self_id,
        )

        def handle_event(data: Dict[str, Any]) -> None:
            if data.get("self_id"):
                self_id_value = data.get("self_id")
                if not self.SELF_ID or self.SELF_ID != self_id_value:
                    self.SELF_ID = self_id_value
                    logger.info(f"从消息中获取到自身ID: {self.SELF_ID}")
            self.event_handler.handle_event(data)

        self.ws_client.set_message_handler(handle_event)
        self.message_manager.set_websocket_client(self.ws_client)

        logger.info("命令解析器初始化完成")

        cleanup_failed_downloads(str(self.config_manager.config_dict["MANGA_DOWNLOAD_PATH"]))

    def _check_platform_compatibility(self) -> None:
        """检查操作系统兼容性"""
        platform_checker = PlatformChecker()
        platform_checker.check_compatibility()

    def connect_websocket(self) -> None:
        """
        连接WebSocket服务器

        Raises:
            RuntimeError: 当连接失败时
        """
        self.ws_client.connect()

    def start_reconnect_manager(self) -> None:
        """启动WebSocket重连管理线程"""
        self.ws_client.start_reconnect_manager()

    def run(self) -> None:
        """运行机器人主函数"""
        logger.info("JMComic下载机器人启动中...")

        self.connect_websocket()
        self.start_reconnect_manager()

        while True:
            time.sleep(1)

    def handle_safe_close(self) -> None:
        """安全关闭机器人，确保所有资源都被正确释放"""
        signal.signal(signal.SIGINT, self._safe_sigint_handler)

    def _get_one_char(self) -> str | None:
        """跨平台获取单个字符输入"""
        if platform.system() != "Linux":
            return input()

        try:
            import termios
            import tty
        except ImportError:
            return input()

        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        return ch

    def _confirm_close(self) -> bool:
        """询问用户是否确认关闭机器人"""
        print("是否确认关闭JMComic下载机器人？(y/n)")
        ch = self._get_one_char()
        return ch.lower() == "y"

    def _safe_sigint_handler(self, signum, frame) -> None:
        """安全处理SIGINT信号"""
        if self._confirm_close():
            try:
                self._close_resources()
                print("JMComic下载机器人已安全关闭")
            except Exception as e:
                logger.error(f"关闭资源时发生严重错误: {e}")
                print(f"关闭过程中发生严重错误，但仍将强制退出: {e}")
            finally:
                signal.signal(signal.SIGINT, signal.SIG_DFL)
                signal.raise_signal(signal.SIGINT)
                return
        else:
            print("关闭操作被取消，程序继续运行")

    def _close_resources(self) -> None:
        """
        关闭所有资源，确保程序安全退出

        Raises:
            RuntimeError: 当关闭资源失败时
        """
        logger.info("开始关闭JMComic下载机器人资源...")

        if self.ws_client.ws is not None:
            try:
                if self.ws_client.is_connected():
                    logger.info("关闭WebSocket连接...")
                    self.ws_client.close()
                    logger.info("WebSocket连接已成功关闭")
                else:
                    logger.info("WebSocket连接已断开，无需关闭")
            except Exception as ws_error:
                logger.error(f"关闭WebSocket连接时出错: {ws_error}")
                raise RuntimeError(ws_error)

        logger.info("停止下载队列处理线程...")
        self.download_manager.queue_running = False
        logger.info("下载队列线程已设置为停止状态")

        if self.download_manager.downloading_mangas:
            logger.info(
                f"清理正在下载的漫画任务: {list(self.download_manager.downloading_mangas.keys())}"
            )
            self.download_manager.downloading_mangas.clear()

        self.ws_client.stop_reconnect_manager()

        print("JMComic下载机器人已安全关闭")
        logger.info("JMComic下载机器人资源关闭完成")
