"""日志配置模块"""

import os
import sys
import threading
import time
import inspect
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Dict, Optional, TextIO, Tuple

# ANSI 颜色重置符
RESET: str = "\033[0m"

# 时间戳颜色（灰色，参考 maimbot 的 #808080）
TIMESTAMP_COLOR_HEX: str = "#808080"

# 模块名 -> (控制台短标签, HEX 颜色)
# 标签与消息共用同一颜色，实现"同一行一个颜色"
MODULE_COLORS_HEX: Dict[str, Tuple[str, str]] = {
    "src.websocket.client": ("[websocket]", "#B047F9"),  # 淡紫色
    "src.event.handler": ("[event]", "#1EDC31"),  # 翠绿色
    "src.command.executor": ("[command]", "#FE0000"),  # 红色
    "src.command.parser": ("[command]", "#FE0000"),  # 红色
    "src.message.manager": ("[message]", "#00B4FF"),  # 天蓝色
    "src.download.manager": ("[download]", "#FFB600"),  # 金色
    "src.download.progress_tracker": ("[download]", "#FFB600"),  # 金色
    "src.bot": ("[bot]", "#FF69B4"),  # 粉色
    "src.config.manager": ("[config]", "#808080"),  # 灰色
    "src.platform.compatibility": ("[platform]", "#808080"),  # 灰色
    "src.permission.manager": ("[perm]", "#808080"),  # 灰色
    "src.utils.helpers": ("[utils]", "#808080"),  # 灰色
    "src.utils.batch": ("[batch]", "#808080"),  # 灰色
}

# 未映射模块的默认主题色（白色）
DEFAULT_MODULE_COLOR_HEX: str = "#FFFFFF"

# 级别颜色（WARNING 及以上覆盖模块主题色）
LEVEL_COLORS_HEX: Dict[str, str] = {
    "WARNING": "#FFFF55",  # 黄色
    "ERROR": "#FF5555",  # 红色
    "CRITICAL": "#FF55FF",  # 品红
}


def hex_to_ansi(hex_color: str) -> str:
    """将 HEX 颜色转换为 ANSI 24位真彩色前景转义码"""
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
    return f"\033[38;2;{r};{g};{b}m"


# 由 HEX 定义派生的运行时 ANSI 颜色
TIMESTAMP_COLOR: str = hex_to_ansi(TIMESTAMP_COLOR_HEX)
DEFAULT_MODULE_COLOR: str = hex_to_ansi(DEFAULT_MODULE_COLOR_HEX)
MODULE_STYLES: Dict[str, Tuple[str, str]] = {
    name: (label, hex_to_ansi(hex_color))
    for name, (label, hex_color) in MODULE_COLORS_HEX.items()
}
LEVEL_COLORS: Dict[str, str] = {
    level: hex_to_ansi(hex_color) for level, hex_color in LEVEL_COLORS_HEX.items()
}

# 中国标准时间时区（UTC+8）
CST_TIMEZONE = timezone(timedelta(hours=8))

# 日志级别数值（用于控制台/文件级别过滤）
_LEVEL_NUMBERS: Dict[str, int] = {
    "DEBUG": 10,
    "INFO": 20,
    "WARNING": 30,
    "ERROR": 40,
    "CRITICAL": 50,
}


def _format_cst_time(record_time: Any) -> str:
    """将 record 中的时间转换为中国标准时间字符串（YYYY-MM-DD HH:MM:SS）"""
    if hasattr(record_time, "timestamp"):
        cst_time = datetime.fromtimestamp(record_time.timestamp(), CST_TIMEZONE)
    else:
        cst_time = datetime.fromtimestamp(float(record_time), CST_TIMEZONE)
    return cst_time.strftime("%Y-%m-%d %H:%M:%S")


def _get_level_name(record: Dict[str, Any]) -> str:
    """从 record 字典中安全获取日志级别名称"""
    level = record.get("level")
    if level is None:
        return "UNKNOWN"
    return getattr(level, "name", str(level))


def format_console_record(record: Dict[str, Any]) -> str:
    """控制台日志格式（两段式配色）

    格式: <灰色>HH:MM:SS<重置> <行颜色>模块标签 消息<重置>
    行颜色默认为模块主题色，WARNING 及以上使用级别颜色。
    """
    try:
        time_str = _format_cst_time(record.get("time", time.time())).split(" ", 1)[1]
        name = record.get("name", "")
        level_name = _get_level_name(record)
        message = record.get("message", "")

        # 模块标签与主题色；未映射模块取模块名最后一段作为标签
        label, module_color = MODULE_STYLES.get(
            name, (name.split(".")[-1] if name else "unknown", DEFAULT_MODULE_COLOR)
        )

        # WARNING 及以上级别用级别颜色覆盖模块主题色
        line_color = LEVEL_COLORS.get(level_name, module_color)

        return (
            f"{TIMESTAMP_COLOR}{time_str}{RESET} "
            f"{line_color}{label} {message}{RESET}\n"
        )
    except Exception:  # pylint: disable=broad-exception-caught
        # 格式化器自身异常时输出兜底行，避免日志系统崩溃
        fallback_time = datetime.now(CST_TIMEZONE).strftime("%H:%M:%S")
        return f"{TIMESTAMP_COLOR}{fallback_time}{RESET} \033[91merror 日志格式化失败{RESET}\n"


def format_file_record(record: Dict[str, Any]) -> str:
    """文件日志格式：YYYY-MM-DD HH:MM:SS CST - 模块名 - LEVEL - 消息"""
    try:
        formatted_time = _format_cst_time(record.get("time", time.time()))
        name = record.get("name", "UNKNOWN")
        level_name = _get_level_name(record)
        message = str(record.get("message", ""))
        return f"{formatted_time} CST - {name} - {level_name} - {message}\n"
    except Exception:  # pylint: disable=broad-exception-caught
        # 文件格式化器同样不能抛异常，否则该条日志写入会中断
        fallback_time = datetime.now(CST_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")
        return f"{fallback_time} CST - ERROR - 日志格式化失败\n"


def _get_caller_module_name() -> str:
    """回溯调用栈获取日志调用方模块名（跳过本模块自身的栈帧）"""
    this_file = os.path.abspath(__file__)
    frame = inspect.currentframe()
    while frame is not None:
        caller_file = os.path.abspath(frame.f_globals.get("__file__", ""))
        if caller_file != this_file:
            return str(frame.f_globals.get("__name__", "unknown"))
        frame = frame.f_back
    return "unknown"


def _cleanup_old_logs(log_dir: str, retention_days: int = 7) -> None:
    """删除超过保留天数的 .log 文件"""
    cutoff = time.time() - retention_days * 86400
    for filename in os.listdir(log_dir):
        if not filename.endswith(".log"):
            continue
        path = os.path.join(log_dir, filename)
        if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
            os.remove(path)


class Logger:
    """轻量日志器：控制台 INFO 级 + 文件 DEBUG 级，线程安全"""

    def __init__(self, log_dir: str = "logs") -> None:
        self._lock = threading.Lock()
        self._log_dir = log_dir
        self._console_level: int = _LEVEL_NUMBERS["INFO"]
        self._file_level: int = _LEVEL_NUMBERS["DEBUG"]
        self._current_date: str = ""
        self._file_handle: Optional[TextIO] = None
        os.makedirs(self._log_dir, exist_ok=True)
        _cleanup_old_logs(self._log_dir)

    def _get_file_handle(self) -> TextIO:
        """获取当天日志文件句柄，跨天时自动切换文件"""
        today = time.strftime("%Y-%m-%d")
        if today != self._current_date or self._file_handle is None:
            if self._file_handle is not None:
                self._file_handle.close()
            self._current_date = today
            path = os.path.join(self._log_dir, f"{today}.log")
            # 句柄需跨调用长期持有并复用，不能用 with 立即关闭
            self._file_handle = open(  # pylint: disable=consider-using-with
                path, "a", encoding="utf-8"
            )
        return self._file_handle

    def _log(self, level_name: str, message: str) -> None:
        """构造 record 并分发到控制台与文件两个输出端"""
        level_no = _LEVEL_NUMBERS[level_name]
        record: Dict[str, Any] = {
            "time": datetime.now(CST_TIMEZONE),
            "name": _get_caller_module_name(),
            "level": SimpleNamespace(name=level_name),
            "message": message,
        }
        with self._lock:
            if level_no >= self._console_level:
                sys.stdout.write(format_console_record(record))
                sys.stdout.flush()
            if level_no >= self._file_level:
                handle = self._get_file_handle()
                handle.write(format_file_record(record))
                handle.flush()

    def debug(self, message: str) -> None:
        """输出 DEBUG 级别日志（仅写入文件）"""
        self._log("DEBUG", message)

    def info(self, message: str) -> None:
        """输出 INFO 级别日志"""
        self._log("INFO", message)

    def warning(self, message: str) -> None:
        """输出 WARNING 级别日志"""
        self._log("WARNING", message)

    def error(self, message: str) -> None:
        """输出 ERROR 级别日志"""
        self._log("ERROR", message)

    def critical(self, message: str) -> None:
        """输出 CRITICAL 级别日志"""
        self._log("CRITICAL", message)


def setup_logger() -> Logger:
    """
    创建日志系统实例

    控制台输出使用两段式配色（灰色时间戳 + 模块色整行）；
    文件输出保留完整时间戳、模块名和日志级别，便于事后排查。

    Returns:
        配置后的Logger实例
    """
    return Logger()


logger: Logger = setup_logger()
