"""Web API 应用服务依赖集合。"""

from dataclasses import dataclass

from src.service import (
    DatabaseMaintenanceService,
    DownloadService,
    MangaService,
    PermissionService,
    RepairService,
    ScanService,
    SettingsService,
)
from src.service.query_service import MangaQueryService, TaskQueryService
from src.service.system_service import SystemService
from src.service.web_auth_service import WebAuthService


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
