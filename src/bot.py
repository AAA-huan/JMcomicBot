"""JMComic QQ 机器人的组件组装与运行入口"""

from typing import Any, Dict, Optional

import platform
import signal
import sys
import threading

from src.command.executor import CommandExecutor
from src.config.manager import ConfigManager
from src.database.database import DatabaseManager
from src.database.repositories import (
    MangaRepository,
    MangaTagRepository,
    PermissionRepository,
    TaskLogRepository,
    UserGroupRepository,
)
from src.download.manager import DownloadManager
from src.event.handler import EventHandler
from src.logging.logger_config import logger
from src.message.manager import MessageManager
from src.permission.manager import PermissionManager
from src.platform.compatibility import PlatformChecker
from src.utils.helpers import cleanup_failed_downloads
from src.utils.name_cache import NameCache
from src.websocket.client import WebSocketClient


class MangaBot:
    """JMComic QQ机器人主类，整合所有功能模块"""

    VERSION = "3.2.5"

    def __init__(self) -> None:
        """初始化MangaBot机器人"""
        logger.info(f"JMComic QQ机器人 版本 {self.VERSION} 启动中...")

        self._shutdown_event: threading.Event = threading.Event()
        self._close_lock: threading.Lock = threading.Lock()
        self._resources_closed: bool = False

        self._check_platform_compatibility()

        self.config_manager = ConfigManager()
        self.config_manager.load_config()
        self.config_manager.make_download_dir()

        # 初始化数据库管理器（SQLite），并创建各数据仓储
        self.database_manager = DatabaseManager(
            db_path=str(self.config_manager.config_dict["DB_PATH"]),
            echo=bool(self.config_manager.config_dict["DB_ECHO"]),
        )
        self.database_manager.init_db()

        self.manga_repo = MangaRepository(
            self.database_manager,
            download_root=str(self.config_manager.config_dict["MANGA_DOWNLOAD_PATH"]),
        )
        self.task_log_repo = TaskLogRepository(self.database_manager)
        self.user_group_repo = UserGroupRepository(self.database_manager)
        self.permission_repo = PermissionRepository(self.database_manager)
        self.tag_repo = MangaTagRepository(self.database_manager)

        # 挂载名称缓存持久化仓储
        NameCache.get_instance().attach_user_group_repo(self.user_group_repo)

        self.permission_manager = PermissionManager(
            permission_repo=self.permission_repo,
            seed_group_whitelist=self.config_manager.group_whitelist,
            seed_private_whitelist=self.config_manager.private_whitelist,
            seed_global_blacklist=self.config_manager.global_blacklist,
            seed_delete_permission_user=self.config_manager.delete_permission_user,
        )

        self.ws_client = WebSocketClient(self.config_manager.config_dict)
        self.message_manager = MessageManager(
            config=self.config_manager.config_dict,
            ws_client=self.ws_client,
            task_log_repo=self.task_log_repo,
        )

        self.download_manager = DownloadManager(
            logger_instance=logger,
            config=self.config_manager.config_dict,
            message_sender=self.message_manager.send_message,
            file_sender=self.message_manager.send_file,
            manga_repo=self.manga_repo,
            task_log_repo=self.task_log_repo,
            tag_repo=self.tag_repo,
        )

        self.command_executor = CommandExecutor(
            message_sender=self.message_manager.send_message,
            file_sender=self.message_manager.send_file,
            download_manager=self.download_manager,
            config=self.config_manager.config_dict,
            self_id_getter=lambda: self.SELF_ID,
            permission_manager=self.permission_manager,
            resend_handler=self.message_manager.resend_pending_files,
            send_status_provider=self.message_manager.get_send_queue_status,
            manga_repo=self.manga_repo,
            tag_repo=self.tag_repo,
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

        self._cleanup_download_directory()

        self._backfill_manga_tags()

    def _cleanup_download_directory(self) -> None:
        """清理失败下载；目录意外缺失时记录原因并继续启动"""
        download_path = str(self.config_manager.config_dict["MANGA_DOWNLOAD_PATH"])
        try:
            cleanup_failed_downloads(download_path)
        except FileNotFoundError as e:
            logger.warning(f"启动清理已跳过: {e}")

    def _backfill_manga_tags(self) -> None:
        """回填已有漫画的标签到 tag 表（幂等，用于存量数据的标签查询兜底）"""
        try:
            count = self.tag_repo.sync_from_manga()
            if count:
                logger.info(f"标签表回填完成：共同步 {count} 条漫画标签记录")
        except Exception as e:
            logger.error(f"标签表回填失败: {e}")

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

        self._shutdown_event.wait()

    def handle_safe_close(self) -> None:
        """安全关闭机器人，确保所有资源都被正确释放"""
        signal.signal(signal.SIGINT, self._safe_sigint_handler)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, self._safe_sigterm_handler)

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
        if not sys.stdin.isatty():
            logger.info("当前无交互式终端，直接执行关闭")
            return True
        print("是否确认关闭JMComic下载机器人？(y/n)")
        try:
            ch = self._get_one_char()
        except (EOFError, OSError) as e:
            logger.warning(f"无法读取关闭确认，直接执行关闭: {e}")
            return True
        return ch is not None and ch.lower() == "y"

    def _safe_sigint_handler(self, _signum: int, _frame: Any) -> None:
        """处理 SIGINT：确认后仅请求关闭，由主流程统一释放资源"""
        if self._confirm_close():
            signal.signal(signal.SIGINT, signal.SIG_DFL)
            self.request_shutdown("收到用户中断信号")
        else:
            print("关闭操作被取消，程序继续运行")

    def _safe_sigterm_handler(self, _signum: int, _frame: Any) -> None:
        """处理服务管理器发送的 SIGTERM，不进行交互确认"""
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        self.request_shutdown("收到终止信号")

    def request_shutdown(self, reason: str = "") -> None:
        """请求主循环退出，重复调用不会产生额外副作用"""
        if reason:
            logger.info(f"请求关闭机器人: {reason}")
        self._shutdown_event.set()

    def close(self) -> None:
        """
        关闭所有资源，确保程序安全退出

        单个组件关闭失败不会阻断其他资源释放；重复调用不会重复关闭。
        """
        with self._close_lock:
            if self._resources_closed:
                return
            self._resources_closed = True

        self._shutdown_event.set()
        logger.info("开始关闭JMComic下载机器人资源...")

        close_steps = (
            ("WebSocket", self.ws_client.close),
            ("文件发送队列", self.message_manager.stop),
            ("下载队列", self.download_manager.stop),
            ("SQLite数据库", self.database_manager.close),
        )
        close_errors = []
        for name, close_step in close_steps:
            try:
                result = close_step()
                if result is False:
                    logger.warning(f"{name} 未在限定时间内完全停止")
            except Exception as e:  # pylint: disable=broad-exception-caught
                close_errors.append(f"{name}: {e}")
                logger.error(f"关闭{name}时出错: {e}")

        if close_errors:
            logger.error(f"机器人关闭完成，但存在异常: {'; '.join(close_errors)}")
            print("JMComic下载机器人已关闭，但部分资源清理失败，请查看日志")
        else:
            logger.info("JMComic下载机器人资源关闭完成")
            print("JMComic下载机器人已关闭")

    def _close_resources(self) -> None:
        """兼容旧调用入口，实际关闭逻辑由 close 统一处理"""
        self.close()
