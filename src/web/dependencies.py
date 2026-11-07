"""Web API 应用服务依赖集合。"""

from dataclasses import dataclass
from typing import Callable, Optional

from src.download.progress import DownloadProgressTracker
from src.service import (
    DataMigrationService,
    DownloadService,
    MangaBlacklistService,
    MangaService,
    PageImageService,
    PermissionService,
    ReadingProgressService,
    ReadingSettingService,
    RepairService,
    ScanService,
    SettingsService,
    VerifyService,
)
from src.message.manager import MessageManager
from src.service.admin_qq_service import AdminQQService
from src.service.favorite_service import FavoriteService
from src.service.jm_collect_service import JmCollectService
from src.service.jm_favorite_service import JmFavoriteService
from src.service.jm_search_service import JmSearchService
from src.service.option_file_service import OptionFileService
from src.service.recovery_prompt import RecoveryPrompt
from src.service.query_service import (
    AuditQueryService,
    MangaQueryService,
    TaskQueryService,
)
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
    manga_blacklist_service: MangaBlacklistService
    download_service: DownloadService
    message_manager: MessageManager
    permission_service: PermissionService
    settings_service: SettingsService
    option_file_service: OptionFileService
    data_migration_service: DataMigrationService
    repair_service: RepairService
    scan_service: ScanService
    reading_progress_service: ReadingProgressService
    reading_setting_service: ReadingSettingService
    page_image_service: PageImageService
    event_bus: WebEventBus
    download_progress_tracker: DownloadProgressTracker
    audit_query_service: AuditQueryService
    verify_service: VerifyService
    favorite_service: FavoriteService
    admin_qq_service: AdminQQService
    jm_favorite_service: JmFavoriteService
    jm_search_service: JmSearchService
    jm_collect_service: JmCollectService
    recovery_prompt_provider: Callable[[], Optional[RecoveryPrompt]]
