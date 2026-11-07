"""JMComic QQ 机器人的组件组装与运行入口"""

from typing import Any, Dict, List, Optional

import platform
import select
import signal
import sys
import threading
import time

from src.command.executor import CommandExecutor
from src.config.manager import ConfigManager
from src.database.database import DatabaseManager
from src.database.models import utc_now
from src.database.repositories import (
    AuditEventRepository,
    FavoriteRepository,
    JmFavoriteRepository,
    MangaBlacklistRepository,
    MangaRepository,
    MangaTagRepository,
    OperationTaskRepository,
    PermissionRepository,
    ReadingProgressRepository,
    ReadingSettingRepository,
    ScanRecordRepository,
    SettingHistoryRepository,
    SettingRepository,
    TaskEventRepository,
    TaskLogRepository,
    UserGroupRepository,
    WebAdminRepository,
    WebSessionRepository,
)
from src.download.manager import DownloadManager
from src.download.progress import DownloadProgressTracker
from src.event.handler import EventHandler
from src.logging.logger_config import logger
from src.message.manager import MessageManager
from src.permission.manager import PermissionManager
from src.platform.compatibility import PlatformChecker
from src.service import (
    CleanupService,
    DataMigrationService,
    DownloadQueueService,
    MangaBlacklistService,
    MangaService,
    OperationContext,
    OperationTaskService,
    OptionFileService,
    PageImageService,
    PermissionService,
    ReadingProgressService,
    ReadingSettingService,
    RepairService,
    ScanService,
    SettingsService,
    VerifyService,
)
from src.service.admin_qq_service import AdminQQService
from src.service.favorite_service import FavoriteService
from src.service.jm_collect_service import JmCollectService
from src.service.jm_favorite_service import JmFavoriteService
from src.service.jm_search_service import JmSearchService
from src.service.query_service import (
    AuditQueryService,
    MangaQueryService,
    TaskQueryService,
)
from src.service.recovery_prompt import RecoveryPrompt
from src.service.results import TaskResult
from src.service.system_service import SystemService
from src.service.web_auth_service import WebAuthService
from src.utils.helpers import cleanup_failed_downloads
from src.utils.name_cache import NameCache
from src.web import WebServer, create_web_app
from src.web.dependencies import WebDependencies
from src.web.events.bus import WebEventBus
from src.websocket.client import WebSocketClient


class MangaBot:  # pylint: disable=too-many-instance-attributes
    """JMComic QQ机器人主类，整合所有功能模块"""

    VERSION = "3.2.5"

    def __init__(self) -> None:
        """初始化MangaBot机器人"""
        logger.info(f"JMComic QQ机器人 版本 {self.VERSION} 启动中...")

        self._shutdown_event: threading.Event = threading.Event()
        self._close_lock: threading.Lock = threading.Lock()
        self._resources_closed: bool = False
        # 中断恢复询问：启动时只检测任务，等 Web/终端通道就绪后再决定
        self.recovery_prompt: Optional[RecoveryPrompt] = None
        self._pending_recovery_tasks: List[TaskResult] = []
        self._recovery_thread: Optional[threading.Thread] = None
        self._started_at = utc_now()
        # 一键重启标记：close() 完成后由 main 判断是否拉起新进程
        self.restart_requested: bool = False

        self._check_platform_compatibility()

        self.config_manager = ConfigManager()
        self.config_manager.load_config()
        self.config_manager.make_download_dir()

        # 初始化数据库管理器（SQLite），并创建各数据仓储
        self.database_manager = DatabaseManager(
            db_path=str(self.config_manager.config_dict["DB_PATH"]),
            echo=bool(self.config_manager.config_dict["DB_ECHO"]),
            download_root=str(self.config_manager.config_dict["MANGA_DOWNLOAD_PATH"]),
        )
        self.database_manager.init_db()

        self.manga_repo = MangaRepository(
            self.database_manager,
            download_root=str(self.config_manager.config_dict["MANGA_DOWNLOAD_PATH"]),
        )
        self.manga_blacklist_repo = MangaBlacklistRepository(self.database_manager)
        self.task_log_repo = TaskLogRepository(self.database_manager)
        self.user_group_repo = UserGroupRepository(self.database_manager)
        self.permission_repo = PermissionRepository(self.database_manager)
        self.tag_repo = MangaTagRepository(self.database_manager)
        self.operation_task_repo = OperationTaskRepository(self.database_manager)
        self.task_event_repo = TaskEventRepository(self.database_manager)
        self.audit_event_repo = AuditEventRepository(self.database_manager)
        self.favorite_repo = FavoriteRepository(self.database_manager)
        self.web_admin_repo = WebAdminRepository(self.database_manager)
        self.web_session_repo = WebSessionRepository(self.database_manager)
        self.scan_record_repo = ScanRecordRepository(self.database_manager)
        self.reading_progress_repo = ReadingProgressRepository(self.database_manager)
        self.reading_setting_repo = ReadingSettingRepository(self.database_manager)
        self.setting_repo = SettingRepository(self.database_manager)
        self.setting_history_repo = SettingHistoryRepository(self.database_manager)
        # WebSocket 事件总线：任务等业务线程发布，Web 连接订阅
        self.event_bus = WebEventBus()
        # 下载进度采集器：下载线程写入，WebSocket 推送与 REST 快照共用
        self.download_progress_tracker = DownloadProgressTracker(self.event_bus.publish)
        self.operation_task_service = OperationTaskService(
            self.operation_task_repo,
            self.task_event_repo,
            self.audit_event_repo,
            event_publisher=self.event_bus,
        )
        # 启动恢复：先记录遗留活动下载，再把运行中任务标记中断；
        # 下载管理器就绪后复用原任务记录重新入队
        legacy_download_tasks = self.operation_task_service.list_active_downloads()
        interrupted_download_tasks = self.operation_task_service.recover_interrupted()
        if interrupted_download_tasks:
            logger.warning(
                f"启动时已中断 {len(interrupted_download_tasks)} 个遗留运行下载任务"
            )

        # 运行时配置服务先于组件创建，加载数据库动态覆盖值
        self.settings_service = SettingsService(
            self.setting_repo,
            self.setting_history_repo,
            self.audit_event_repo,
            self.config_manager,
        )
        persisted_settings = self.settings_service.load_persisted()
        if persisted_settings:
            logger.info(f"已应用 {persisted_settings} 项数据库动态配置")

        # option.yml 网页编辑服务，路径与 download_manager 的相对路径约定一致
        self.option_file_service = OptionFileService(
            option_file_path="option.yml",
            audit_repository=self.audit_event_repo,
        )

        self.cleanup_service = CleanupService(
            self.operation_task_repo,
            self.audit_event_repo,
        )
        self._cleanup_thread: Optional[threading.Thread] = None
        self._cleanup_stop_event: threading.Event = threading.Event()

        # 挂载名称缓存持久化仓储
        NameCache.get_instance().attach_user_group_repo(self.user_group_repo)

        self.permission_manager = PermissionManager(
            permission_repo=self.permission_repo,
            admin_repository=self.web_admin_repo,
            seed_group_whitelist=self.config_manager.group_whitelist,
            seed_private_whitelist=self.config_manager.private_whitelist,
            seed_global_blacklist=self.config_manager.global_blacklist,
            seed_delete_permission_user=self.config_manager.delete_permission_user,
        )
        self.permission_service = PermissionService(
            self.permission_manager,
            self.audit_event_repo,
            self.user_group_repo,
        )

        self.ws_client = WebSocketClient(self.config_manager.config_dict)
        self.message_manager = MessageManager(
            config=self.config_manager.config_dict,
            ws_client=self.ws_client,
            task_log_repo=self.task_log_repo,
            settings_service=self.settings_service,
        )

        self.download_manager = DownloadManager(
            logger_instance=logger,
            config=self.config_manager.config_dict,
            message_sender=self.message_manager.send_message,
            file_sender=self.message_manager.send_file,
            manga_repo=self.manga_repo,
            task_log_repo=self.task_log_repo,
            tag_repo=self.tag_repo,
            operation_task_service=self.operation_task_service,
            send_conflict_checker=self.message_manager.is_manga_sending,
            favorite_repository=self.favorite_repo,
            progress_tracker=self.download_progress_tracker,
            settings_service=self.settings_service,
        )
        # 启动续传：运行中任务已在上方标记中断，这里只把原记录合并为待恢复
        # 列表；实际入队推迟到 WebUI/终端询问通道就绪之后
        interrupted_by_id = {task.id: task for task in interrupted_download_tasks}
        self._pending_recovery_tasks = [
            interrupted_by_id.get(task.id, task) for task in legacy_download_tasks
        ]
        if self._pending_recovery_tasks:
            logger.info(
                f"检测到 {len(self._pending_recovery_tasks)} 个遗留下载任务，"
                "等待恢复询问"
            )
        # 漫画黑名单先于删除服务构造；删除联动通过 provider 延迟取得 MangaService
        self.manga_blacklist_service = MangaBlacklistService(
            blacklist_repository=self.manga_blacklist_repo,
            manga_repository=self.manga_repo,
            audit_repository=self.audit_event_repo,
            task_service=self.operation_task_service,
            manga_service_provider=lambda: self.manga_service,
            delete_binding=bool(
                self.config_manager.config_dict["BLACKLIST_DELETE_BINDING"]
            ),
        )
        self.download_service = DownloadQueueService(
            self.download_manager,
            self.operation_task_service,
            blacklist_service=self.manga_blacklist_service,
            downloaded_checker=self.manga_repo,
        )
        self.scan_service = ScanService(
            self.manga_repo,
            self.tag_repo,
            self.scan_record_repo,
            self.operation_task_service,
            download_root=str(self.config_manager.config_dict["MANGA_DOWNLOAD_PATH"]),
        )
        self.repair_service = RepairService(
            self.manga_repo,
            self.tag_repo,
            self.scan_record_repo,
            self.operation_task_service,
            download_root=str(self.config_manager.config_dict["MANGA_DOWNLOAD_PATH"]),
        )
        # 数据迁移服务：整库导出/导入，路径配置只用于生成导入预览差异提示
        self.data_migration_service = DataMigrationService(
            self.database_manager,
            self.audit_event_repo,
            db_path_config=str(self.config_manager.config_dict["DB_PATH"]),
            manga_download_path=str(
                self.config_manager.config_dict["MANGA_DOWNLOAD_PATH"]
            ),
        )
        # 统一删除服务：QQ 删除命令与 Web 写接口共用同一套删除流程
        self.manga_service = MangaService(
            manga_repository=self.manga_repo,
            tag_repository=self.tag_repo,
            audit_repository=self.audit_event_repo,
            operation_task_service=self.operation_task_service,
            download_root=str(self.config_manager.config_dict["MANGA_DOWNLOAD_PATH"]),
            download_conflict_checker=self.download_manager.is_download_active,
            send_conflict_checker=self.message_manager.is_manga_sending,
            favorite_repository=self.favorite_repo,
            blacklist_service=self.manga_blacklist_service,
            blacklist_delete_binding=bool(
                self.config_manager.config_dict["BLACKLIST_DELETE_BINDING"]
            ),
        )
        # 阅读进度服务：WebUI 阅读器读写，文件存在性与页数补齐在服务层校验
        self.reading_progress_service = ReadingProgressService(
            self.reading_progress_repo,
            self.manga_repo,
        )
        # 阅读设置服务：设置页与阅读器工具栏共用，按管理员账户保存一份
        self.reading_setting_service = ReadingSettingService(
            self.reading_setting_repo,
            self.audit_event_repo,
        )
        # 页面图片服务：从图片型 PDF 抽取嵌入图，内存缓存不落盘
        self.page_image_service = PageImageService()
        self.web_auth_service = WebAuthService(
            self.web_admin_repo,
            self.web_session_repo,
            self.audit_event_repo,
            int(self.config_manager.config_dict["WEBUI_SESSION_HOURS"]),
        )
        self.favorite_service = FavoriteService(
            self.favorite_repo, self.audit_event_repo
        )
        self.jm_favorite_service = JmFavoriteService(
            JmFavoriteRepository(self.database_manager)
        )
        # JM 远程作者搜索：仅查询站点数据，不写入本地漫画库
        self.jm_search_service = JmSearchService()
        # JM 收藏入库：联网取信息后以收藏态保存，不下载漫画本体
        self.jm_collect_service = JmCollectService(
            self.manga_repo, self.tag_repo, self.favorite_repo
        )
        self.admin_qq_service = AdminQQService(
            self.web_admin_repo, self.permission_manager, self.audit_event_repo
        )
        self.manga_query_service = MangaQueryService(
            self.manga_repo,
            self.tag_repo,
            self.favorite_repo,
            self.manga_blacklist_repo,
        )
        self.task_query_service = TaskQueryService(self.operation_task_repo)
        self.audit_query_service = AuditQueryService(self.audit_event_repo)
        self.verify_service = VerifyService(
            self.manga_repo,
            self.scan_record_repo,
            self.operation_task_service,
            download_root=str(self.config_manager.config_dict["MANGA_DOWNLOAD_PATH"]),
        )
        self.system_service = SystemService(
            version=self.VERSION,
            started_at=self._started_at,
            manga_repository=self.manga_repo,
            connection_provider=self.ws_client.is_connected,
            download_queue_provider=self.download_manager.get_queue_status,
            send_queue_provider=lambda: dict(
                self.message_manager.get_send_queue_status()
            ),
            reconnect_requester=self.ws_client.request_reconnect,
            shutdown_requester=lambda context: self.request_shutdown(
                "通过 WebUI 请求安全关闭", context=context
            ),
            restart_requester=lambda context: self.request_restart(
                "通过 WebUI 请求一键重启", context=context
            ),
            audit_repository=self.audit_event_repo,
        )

        self.command_executor = CommandExecutor(
            message_sender=self.message_manager.send_message,
            file_sender=self.message_manager.send_file,
            download_manager=self.download_manager,
            config=self.config_manager.config_dict,
            self_id_getter=lambda: self.SELF_ID,
            permission_manager=self.permission_manager,
            download_service=self.download_service,
            manga_service=self.manga_service,
            resend_handler=self.message_manager.resend_pending_files,
            send_status_provider=self.message_manager.get_send_queue_status,
            manga_repo=self.manga_repo,
            tag_repo=self.tag_repo,
            blacklist_service=self.manga_blacklist_service,
        )

        # 注册立即生效配置的显式应用接口，WebUI 修改后由服务直接调用
        self.settings_service.register_appliers(
            {
                "FILE_SEND_INTERVAL": lambda value: (
                    self.message_manager.update_send_settings(send_interval=value)
                ),
                "FILE_SEND_BATCH_SIZE": lambda value: (
                    self.command_executor.update_batch_settings(batch_size=value)
                ),
                "FILE_SEND_BATCH_INTERVAL": lambda value: (
                    self.command_executor.update_batch_settings(batch_interval=value)
                ),
                "SEND_RETRY_TIMEOUT": lambda value: (
                    self.message_manager.update_send_settings(retry_timeout=value)
                ),
                "RESEND_CONFIRM_TIMEOUT": lambda value: (
                    self.message_manager.update_send_settings(
                        resend_confirm_timeout=value
                    )
                ),
                "LOW_MEMORY_DELETE_DELAY": lambda value: (
                    self.download_manager.update_low_memory_settings(delete_delay=value)
                ),
            }
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

        self.web_server: Optional[WebServer] = None
        if bool(self.config_manager.config_dict["WEBUI_ENABLED"]):
            web_host = str(self.config_manager.config_dict["WEBUI_HOST"])
            if (
                web_host not in {"127.0.0.1", "::1", "localhost"}
                and not self.web_admin_repo.get()
            ):
                logger.warning("WebUI 管理员尚未初始化，监听地址已强制退回 127.0.0.1")
                web_host = "127.0.0.1"
            self.web_server = WebServer(
                app=create_web_app(
                    WebDependencies(
                        auth_service=self.web_auth_service,
                        manga_query_service=self.manga_query_service,
                        task_query_service=self.task_query_service,
                        system_service=self.system_service,
                        manga_service=self.manga_service,
                        manga_blacklist_service=self.manga_blacklist_service,
                        download_service=self.download_service,
                        message_manager=self.message_manager,
                        permission_service=self.permission_service,
                        settings_service=self.settings_service,
                        option_file_service=self.option_file_service,
                        data_migration_service=self.data_migration_service,
                        repair_service=self.repair_service,
                        scan_service=self.scan_service,
                        reading_progress_service=self.reading_progress_service,
                        reading_setting_service=self.reading_setting_service,
                        page_image_service=self.page_image_service,
                        event_bus=self.event_bus,
                        download_progress_tracker=self.download_progress_tracker,
                        audit_query_service=self.audit_query_service,
                        verify_service=self.verify_service,
                        favorite_service=self.favorite_service,
                        admin_qq_service=self.admin_qq_service,
                        jm_favorite_service=self.jm_favorite_service,
                        jm_search_service=self.jm_search_service,
                        jm_collect_service=self.jm_collect_service,
                        recovery_prompt_provider=lambda: self.recovery_prompt,
                    ),
                    web_host=web_host,
                    web_port=int(self.config_manager.config_dict["WEBUI_PORT"]),
                    extra_origins=set(self.config_manager.webui_dev_origins),
                ),
                host=web_host,
                port=int(self.config_manager.config_dict["WEBUI_PORT"]),
            )

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
        except Exception as e:  # pylint: disable=broad-exception-caught
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

    def start_cleanup_scheduler(self) -> None:
        """启动每日过期数据清理线程（幂等）。"""
        if self._cleanup_thread is not None and self._cleanup_thread.is_alive():
            return
        self._cleanup_stop_event.clear()
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop,
            daemon=True,
            name="cleanup-retention",
        )
        self._cleanup_thread.start()
        logger.info("过期数据清理线程已启动（每天一次）")

    def stop_cleanup_scheduler(self, timeout: float = 1.0) -> bool:
        """停止清理线程并立即唤醒其等待。"""
        self._cleanup_stop_event.set()
        if self._cleanup_thread is not None:
            self._cleanup_thread.join(timeout=timeout)
            stopped = not self._cleanup_thread.is_alive()
        else:
            stopped = True
        if stopped:
            logger.info("过期数据清理线程已停止")
        return stopped

    def _cleanup_loop(self) -> None:
        """每日清理循环，由停止事件周期唤醒。"""
        while not self._cleanup_stop_event.wait(24 * 3600):
            self._run_cleanup_once()

    def _run_cleanup_once(self) -> None:
        """执行一次过期任务、审计与 Web 会话清理；失败仅记录，不中断调度。"""
        try:
            self.cleanup_service.cleanup()
            expired_sessions = self.web_auth_service.cleanup_expired_sessions()
            if expired_sessions:
                logger.info(f"已清理过期 Web 会话：{expired_sessions} 个")
        except Exception as error:  # pylint: disable=broad-exception-caught
            logger.error(f"过期数据清理失败: {error}")

    def _start_recovery_prompt(self) -> None:
        """在独立线程中等待恢复决定，避免阻塞 WebSocket 与主循环启动。"""
        if not self._pending_recovery_tasks:
            return
        if self._recovery_thread is not None and self._recovery_thread.is_alive():
            return
        self._recovery_thread = threading.Thread(
            target=self._handle_recovery_prompt,
            daemon=True,
            name="recovery-prompt",
        )
        self._recovery_thread.start()

    def _handle_recovery_prompt(self) -> None:
        """按可用渠道询问是否恢复；无渠道时默认继续，超时默认取消。"""
        tasks = self._pending_recovery_tasks
        if not tasks:
            return
        timeout = int(
            self.config_manager.config_dict["RECOVERY_PROMPT_TIMEOUT_SECONDS"]
        )
        prompt = RecoveryPrompt(len(tasks), timeout_seconds=timeout)
        self.recovery_prompt = prompt
        try:
            tty_available = sys.stdin.isatty()
            webui_available = self.web_server is not None
            if not tty_available and not webui_available:
                # 无任何询问渠道时保持原行为，避免静默丢弃遗留任务
                logger.info("当前无终端或 WebUI 询问渠道，默认恢复下载任务")
                decision = "continue"
            else:
                if tty_available:
                    self._start_terminal_recovery_prompt(prompt)
                decision = prompt.wait()
        finally:
            self.recovery_prompt = None
            self._pending_recovery_tasks = []
        if decision == "continue":
            self._recover_download_tasks(tasks)
        else:
            self._cancel_recovery_tasks(tasks)

    def _start_terminal_recovery_prompt(self, prompt: RecoveryPrompt) -> None:
        """终端读取放到单独线程，与 WebUI 渠道共享同一个决定。"""
        threading.Thread(
            target=self._terminal_recovery_loop,
            args=(prompt,),
            daemon=True,
            name="recovery-terminal",
        ).start()

    def _terminal_recovery_loop(self, prompt: RecoveryPrompt) -> None:
        """读取终端 y/n；无输入或 EOF 时交由 WebUI 或超时处理。"""
        print(
            f"检测到 {prompt.task_count} 个中断下载任务，是否继续？"
            f"(y/n，{prompt.timeout_seconds} 秒内无响应默认取消)"
        )
        try:
            if platform.system() == "Linux":
                while prompt.is_pending():
                    remaining = min(1.0, float(prompt.remaining_seconds()))
                    ready, _, _ = select.select(
                        [sys.stdin], [], [], max(remaining, 0.1)
                    )
                    if not ready:
                        continue
                    line = sys.stdin.readline().strip().lower()
                    if not line:
                        return
                    prompt.resolve("continue" if line.startswith("y") else "cancel")
                    return
            else:
                import msvcrt  # pylint: disable=import-error,import-outside-toplevel

                msvcrt_module: Any = msvcrt
                while prompt.is_pending():
                    if msvcrt_module.kbhit():
                        key = msvcrt_module.getwch().lower()
                        prompt.resolve("continue" if key == "y" else "cancel")
                        return
                    time.sleep(0.1)
        except (EOFError, OSError, ValueError) as error:
            logger.warning(f"终端恢复询问不可用，交由其他渠道处理: {error}")

    def _recover_download_tasks(self, tasks: List[TaskResult]) -> None:
        """把待恢复任务重新入队，并记录启动恢复审计。"""
        recovery_result = self.download_manager.recover_tasks(tasks)
        recovery_summary = (
            f"启动恢复 {recovery_result.recovered_count} 个下载任务"
            f"（其中中断续传 {recovery_result.resumed_count} 个）"
        )
        if recovery_result.skipped_count or recovery_result.aborted:
            logger.warning(
                f"{recovery_summary}，跳过 {recovery_result.skipped_count} 个"
            )
        else:
            logger.info(recovery_summary)
        self.audit_event_repo.record(
            event_type="bot.tasks_recovered",
            source="system",
            result=(
                "failed"
                if recovery_result.aborted
                else ("partial" if recovery_result.skipped_count else "succeeded")
            ),
            target_type="bot",
            target_id="self",
            metadata={
                "recovered_count": recovery_result.recovered_count,
                "resumed_count": recovery_result.resumed_count,
            },
        )

    def _cancel_recovery_tasks(self, tasks: List[TaskResult]) -> None:
        """用户拒绝恢复时取消遗留任务、写审计并清理临时下载目录。"""
        cancelled_count = 0
        for task in tasks:
            try:
                self.operation_task_service.cancel_recovery(task.id)
            except ValueError as error:
                logger.warning(f"取消遗留下载任务失败（{task.id}）: {error}")
                continue
            cancelled_count += 1
            self.audit_event_repo.record(
                event_type="bot.recovery_cancelled",
                source="system",
                result="succeeded",
                target_type="manga" if task.manga_id else "task",
                target_id=task.manga_id or task.id,
                metadata={"reason": "user_cancelled"},
            )
        logger.info(f"已按用户选择取消 {cancelled_count} 个遗留下载任务")
        self._cleanup_download_directory()

    def run(self) -> None:
        """运行机器人主函数"""
        logger.info("JMComic下载机器人启动中...")

        if self.web_server is not None:
            self.web_server.start()
        # 询问在后台线程等待，WebSocket 连接与其他启动步骤不被 3 分钟倒计时阻塞
        self._start_recovery_prompt()
        self.connect_websocket()
        self.start_reconnect_manager()
        self.start_cleanup_scheduler()

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
            import termios  # pylint: disable=import-outside-toplevel
            import tty  # pylint: disable=import-outside-toplevel
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

    def request_shutdown(
        self, reason: str = "", context: Optional[OperationContext] = None
    ) -> None:
        """请求主循环退出，重复调用不会产生额外副作用

        Args:
            reason: 关闭原因，写入日志与审计元数据
            context: 操作来源上下文，缺省按系统来源记录
        """
        if self._shutdown_event.is_set():
            return
        if reason:
            logger.info(f"请求关闭机器人: {reason}")
        operation_context = context or OperationContext.system()
        self.audit_event_repo.record(
            event_type="bot.shutdown_requested",
            source=operation_context.source,
            result="accepted",
            actor_user_id=operation_context.actor_user_id,
            actor_group_id=operation_context.actor_group_id,
            client_ip=operation_context.client_ip,
            target_type="bot",
            target_id="self",
            metadata={"reason": reason} if reason else None,
        )
        self._shutdown_event.set()

    def request_restart(
        self, reason: str = "", context: Optional[OperationContext] = None
    ) -> None:
        """请求优雅重启：复用安全关闭收尾路径，close 后由 main 拉起新进程。

        重复调用不会产生额外副作用；与 request_shutdown 互斥（先到的生效）。
        """
        if self._shutdown_event.is_set():
            return
        if reason:
            logger.info(f"请求重启机器人: {reason}")
        operation_context = context or OperationContext.system()
        self.audit_event_repo.record(
            event_type="bot.restart_requested",
            source=operation_context.source,
            result="accepted",
            actor_user_id=operation_context.actor_user_id,
            actor_group_id=operation_context.actor_group_id,
            client_ip=operation_context.client_ip,
            target_type="bot",
            target_id="self",
            metadata={"reason": reason} if reason else None,
        )
        self.restart_requested = True
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

        close_steps = []
        if self.web_server is not None:
            close_steps.append(("WebUI", self.web_server.stop))
        close_steps.extend(
            (
                ("WebSocket", self.ws_client.close),
                ("文件发送队列", self.message_manager.stop),
                ("下载队列", self.download_manager.stop),
                ("过期清理线程", self.stop_cleanup_scheduler),
                ("SQLite数据库", self.database_manager.close),
            )
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
