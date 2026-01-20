import os
from dotenv import load_dotenv
from typing import Dict, Union, List

from src.logging.logger_config import logger


class ConfigManager:
    def __init__(self):
        self.logger = logger
        self.config: Dict[str, Union[str, int]] = {}
        self.group_whitelist: List[str] = []
        self.private_whitelist: List[str] = []
        self.global_blacklist: List[str] = []
        self.delete_permission_user: List[str] = []

    def load_config(self):
        """加载.env文件到内存配置（覆盖默认配置中同名项）"""
        # 加载环境变量
        load_dotenv()
        # 初始化配置
        # 简化token配置，只使用NAPCAT_TOKEN作为唯一的token配置项
        token = os.getenv("NAPCAT_TOKEN", "")

        # 构建带token的WebSocket URL（如果有token）
        base_ws_url = os.getenv("NAPCAT_WS_URL", "ws://localhost:8080/qq")
        if token:
            # 检查URL是否已经包含查询参数
            if "?" in base_ws_url:
                ws_url = f"{base_ws_url}&token={token}"
            else:
                ws_url = f"{base_ws_url}?token={token}"
        else:
            ws_url = base_ws_url

        # 获取下载路径配置
        download_path = os.getenv("MANGA_DOWNLOAD_PATH", "./downloads")
        # 处理Linux系统中的波浪号(~)路径，将其扩展为用户主目录
        if download_path.startswith("~"):
            download_path = os.path.expanduser(download_path)
        # 将相对路径转换为绝对路径，确保父级目录引用能正确解析
        absolute_download_path = os.path.abspath(download_path)

        self.config: Dict[str, Union[str, int]] = {
            "MANGA_DOWNLOAD_PATH": absolute_download_path,
            "NAPCAT_WS_URL": ws_url,  # 存储完整的WebSocket URL（可能包含token）
            "NAPCAT_TOKEN": token,  # 使用NAPCAT_TOKEN作为配置键
        }

        # 初始化黑白名单配置
        self.group_whitelist: List[str] = self._parse_id_list(
            os.getenv("GROUP_WHITELIST", "")
        )
        self.private_whitelist: List[str] = self._parse_id_list(
            os.getenv("PRIVATE_WHITELIST", "")
        )
        self.global_blacklist: List[str] = self._parse_id_list(
            os.getenv("GLOBAL_BLACKLIST", "")
        )
        # 初始化删除权限用户名单配置
        self.delete_permission_user: List[str] = self._parse_id_list(
            os.getenv("DELETE_PERMISSION_USER", "")
        )
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

    def make_download_dir(self):
        # 创建下载目录
        os.makedirs(self.config["MANGA_DOWNLOAD_PATH"], exist_ok=True)
        self.logger.info(f"下载路径设置为: {self.config['MANGA_DOWNLOAD_PATH']}")

    def get(self, key: str, default: Union[str, int] = "") -> Union[str, int]:
        """获取配置值"""
        return self.config.get(key, default)

    def set(self, key: str, value: Union[str, int]) -> None:
        """设置配置值"""
        self.config[key] = value
