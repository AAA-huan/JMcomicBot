"""阅读器偏好设置应用服务，统一校验并持久化五项配置。"""

from typing import Any, Dict, Optional

from src.database.models import ReadingSetting, utc_now
from src.database.repositories import AuditEventRepository, ReadingSettingRepository
from src.service.operation_context import OperationContext

READING_MODES = ("normal", "manga", "scroll")
_SETTING_FIELDS = (
    "reading_mode",
    "continuous",
    "click_to_turn",
    "reverse_click",
    "dark_background",
)


class ReadingSettingService:
    """阅读器设置服务，设置页与阅读器工具栏共用同一份数据。"""

    def __init__(
        self,
        repository: ReadingSettingRepository,
        audit_repository: AuditEventRepository,
    ) -> None:
        self.repository = repository
        self.audit_repository = audit_repository

    def get_or_default(self, admin_id: int) -> ReadingSetting:
        """查询管理员设置；未保存时返回全默认值的内存对象，不落库。"""
        self._validate_admin_id(admin_id)
        setting = self.repository.get(admin_id)
        if setting is not None:
            return setting
        return self._defaults(admin_id)

    def upsert(
        self,
        admin_id: int,
        payload: Dict[str, Any],
        context: Optional[OperationContext] = None,
    ) -> ReadingSetting:
        """整体更新五项配置，未传字段保留原值，并写入审计。

        Raises:
            ValueError: 字段未知、类型非法、模式非法或反转点击缺少点击翻页。
        """
        self._validate_admin_id(admin_id)
        unexpected = set(payload) - set(_SETTING_FIELDS)
        if unexpected:
            raise ValueError(f"包含未知的阅读设置字段: {sorted(unexpected)}")
        if not payload:
            return self.get_or_default(admin_id)

        merged = self._as_dict(self.get_or_default(admin_id))
        for field, value in payload.items():
            if field == "reading_mode":
                if not isinstance(value, str) or value not in READING_MODES:
                    raise ValueError(f"不支持的阅读模式: {value}")
            elif not isinstance(value, bool):
                raise ValueError(f"阅读设置 {field} 必须是布尔值")
            merged[field] = value

        if merged["reverse_click"] and not merged["click_to_turn"]:
            raise ValueError("开启反转点击翻页前必须先开启点击翻页")

        saved = self.repository.upsert(
            admin_id=admin_id,
            reading_mode=merged["reading_mode"],
            continuous=merged["continuous"],
            click_to_turn=merged["click_to_turn"],
            reverse_click=merged["reverse_click"],
            dark_background=merged["dark_background"],
        )
        operation_context = context or OperationContext.system()
        self.audit_repository.record(
            event_type="reader.setting_changed",
            source=operation_context.source,
            result="succeeded",
            actor_user_id=operation_context.actor_user_id,
            actor_group_id=operation_context.actor_group_id,
            client_ip=operation_context.client_ip,
            target_type="reading_setting",
            target_id=str(admin_id),
            metadata={"changed_fields": sorted(payload)},
        )
        return saved

    @staticmethod
    def _validate_admin_id(admin_id: int) -> None:
        """管理员账户ID必须为正整数。"""
        if not isinstance(admin_id, int) or isinstance(admin_id, bool) or admin_id <= 0:
            raise ValueError("管理员账户ID必须是正整数")

    @staticmethod
    def _defaults(admin_id: int) -> ReadingSetting:
        """构造全默认值的内存设置对象。"""
        return ReadingSetting(
            admin_id=admin_id,
            reading_mode="normal",
            continuous=False,
            click_to_turn=False,
            reverse_click=False,
            dark_background=False,
            updated_at=utc_now(),
        )

    @staticmethod
    def _as_dict(setting: ReadingSetting) -> Dict[str, Any]:
        """提取五项可更新字段的当前值。"""
        return {field: getattr(setting, field) for field in _SETTING_FIELDS}
