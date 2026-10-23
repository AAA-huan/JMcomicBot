"""配置管理器模块，负责加载和管理应用程序配置"""

from typing import Dict, List, Optional, Union, overload

import os

from dotenv import dotenv_values, find_dotenv, set_key

from src.logging.logger_config import logger


def _parse_bool_config(name: str, raw_value: Optional[str], default: bool) -> bool:
    """解析布尔配置，未配置时使用默认值，非法值直接暴露配置错误。"""
    if raw_value is None:
        return default
    normalized = raw_value.strip().lower()
    if normalized in ("true", "1", "yes", "on"):
        return True
    if normalized in ("false", "0", "no", "off"):
        return False
    raise ValueError(f"{name} 必须是布尔值")


def _parse_int_config(
    name: str,
    raw_value: Optional[str],
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    """解析有明确范围的整数配置，未配置时使用默认值。"""
    raw_value = str(default) if raw_value is None else raw_value
    try:
        value = int(raw_value)
    except ValueError as error:
        raise ValueError(f"{name} 必须是整数") from error
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} 必须位于 {minimum} 到 {maximum} 之间")
    return value


class ConfigManager:
    """配置管理器类，负责加载和管理应用程序配置"""

    def __init__(self, env_file: Optional[str] = None):
        """初始化配置管理器"""
        self.env_file = os.path.abspath(env_file or find_dotenv() or ".env")
        self.logger = logger
        self.config_dict: Dict[str, Union[str, int, float, bool]] = {}
        self._dotenv_values: Dict[str, Optional[str]] = {}
        # 进程启动时 .env 的原始快照，仅用于识别旧版 load_dotenv 注入的残留值
        self._startup_dotenv_values: Dict[str, Optional[str]] = {}
        self.group_whitelist: List[str] = []
        self.private_whitelist: List[str] = []
        self.global_blacklist: List[str] = []
        self.delete_permission_user: List[str] = []
        self.webui_dev_origins: List[str] = []

    @overload
    def _get_env(self, name: str) -> Optional[str]: ...

    @overload
    def _get_env(self, name: str, default: str) -> str: ...

    def _get_env(self, name: str, default: Optional[str] = None) -> Optional[str]:
        """读取配置值：显式环境变量优先，其次 .env，最后默认值。

        这里刻意不使用 load_dotenv 写入 os.environ：否则当前进程会残留旧值，
        自重启的子进程继承该旧值后，load_dotenv 默认不覆盖，导致设置页修改的
        启动项在重启后回退。
        """
        if name in os.environ:
            return os.environ[name]
        value = self._dotenv_values.get(name)
        return default if value is None else value

    def save_restart_setting(self, key: str, value: str) -> None:
        """原子更新启动配置文件，不改变当前进程的环境变量或运行配置。"""
        success, _key, _value = set_key(self.env_file, key, value)
        if not success:
            raise OSError("无法保存启动配置文件")

    def build_restart_environment(self) -> Dict[str, str]:
        """构造网页一键重启使用的新进程环境。

        普通启动遵循“显式环境变量优先于 .env”，因此重启时必须保留与启动时
        .env 值不同的显式覆盖（例如部署时注入的数据库路径或 WebUI 端口）。
        旧版本 load_dotenv 注入的环境变量值会与启动时 .env 快照一致，只有
        这类残留值才需要移除，让 exec 后的新进程重新读取最新 .env。
        """
        environment = dict(os.environ)
        latest_dotenv = dotenv_values(self.env_file)
        managed_keys = set(self.config_dict) | {
            "GROUP_WHITELIST",
            "PRIVATE_WHITELIST",
            "GLOBAL_BLACKLIST",
            "DELETE_PERMISSION_USER",
        }
        for key in set(latest_dotenv) & managed_keys:
            startup_value = self._startup_dotenv_values.get(key)
            if key in environment and environment[key] == startup_value:
                environment.pop(key, None)
        return environment

    def load_config(self):
        """加载.env文件到内存配置（覆盖默认配置中同名项）"""
        # 读取 .env，但不写入 os.environ，避免自重启继承旧配置值
        self._dotenv_values = dotenv_values(self.env_file)
        self._startup_dotenv_values = dict(self._dotenv_values)
        # 初始化配置
        # 简化token配置，只使用NAPCAT_TOKEN作为唯一的token配置项
        token = self._get_env("NAPCAT_TOKEN", "")

        # 构建带token的WebSocket URL（如果有token）
        base_ws_url = self._get_env("NAPCAT_WS_URL", "ws://localhost:8080/qq")
        if token:
            # 检查URL是否已经包含查询参数
            if "?" in base_ws_url:
                ws_url = f"{base_ws_url}&token={token}"
            else:
                ws_url = f"{base_ws_url}?token={token}"
        else:
            ws_url = base_ws_url

        # 获取下载路径配置
        download_path = self._get_env("MANGA_DOWNLOAD_PATH", "./downloads")
        # 处理Linux系统中的波浪号(~)路径，将其扩展为用户主目录
        if download_path.startswith("~"):
            download_path = os.path.expanduser(download_path)
        # 将相对路径转换为绝对路径，确保父级目录引用能正确解析
        absolute_download_path = os.path.abspath(download_path)

        # 获取内存低占用模式配置
        low_memory_mode_str = self._get_env("LOW_MEMORY_MODE", "false").lower()
        low_memory_mode = low_memory_mode_str in ("true", "1", "yes", "on")

        # 获取低内存模式下的文件删除延迟时间（分钟）
        low_memory_delete_delay_str = self._get_env("LOW_MEMORY_DELETE_DELAY", "3")
        try:
            low_memory_delete_delay = int(low_memory_delete_delay_str)
            if low_memory_delete_delay < 1:
                low_memory_delete_delay = 3
        except ValueError:
            low_memory_delete_delay = 3

        # 获取文件发送间隔（秒）
        file_send_interval_str = self._get_env("FILE_SEND_INTERVAL", "1.8")
        try:
            file_send_interval = float(file_send_interval_str)
            if file_send_interval < 1:
                file_send_interval = 1.8
        except ValueError:
            file_send_interval = 1.8

        # 获取文件发送每批数量
        file_send_batch_size_str = self._get_env("FILE_SEND_BATCH_SIZE", "10")
        try:
            file_send_batch_size = int(file_send_batch_size_str)
            if file_send_batch_size < 1:
                file_send_batch_size = 10
        except ValueError:
            file_send_batch_size = 10

        # 获取每批文件发送的间隔（秒）
        file_send_batch_interval_str = self._get_env("FILE_SEND_BATCH_INTERVAL", "7")
        try:
            file_send_batch_interval = float(file_send_batch_interval_str)
            if file_send_batch_interval < 1:
                file_send_batch_interval = 7
        except ValueError:
            file_send_batch_interval = 7

        # 获取文件发送重连等待超时（秒）
        send_retry_timeout_str = self._get_env("SEND_RETRY_TIMEOUT", "30")
        try:
            send_retry_timeout = int(send_retry_timeout_str)
            if send_retry_timeout < 1:
                send_retry_timeout = 30
        except ValueError:
            send_retry_timeout = 30

        # 获取断线文件确认重发的等待超时（秒）
        resend_confirm_timeout_str = self._get_env("RESEND_CONFIRM_TIMEOUT", "300")
        try:
            resend_confirm_timeout = int(resend_confirm_timeout_str)
            if resend_confirm_timeout < 1:
                resend_confirm_timeout = 300
        except ValueError:
            resend_confirm_timeout = 300

        # 获取SQLite数据库目录配置，处理路径并转换为绝对路径
        db_path = self._get_env("DB_PATH", "./data")
        if db_path.startswith("~"):
            db_path = os.path.expanduser(db_path)
        absolute_db_path = os.path.abspath(db_path)

        # 获取数据库SQL日志开关
        db_echo_str = self._get_env("DB_ECHO", "false").lower()
        db_echo = db_echo_str in ("true", "1", "yes", "on")

        webui_enabled = _parse_bool_config(
            "WEBUI_ENABLED", self._get_env("WEBUI_ENABLED"), True
        )
        # 拉黑与删除的绑定开关：默认关闭，非法值在启动时直接报错
        blacklist_delete_binding = _parse_bool_config(
            "BLACKLIST_DELETE_BINDING",
            self._get_env("BLACKLIST_DELETE_BINDING"),
            False,
        )
        webui_host = (self._get_env("WEBUI_HOST", "127.0.0.1") or "").strip()
        if not webui_host:
            raise ValueError("WEBUI_HOST 不能为空")
        webui_port = _parse_int_config(
            "WEBUI_PORT", self._get_env("WEBUI_PORT"), 7999, 1, 65535
        )
        webui_session_hours = _parse_int_config(
            "WEBUI_SESSION_HOURS",
            self._get_env("WEBUI_SESSION_HOURS"),
            24,
            1,
            24 * 30,
        )
        # 开发环境额外允许的页面来源（Vite 开发服务器），生产默认留空
        webui_dev_origins_raw = self._get_env("WEBUI_DEV_ORIGINS", "") or ""
        webui_dev_origins = self._parse_id_list(webui_dev_origins_raw)
        for origin in webui_dev_origins:
            if not origin.startswith(("http://", "https://")):
                raise ValueError(f"WEBUI_DEV_ORIGINS 必须是完整的来源地址: {origin}")

        self.config_dict: Dict[str, Union[str, int, float, bool]] = {
            "MANGA_DOWNLOAD_PATH": absolute_download_path,
            "NAPCAT_WS_URL": ws_url,
            "NAPCAT_TOKEN": token,
            "BLACKLIST_DELETE_BINDING": blacklist_delete_binding,
            "LOW_MEMORY_MODE": low_memory_mode,
            "LOW_MEMORY_DELETE_DELAY": low_memory_delete_delay,
            "FILE_SEND_INTERVAL": file_send_interval,
            "FILE_SEND_BATCH_SIZE": file_send_batch_size,
            "FILE_SEND_BATCH_INTERVAL": file_send_batch_interval,
            "SEND_RETRY_TIMEOUT": send_retry_timeout,
            "RESEND_CONFIRM_TIMEOUT": resend_confirm_timeout,
            "DB_PATH": absolute_db_path,
            "DB_ECHO": db_echo,
            "WEBUI_ENABLED": webui_enabled,
            "WEBUI_HOST": webui_host,
            "WEBUI_PORT": webui_port,
            "WEBUI_SESSION_HOURS": webui_session_hours,
            "WEBUI_DEV_ORIGINS": self._get_env("WEBUI_DEV_ORIGINS", ""),
        }

        # 初始化黑白名单配置
        self.group_whitelist: List[str] = self._parse_id_list(
            self._get_env("GROUP_WHITELIST", "")
        )
        self.private_whitelist: List[str] = self._parse_id_list(
            self._get_env("PRIVATE_WHITELIST", "")
        )
        self.global_blacklist: List[str] = self._parse_id_list(
            self._get_env("GLOBAL_BLACKLIST", "")
        )
        # 初始化删除权限用户名单配置
        self.delete_permission_user: List[str] = self._parse_id_list(
            self._get_env("DELETE_PERMISSION_USER", "")
        )
        # WebUI 开发环境额外允许的页面来源
        self.webui_dev_origins: List[str] = webui_dev_origins
        # 记录黑白名单配置信息
        self.logger.info(
            f"黑白名单配置加载完成 - "
            f"群组白名单: {len(self.group_whitelist)}个, "
            f"私信白名单: {len(self.private_whitelist)}个, "
            f"全局黑名单: {len(self.global_blacklist)}个, "
            f"删除权限用户: {len(self.delete_permission_user)}个"
        )

    def _parse_id_list(self, id_string: str) -> List[str]:
        """
        解析ID列表字符串，将逗号分隔的ID转换为列表

        Args:
            id_string: 逗号分隔的ID字符串

        Returns:
            清理后的ID列表
        """
        if not id_string or not id_string.strip():
            return []

        # 分割字符串并清理每个ID
        ids = [id.strip() for id in id_string.split(",") if id.strip()]
        return ids

    def make_download_dir(self) -> None:
        """创建下载目录"""
        download_path = str(self.config_dict["MANGA_DOWNLOAD_PATH"])
        os.makedirs(download_path, exist_ok=True)
        self.logger.info(f"下载路径设置为: {download_path}")

    def get(
        self, key: str, default: Union[str, int, float, bool] = ""
    ) -> Union[str, int, float, bool]:
        """获取配置值"""
        return self.config_dict.get(key, default)

    def set(self, key: str, value: Union[str, int, float, bool]) -> None:
        """设置配置值"""
        self.config_dict[key] = value
