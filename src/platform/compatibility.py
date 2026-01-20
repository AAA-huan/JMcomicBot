import os
import platform
import subprocess
import sys
from typing import List

from src.logging.logger_config import logger


class PlatformChecker:
    """平台兼容性检查器，负责检查操作系统和Python版本兼容性"""

    SUPPORTED_PLATFORMS: List[str] = ["linux", "windows"]
    MIN_PYTHON_VERSION: tuple = (3, 7)

    def __init__(self) -> None:
        """初始化平台检查器"""
        self.logger = logger
        self.current_platform = platform.system().lower()
        self.python_version = platform.python_version()

    def check_compatibility(self) -> None:
        """
        检查操作系统兼容性，确保在Linux和Windows上都能正常运行

        Raises:
            OSError: 当操作系统不支持时
            RuntimeError: 当Python版本过低时
        """
        self.logger.info(f"检测到操作系统: {self.current_platform}")
        self.logger.info(f"Python版本: {self.python_version}")

        self._check_platform()
        self._check_python_version()

        if self.current_platform == "linux":
            self._check_linux_requirements()
        elif self.current_platform == "windows":
            self._check_windows_requirements()

        self.logger.info(f"平台兼容性检查通过: {self.current_platform}")

    def _check_platform(self) -> None:
        """
        检查操作系统是否支持

        Raises:
            OSError: 当操作系统不支持时
        """
        if self.current_platform not in self.SUPPORTED_PLATFORMS:
            error_msg = f"不支持的平台: {self.current_platform}。仅支持 {self.SUPPORTED_PLATFORMS}"
            self.logger.error(error_msg)
            raise OSError(error_msg)

    def _check_python_version(self) -> None:
        """
        检查Python版本是否符合要求

        Raises:
            RuntimeError: 当Python版本过低时
        """
        python_version_tuple = sys.version_info
        if python_version_tuple < self.MIN_PYTHON_VERSION:
            error_msg = (
                f"Python版本过低: {self.python_version}。"
                f"需要Python {self.MIN_PYTHON_VERSION[0]}.{self.MIN_PYTHON_VERSION[1]}或更高版本"
            )
            self.logger.error(error_msg)
            raise RuntimeError(error_msg)

    def _check_linux_requirements(self) -> None:
        """检查Linux系统特定要求"""
        self.logger.info("执行Linux系统要求检查...")

        required_commands: List[str] = ["python3", "pip3"]
        for cmd in required_commands:
            try:
                result = subprocess.run(["which", cmd], capture_output=True, text=True)
                if result.returncode != 0:
                    self.logger.warning(f"未找到命令: {cmd}。请确保已安装")
            except Exception as e:
                self.logger.warning(f"检查命令 {cmd} 时出错: {e}")

        current_dir = os.getcwd()
        if not os.access(current_dir, os.W_OK):
            self.logger.warning(f"当前目录没有写权限: {current_dir}")

    def _check_windows_requirements(self) -> None:
        """检查Windows系统特定要求"""
        self.logger.info("执行Windows系统要求检查...")

        python_exe = sys.executable
        if "python" not in python_exe.lower():
            self.logger.warning("Python执行路径可能不正确")

        if "\\" not in os.path.sep:
            self.logger.warning("路径分隔符可能不兼容Windows")

    def get_platform_info(self) -> dict:
        """
        获取平台信息

        Returns:
            dict: 包含平台信息的字典
        """
        return {
            "system": self.current_platform,
            "python_version": self.python_version,
            "release": platform.release(),
            "machine": platform.machine(),
        }
