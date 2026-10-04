"""Web API 测试共享依赖构造工具。"""

from pathlib import Path
from typing import Dict, List, Optional, Tuple

from argon2 import PasswordHasher
from starlette.testclient import TestClient

from src.config.manager import ConfigManager
from src.database.database import DatabaseManager
from src.database.models import utc_now
from src.database.repositories import (
    AuditEventRepository,
    BackupRepository,
    FavoriteRepository,
    JmFavoriteRepository,
    MangaRepository,
    MangaTagRepository,
    OperationTaskRepository,
    PermissionRepository,
    ReadingProgressRepository,
    ScanRecordRepository,
    SettingHistoryRepository,
    SettingRepository,
    TaskEventRepository,
    UserGroupRepository,
    WebAdminRepository,
    WebSessionRepository,
)
from src.permission.manager import PermissionManager
from src.service import (
    DatabaseMaintenanceService,
    DownloadQueueService,
    MangaService,
    OperationTaskService,
    PermissionService,
    ReadingProgressService,
    RepairService,
    ScanService,
    SettingsService,
    VerifyService,
)
from src.service.admin_qq_service import AdminQQService
from src.service.favorite_service import FavoriteService
from src.service.jm_favorite_service import JmFavoriteService
from src.service.query_service import (
    AuditQueryService,
    MangaQueryService,
    TaskQueryService,
)
from src.service.results import DownloadRequestItem
from src.service.settings_service import EFFECT_IMMEDIATE, SETTING_DEFINITIONS
from src.service.system_service import SystemService
from src.service.web_auth_service import WebAuthService
from src.web.app import create_web_app
from src.web.dependencies import WebDependencies
from src.web.events.bus import WebEventBus

PASSWORD = "correct-horse-battery-staple"


class _ConfigManagerStub(ConfigManager):
    """仅提供 config_dict 的配置管理器替身。"""

    def __init__(
        self, config_dict: Optional[Dict[str, object]] = None, env_file=None
    ) -> None:
        super().__init__(env_file=env_file)
        self.config_dict: Dict[str, object] = dict(config_dict or {})


class FakeDownloadQueue:
    """测试用下载队列网关：记录入队与取消，不执行真实下载。"""

    def __init__(self, task_service: OperationTaskService) -> None:
        self.task_service = task_service
        self.queued_task_ids: Dict[str, str] = {}
        self.requested_manga_ids: List[str] = []

    def request_download(self, manga_id: str, context, notifier) -> DownloadRequestItem:
        del notifier
        task = self.task_service.create("download", context, manga_id=manga_id)
        self.queued_task_ids[manga_id] = task.id
        self.requested_manga_ids.append(manga_id)
        return DownloadRequestItem(manga_id=manga_id, status="queued", task_id=task.id)

    def find_active_download(self, manga_id: str) -> Optional[str]:
        return self.queued_task_ids.get(manga_id)

    def cancel_download(self, manga_id: str) -> bool:
        task_id = self.queued_task_ids.pop(manga_id, None)
        if task_id is None:
            return False
        self.task_service.cancel(task_id)
        return True

    def cancel_all_downloads(self) -> int:
        task_ids = list(self.queued_task_ids.values())
        self.queued_task_ids.clear()
        for task_id in task_ids:
            self.task_service.cancel(task_id)
        return len(task_ids)


class WebTestContext:
    """测试依赖集合与可观测的替身句柄。"""

    def __init__(
        self,
        dependencies: WebDependencies,
        download_queue: FakeDownloadQueue,
        event_bus: WebEventBus,
        shutdown_calls: List[object],
        reconnect_calls: List[bool],
        applied_settings: Dict[str, object],
    ) -> None:
        self.dependencies = dependencies
        self.download_queue = download_queue
        self.event_bus = event_bus
        self.shutdown_calls = shutdown_calls
        self.reconnect_calls = reconnect_calls
        self.applied_settings = applied_settings


def build_web_context(  # pylint: disable=too-many-locals
    db_manager: DatabaseManager,
    download_root: Path,
    backup_dir: Path,
    config_dict: Optional[Dict[str, object]] = None,
) -> WebTestContext:
    """构造完整 WebDependencies，并保留替身调用记录供断言。"""
    shutdown_calls: List[object] = []
    reconnect_calls: List[bool] = []
    applied_settings: Dict[str, object] = {}

    manga_repo = MangaRepository(db_manager, download_root=str(download_root))
    tag_repo = MangaTagRepository(db_manager)
    operation_task_repo = OperationTaskRepository(db_manager)
    audit_repo = AuditEventRepository(db_manager)
    event_bus = WebEventBus()
    task_service = OperationTaskService(
        operation_task_repo,
        TaskEventRepository(db_manager),
        audit_repo,
        event_publisher=event_bus,
    )
    permission_manager = PermissionManager(PermissionRepository(db_manager))
    download_queue = FakeDownloadQueue(task_service)

    settings_service = SettingsService(
        SettingRepository(db_manager),
        SettingHistoryRepository(db_manager),
        audit_repo,
        _ConfigManagerStub(config_dict, str(Path(db_manager.db_dir) / ".env")),  # type: ignore[arg-type]
    )

    def make_applier(key: str):
        def apply(value: object) -> None:
            applied_settings[key] = value

        return apply

    settings_service.register_appliers(
        {
            definition.key: make_applier(definition.key)
            for definition in SETTING_DEFINITIONS
            if definition.editable and definition.effect == EFFECT_IMMEDIATE
        }
    )

    def request_reconnect() -> bool:
        reconnect_calls.append(True)
        return True

    def request_shutdown(operation_context) -> None:
        shutdown_calls.append(operation_context)

    dependencies = WebDependencies(
        auth_service=WebAuthService(
            WebAdminRepository(db_manager),
            WebSessionRepository(db_manager),
            audit_repo,
            session_hours=24,
            password_hasher=PasswordHasher(
                time_cost=1,
                memory_cost=8192,
                parallelism=1,
            ),
        ),
        manga_query_service=MangaQueryService(manga_repo, tag_repo),
        task_query_service=TaskQueryService(operation_task_repo),
        system_service=SystemService(
            version="test-version",
            started_at=utc_now(),
            manga_repository=manga_repo,
            connection_provider=lambda: True,
            download_queue_provider=lambda: {"running": True, "queue_size": 0},
            send_queue_provider=lambda: {"running": True, "queue_size": 0},
            reconnect_requester=request_reconnect,
            shutdown_requester=request_shutdown,
            audit_repository=audit_repo,
        ),
        manga_service=MangaService(
            manga_repository=manga_repo,
            tag_repository=tag_repo,
            audit_repository=audit_repo,
            operation_task_service=task_service,
            download_root=str(download_root),
            download_conflict_checker=download_queue.find_active_download,
            send_conflict_checker=lambda _manga_id: False,
        ),
        download_service=DownloadQueueService(download_queue, task_service),
        permission_service=PermissionService(
            permission_manager,
            audit_repo,
            UserGroupRepository(db_manager),
        ),
        settings_service=settings_service,
        database_maintenance_service=DatabaseMaintenanceService(
            db_manager,
            task_service,
            BackupRepository(db_manager),
            backup_dir=str(backup_dir),
        ),
        repair_service=RepairService(
            manga_repo,
            tag_repo,
            ScanRecordRepository(db_manager),
            task_service,
            download_root=str(download_root),
        ),
        scan_service=ScanService(
            manga_repo,
            tag_repo,
            ScanRecordRepository(db_manager),
            task_service,
            download_root=str(download_root),
        ),
        reading_progress_service=ReadingProgressService(
            ReadingProgressRepository(db_manager), manga_repo
        ),
        favorite_service=FavoriteService(FavoriteRepository(db_manager), audit_repo),
        jm_favorite_service=JmFavoriteService(JmFavoriteRepository(db_manager)),
        admin_qq_service=AdminQQService(
            WebAdminRepository(db_manager), permission_manager, audit_repo
        ),
        event_bus=event_bus,
        audit_query_service=AuditQueryService(audit_repo),
        verify_service=VerifyService(
            manga_repo,
            ScanRecordRepository(db_manager),
            task_service,
            download_root=str(download_root),
        ),
    )
    return WebTestContext(
        dependencies=dependencies,
        download_queue=download_queue,
        event_bus=event_bus,
        shutdown_calls=shutdown_calls,
        reconnect_calls=reconnect_calls,
        applied_settings=applied_settings,
    )


def create_client_for(
    db_manager: DatabaseManager, host: str = "127.0.0.1"
) -> Tuple[TestClient, WebTestContext]:
    """基于临时目录构造测试客户端与可观测上下文。"""
    root = Path(db_manager.db_dir).parent
    context = build_web_context(db_manager, root, root / "backups")
    return create_test_client(context.dependencies, host), context


def create_test_client(
    dependencies: WebDependencies,
    host: str = "127.0.0.1",
    status_interval_seconds: float = 2.0,
    web_host: str = "127.0.0.1",
    web_port: int = 7999,
    host_header: str = "127.0.0.1",
) -> TestClient:
    """构造带固定 Host 头的测试客户端。

    web_host 用于模拟 WEBUI_HOST 配置（0.0.0.0 表示局域网模式）；
    host_header 决定请求携带的 Host 头。
    """
    return TestClient(
        create_web_app(
            dependencies,
            web_host=web_host,
            web_port=web_port,
            status_interval_seconds=status_interval_seconds,
        ),
        client=(host, 50000),
        headers={"Host": host_header},
    )


def setup_and_login(client: TestClient) -> None:
    """完成首次设置与登录，并校验会话 Cookie 安全属性。"""
    setup_response = client.post("/api/v1/auth/setup", json={"password": PASSWORD})
    assert setup_response.status_code == 201
    login_response = client.post("/api/v1/auth/login", json={"password": PASSWORD})
    assert login_response.status_code == 200
    cookie = login_response.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie


def csrf_headers(client: TestClient) -> dict[str, str]:
    """返回使用真实 CSRF Cookie 的请求头。"""
    return {"X-CSRF-Token": client.cookies["jmbot_csrf"]}
