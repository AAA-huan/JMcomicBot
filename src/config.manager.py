from typing import Dict, Union
from dotenv import load_dotenv
import os



class ConfigManager:
    def __init__(self, file_path: str):
        self.config: Dict[str, Union[str, int]] = {}
        self.file_path: str = file_path
        
    def load_config(self):
        """加载.env文件到内存配置（覆盖默认配置中同名项）"""
        # 加载环境变量
        load_dotenv(self.file_path)
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

        
