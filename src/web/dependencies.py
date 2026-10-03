"""Web API 应用服务依赖集合。"""

from dataclasses import dataclass

from src.service import (
    DatabaseMaintenanceService,
    DownloadService,
    MangaService,
    PermissionService,
    ReadingProgressService,
    RepairService,
    ScanService,
    SettingsService,
    VerifyService,
)
from src.service.query_service import (
    AuditQueryService,
    MangaQueryService,
    TaskQueryService,
)
from src.service.admin_qq_service import AdminQQService
from src.service.favorite_service import FavoriteService
from src.service.system_service import SystemService
from src.service.web_auth_service import WebAuthService
from src.web.events.bus import WebEventBus


@dataclass(frozen=True)
class WebDependencies:  # pylint: disable=too-many-instance-attributes
    """由 MangaBot 构造并注入 Web 应用的服务集合。"""

    auth_service: WebAuthService
    manga_query_service: MangaQueryService
    task_query_service: TaskQueryService
    system_service: SystemService
    manga_service: MangaService
    download_service: DownloadService
    permission_service: PermissionService
    settings_service: SettingsService
    database_maintenance_service: DatabaseMaintenanceService
    repair_service: RepairService
    scan_service: ScanService
    reading_progress_service: ReadingProgressService
    event_bus: WebEventBus
    audit_query_service: AuditQueryService
    verify_service: VerifyService
    favorite_service: FavoriteService
    admin_qq_service: AdminQQService
