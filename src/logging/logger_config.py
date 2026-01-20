"""日志配置模块"""

import os
import sys
import time
from datetime import datetime, timezone, timedelta
from typing import Any

from loguru import logger as loguru_logger


class LoggerConfig:
    """日志配置类，负责配置loguru日志系统"""

    def __init__(self) -> None:
        """初始化日志配置"""
        self.setup_logger()

    def setup_logger(self) -> Any:
        """
        配置loguru日志系统

        Returns:
            配置后的logger实例
        """
        loguru_logger.remove()

        log_dir: str = "logs"
        os.makedirs(log_dir, exist_ok=True)
        log_file: str = os.path.join(log_dir, f'{time.strftime("%Y-%m-%d")}.log')

        def cst_formatter(record):
            try:
                cst_timezone = timezone(timedelta(hours=8))
                timestamp = record.get("time", time.time())

                if hasattr(timestamp, "timestamp"):
                    cst_time = datetime.fromtimestamp(timestamp.timestamp(), cst_timezone)
                else:
                    cst_time = datetime.fromtimestamp(timestamp, cst_timezone)

                formatted_time = cst_time.strftime("%Y-%m-%d %H:%M:%S")

                name = record.get("name", "UNKNOWN")
                level_name = record.get("level", type("obj", (object,), {"name": "UNKNOWN"})).name
                message = record.get("message", "")

                safe_message = str(message).replace("{", "{{").replace("}", "}}")
                return f"{formatted_time} CST - {name} - {level_name} - {safe_message}\n"
            except Exception:
                fallback_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                return f"{fallback_time} CST - ERROR - 日志格式化失败\n"

        loguru_logger.add(
            sys.stdout,
            level="INFO",
            format=cst_formatter,
            colorize=False,
        )

        loguru_logger.add(
            log_file,
            level="DEBUG",
            format=cst_formatter,
            encoding="utf-8",
            rotation="00:00",
            retention="7 days",
        )

        return loguru_logger


logger = LoggerConfig().setup_logger()
