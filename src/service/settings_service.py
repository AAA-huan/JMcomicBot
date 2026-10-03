"""运行时配置应用服务，统一注册表、校验、生效与审计。"""

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple
from urllib.parse import urlparse

from src.config.manager import ConfigManager
from src.database.repositories import (
    AuditEventRepository,
    SettingHistoryRepository,
    SettingRepository,
)
from src.service.operation_context import OperationContext

EFFECT_IMMEDIATE = "immediate"
EFFECT_RESTART = "restart"

# 敏感值对前端和审计只展示占位符，永不回显真实内容
_MASKED_VALUE = "******"
_BOOL_TRUE_VALUES = {"true", "1", "yes", "on"}
_BOOL_FALSE_VALUES = {"false", "0", "no", "off"}


@dataclass(frozen=True)
class SettingDefinition:  # pylint: disable=too-many-instance-attributes
    """单个配置项的注册表定义。"""

    key: str
    title: str
    value_type: str
    default: Any
    group: str
    editable: bool
    sensitive: bool
    effect: str
    apply_target: str
    minimum: Optional[float] = None
    maximum: Optional[float] = None


@dataclass(frozen=True)
class SettingView:  # pylint: disable=too-many-instance-attributes
    """可安全返回浏览器的配置视图，敏感值只暴露是否已设置。"""

    key: str
    title: str
    value_type: str
    group: str
    editable: bool
    sensitive: bool
    effect: str
    apply_target: str
    value: Any
    is_set: bool
    restart_required: bool = False


SETTING_DEFINITIONS: Tuple[SettingDefinition, ...] = (
    SettingDefinition(
        key="FILE_SEND_INTERVAL",
        title="文件发送间隔（秒）",
        value_type="float",
        default=1.8,
        group="文件发送",
        editable=True,
        sensitive=False,
        effect=EFFECT_IMMEDIATE,
        apply_target="文件发送队列",
        minimum=0.1,
        maximum=10.0,
    ),
    SettingDefinition(
        key="FILE_SEND_BATCH_SIZE",
        title="每批发送文件数量",
        value_type="int",
        default=10,
        group="文件发送",
        editable=True,
        sensitive=False,
        effect=EFFECT_IMMEDIATE,
        apply_target="文件发送队列",
        minimum=1,
        maximum=100,
    ),
    SettingDefinition(
        key="FILE_SEND_BATCH_INTERVAL",
        title="批次发送间隔（秒）",
        value_type="float",
        default=7.0,
        group="文件发送",
        editable=True,
        sensitive=False,
        effect=EFFECT_IMMEDIATE,
        apply_target="文件发送队列",
        minimum=1.0,
        maximum=120.0,
    ),
    SettingDefinition(
        key="SEND_RETRY_TIMEOUT",
        title="发送重试超时（秒）",
        value_type="int",
        default=30,
        group="文件发送",
        editable=True,
        sensitive=False,
        effect=EFFECT_IMMEDIATE,
        apply_target="文件发送队列",
        minimum=5,
        maximum=600,
    ),
    SettingDefinition(
        key="RESEND_CONFIRM_TIMEOUT",
        title="断线重发确认超时（秒）",
        value_type="int",
        default=300,
        group="文件发送",
        editable=True,
        sensitive=False,
        effect=EFFECT_IMMEDIATE,
        apply_target="文件发送队列",
        minimum=30,
        maximum=3600,
    ),
    SettingDefinition(
        key="LOW_MEMORY_DELETE_DELAY",
        title="低内存模式删除延迟（分钟）",
        value_type="int",
        default=3,
        group="下载与存储",
        editable=True,
        sensitive=False,
        effect=EFFECT_IMMEDIATE,
        apply_target="下载队列",
        minimum=1,
        maximum=60,
    ),
    SettingDefinition(
        key="LOW_MEMORY_MODE",
        title="低内存模式",
        value_type="bool",
        default=False,
        group="下载与存储",
        editable=True,
        sensitive=False,
        effect=EFFECT_RESTART,
        apply_target="重启机器人",
    ),
    SettingDefinition(
        key="MANGA_DOWNLOAD_PATH",
        title="漫画下载目录",
        value_type="str",
        default="./downloads",
        group="路径",
        editable=True,
        sensitive=False,
        effect=EFFECT_RESTART,
        apply_target="重启机器人",
    ),
    SettingDefinition(
        key="DB_PATH",
        title="数据库目录",
        value_type="str",
        default="./data",
        group="路径",
        editable=True,
        sensitive=False,
        effect=EFFECT_RESTART,
        apply_target="重启机器人",
    ),
    SettingDefinition(
        key="BACKUP_PATH",
        title="数据库备份目录",
        value_type="str",
        default="./data/backups",
        group="路径",
        editable=True,
        sensitive=False,
        effect=EFFECT_RESTART,
        apply_target="重启机器人",
    ),
    SettingDefinition(
        key="WEBUI_ENABLED",
        title="启用 WebUI",
        value_type="bool",
        default=True,
        group="WebUI",
        editable=True,
        sensitive=False,
        effect=EFFECT_RESTART,
        apply_target="重启机器人",
    ),
    SettingDefinition(
        key="WEBUI_HOST",
        title="WebUI 监听地址",
        value_type="str",
        default="127.0.0.1",
        group="WebUI",
        editable=True,
        sensitive=False,
        effect=EFFECT_RESTART,
        apply_target="重启机器人",
    ),
    SettingDefinition(
        key="WEBUI_PORT",
        title="WebUI 监听端口",
        value_type="int",
        default=7999,
        group="WebUI",
        editable=True,
        sensitive=False,
        effect=EFFECT_RESTART,
        apply_target="重启机器人",
        minimum=1,
        maximum=65535,
    ),
    SettingDefinition(
        key="WEBUI_SESSION_HOURS",
        title="登录会话有效期（小时）",
        value_type="int",
        default=24,
        group="WebUI",
        editable=True,
        sensitive=False,
        effect=EFFECT_RESTART,
        apply_target="重启机器人",
        minimum=1,
        maximum=720,
    ),
    SettingDefinition(
        key="NAPCAT_WS_URL",
        title="NapCat WebSocket 地址",
        value_type="str",
        default="",
        group="NapCat",
        editable=True,
        sensitive=True,
        effect=EFFECT_RESTART,
        apply_target="重启机器人",
    ),
    SettingDefinition(
        key="NAPCAT_TOKEN",
        title="NapCat 访问令牌",
        value_type="str",
        default="",
        group="NapCat",
        editable=True,
        sensitive=True,
        effect=EFFECT_RESTART,
        apply_target="重启机器人",
    ),
)


class SettingsService:
    """通过注册表提供配置查询、校验、即时应用与启动配置保存。"""

    def __init__(
        self,
        setting_repository: SettingRepository,
        history_repository: SettingHistoryRepository,
        audit_repository: AuditEventRepository,
        config_manager: ConfigManager,
        definitions: Tuple[SettingDefinition, ...] = SETTING_DEFINITIONS,
    ) -> None:
        self.setting_repository = setting_repository
        self.history_repository = history_repository
        self.audit_repository = audit_repository
        self.config_manager = config_manager
        self.definitions: Dict[str, SettingDefinition] = {}
        for definition in definitions:
            if definition.key in self.definitions:
                raise ValueError(f"配置注册表存在重复键: {definition.key}")
            self.definitions[definition.key] = definition
        self.pending_restart_values: Dict[str, Any] = {}
        self.appliers: Dict[str, Callable[[Any], None]] = {}

    def register_appliers(self, appliers: Dict[str, Callable[[Any], None]]) -> None:
        """注册立即生效配置的显式应用接口，缺失或多余键都会明确报错。"""
        required_keys = {
            definition.key
            for definition in self.definitions.values()
            if definition.editable and definition.effect == EFFECT_IMMEDIATE
        }
        unknown_keys = set(appliers) - required_keys
        if unknown_keys:
            raise ValueError(f"存在无对应可编辑配置的应用接口: {sorted(unknown_keys)}")
        missing_keys = required_keys - set(appliers)
        if missing_keys:
            raise ValueError(f"缺少立即生效配置的应用接口: {sorted(missing_keys)}")
        self.appliers = dict(appliers)

    def load_persisted(self) -> int:
        """启动时应用数据库中的动态覆盖值，返回应用数量。

        只允许覆盖注册表中的可编辑配置；数据库出现未知键或只读键时明确报错，
        不静默忽略。
        """
        applied_count = 0
        for setting in self.setting_repository.list():
            definition = self.definitions.get(setting.key)
            if definition is None:
                raise ValueError(f"数据库中保存了未注册的配置项: {setting.key}")
            if not definition.editable or definition.effect != EFFECT_IMMEDIATE:
                raise ValueError(f"配置项不允许通过数据库覆盖: {setting.key}")
            parsed_value = self._parse_stored(definition, setting.value)
            self.config_manager.config_dict[setting.key] = parsed_value
            applied_count += 1
        return applied_count

    def list(self) -> Tuple[SettingView, ...]:
        """返回全部配置项的安全视图，保持注册表顺序。"""
        return tuple(self._view(definition) for definition in self.definitions.values())

    def update(
        self,
        key: str,
        raw_value: Any,
        context: Optional[OperationContext] = None,
    ) -> SettingView:
        """校验并更新配置，即时项调用组件接口，启动项写环境文件并记录历史。

        Raises:
            ValueError: 配置项不存在、不可编辑、类型或取值非法时
            RuntimeError: 立即生效配置缺少显式应用接口时
        """
        definition = self.definitions.get(key)
        if definition is None:
            raise ValueError(f"不支持的配置项: {key}")
        if not definition.editable:
            raise ValueError(f"配置项不允许在 WebUI 修改: {key}")
        parsed_value = self._validate_api_value(definition, raw_value)
        current_value = self._effective_value(definition)
        if parsed_value == current_value:
            return self._view(definition)

        if definition.effect == EFFECT_RESTART:
            # 启动项必须在打开数据库、启动 WebUI 之前加载，不能保存到动态配置表。
            self.config_manager.save_restart_setting(key, self._serialize(parsed_value))
            self.pending_restart_values[key] = parsed_value
        else:
            applier = self.appliers.get(key)
            if applier is None:
                raise RuntimeError(f"配置项缺少显式应用接口: {key}")
            # 先应用再持久化：应用失败时数据库保持旧值，不会出现“已保存但未生效”
            applier(parsed_value)
            self.setting_repository.set(key, self._serialize(parsed_value))
            self.config_manager.config_dict[key] = parsed_value

        operation_context = context or OperationContext.system()
        self.history_repository.record(
            key=key,
            old_value_masked=self._mask(definition, current_value),
            new_value_masked=self._mask(definition, parsed_value),
            source=operation_context.source,
            changed_by=operation_context.actor_user_id or "",
        )
        self.audit_repository.record(
            event_type="setting.changed",
            source=operation_context.source,
            result="succeeded",
            actor_user_id=operation_context.actor_user_id,
            actor_group_id=operation_context.actor_group_id,
            client_ip=operation_context.client_ip,
            target_type="setting",
            target_id=key,
            metadata={"changed_fields": [key]},
        )
        return self._view(definition)

    def _view(self, definition: SettingDefinition) -> SettingView:
        """按敏感性生成安全视图：敏感值只返回是否已设置。"""
        value = self._effective_value(definition)
        restart_required = (
            definition.key in self.pending_restart_values
            and value
            != self.config_manager.config_dict.get(definition.key, definition.default)
        )
        if definition.sensitive:
            return SettingView(
                key=definition.key,
                title=definition.title,
                value_type=definition.value_type,
                group=definition.group,
                editable=definition.editable,
                sensitive=True,
                effect=definition.effect,
                apply_target=definition.apply_target,
                value=None,
                is_set=bool(value),
                restart_required=restart_required,
            )
        return SettingView(
            key=definition.key,
            title=definition.title,
            value_type=definition.value_type,
            group=definition.group,
            editable=definition.editable,
            sensitive=False,
            effect=definition.effect,
            apply_target=definition.apply_target,
            value=value,
            is_set=True,
            restart_required=restart_required,
        )

    def _effective_value(self, definition: SettingDefinition) -> Any:
        """数据库动态值优先，其次启动配置，最后注册表默认值。"""
        if definition.effect == EFFECT_RESTART:
            return self.pending_restart_values.get(
                definition.key,
                self.config_manager.config_dict.get(definition.key, definition.default),
            )
        stored_value = self.setting_repository.get_optional(definition.key)
        if stored_value is not None:
            return self._parse_stored(definition, stored_value)
        if definition.key in self.config_manager.config_dict:
            return self.config_manager.config_dict[definition.key]
        return definition.default

    @staticmethod
    def _mask(definition: SettingDefinition, value: Any) -> str:
        """生成历史记录中的脱敏值。"""
        if definition.sensitive:
            return _MASKED_VALUE
        return str(value)

    @staticmethod
    def _serialize(value: Any) -> str:
        """将配置值序列化为数据库字符串。"""
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    @staticmethod
    def _check_range(definition: SettingDefinition, value: Any) -> Any:
        """校验数值配置的范围并返回原值。"""
        if definition.minimum is not None and value < definition.minimum:
            raise ValueError(f"配置项 {definition.key} 不能小于 {definition.minimum}")
        if definition.maximum is not None and value > definition.maximum:
            raise ValueError(f"配置项 {definition.key} 不能大于 {definition.maximum}")
        return value

    @classmethod
    def _parse_stored(cls, definition: SettingDefinition, raw_value: str) -> Any:
        """解析数据库或启动配置中的字符串值。"""
        if definition.value_type == "bool":
            normalized = raw_value.strip().lower()
            if normalized in _BOOL_TRUE_VALUES:
                return True
            if normalized in _BOOL_FALSE_VALUES:
                return False
            raise ValueError(f"配置项 {definition.key} 的布尔值非法: {raw_value}")
        if definition.value_type == "int":
            try:
                parsed_value = int(raw_value)
            except ValueError as error:
                raise ValueError(
                    f"配置项 {definition.key} 需要整数: {raw_value}"
                ) from error
            return cls._check_range(definition, parsed_value)
        if definition.value_type == "float":
            try:
                parsed_value = float(raw_value)
            except ValueError as error:
                raise ValueError(
                    f"配置项 {definition.key} 需要数字: {raw_value}"
                ) from error
            return cls._check_range(definition, parsed_value)
        if definition.value_type == "str":
            return raw_value
        raise ValueError(f"配置项 {definition.key} 的类型非法: {definition.value_type}")

    @classmethod
    def _validate_api_value(cls, definition: SettingDefinition, raw_value: Any) -> Any:
        """校验来自 Web API 的原始值，类型不符时明确报错。"""
        if definition.value_type == "bool":
            if not isinstance(raw_value, bool):
                raise ValueError(f"配置项 {definition.key} 需要布尔值")
            return raw_value
        if definition.value_type == "int":
            if isinstance(raw_value, bool) or not isinstance(raw_value, int):
                raise ValueError(f"配置项 {definition.key} 需要整数")
            return cls._check_range(definition, raw_value)
        if definition.value_type == "float":
            if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
                raise ValueError(f"配置项 {definition.key} 需要数字")
            return cls._check_range(definition, float(raw_value))
        if definition.value_type == "str":
            if not isinstance(raw_value, str):
                raise ValueError(f"配置项 {definition.key} 需要字符串")
            if any(character in raw_value for character in ("\n", "\r", "\x00")):
                raise ValueError(f"配置项 {definition.key} 不能包含换行或空字符")
            if definition.key != "NAPCAT_TOKEN" and not raw_value.strip():
                raise ValueError(f"配置项 {definition.key} 不能为空")
            if definition.key == "NAPCAT_WS_URL":
                try:
                    url = urlparse(raw_value)
                    valid = url.scheme in ("ws", "wss") and bool(url.hostname)
                    _port = url.port
                except ValueError:
                    valid = False
                if not valid:
                    raise ValueError(
                        "NapCat WebSocket 地址需要有效的 ws:// 或 wss:// 地址"
                    )
            return raw_value
        raise ValueError(f"配置项 {definition.key} 的类型非法: {definition.value_type}")
