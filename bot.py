import json
import logging
import os
import re
import platform
import sys
import threading
import time
import signal
from typing import Any, Callable, Dict, List, Optional, Union

import jmcomic
import websocket
from dotenv import load_dotenv

class MangaBot:
    # 机器人版本号
    VERSION = "2.2.8"
    
    def __init__(self) -> None:
        """初始化MangaBot机器人，添加跨平台兼容性检查"""
        # 配置日志（先初始化日志系统）
        self._setup_logger()
        # 记录启动信息，包含版本号
        logging.info(f"JMComic QQ机器人 版本 {self.VERSION} 启动中...")

        # 检查操作系统兼容性
        self._check_platform_compatibility()

        # 加载环境变量
        load_dotenv()

        # 初始化配置
        # 简化token配置，只使用NAPCAT_TOKEN作为唯一的token配置项
        token = os.getenv("NAPCAT_TOKEN", "")  # 只使用NAPCAT_TOKEN
            
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
            
        self.config: Dict[str, Union[str, int]] = {
            "MANGA_DOWNLOAD_PATH": os.getenv("MANGA_DOWNLOAD_PATH", "./downloads"),
            "NAPCAT_WS_URL": ws_url,  # 存储完整的WebSocket URL（可能包含token）
            "NAPCAT_TOKEN": token,  # 使用NAPCAT_TOKEN作为配置键
        }

        # 初始化属性
        self.ws: Optional[websocket.WebSocketApp] = None  # WebSocket连接对象
        self.SELF_ID: Optional[str] = None  # 存储机器人自身的QQ号
        self.downloading_mangas: Dict[str, bool] = (
            {}
        )  # 跟踪正在下载的漫画 {manga_id: True}

        # 创建下载目录
        os.makedirs(self.config["MANGA_DOWNLOAD_PATH"], exist_ok=True)

    def _check_platform_compatibility(self) -> None:
        """检查操作系统兼容性，确保在Linux和Windows上都能正常运行"""
        current_platform: str = platform.system().lower()
        python_version: str = platform.python_version()

        self.logger.info(f"检测到操作系统: {current_platform}")
        self.logger.info(f"Python版本: {python_version}")

        # 检查支持的操作系统
        supported_platforms: List[str] = ["linux", "windows"]
        if current_platform not in supported_platforms:
            error_msg: str = (
                f"不支持的平台: {current_platform}。仅支持 {supported_platforms}"
            )
            self.logger.error(error_msg)
            raise OSError(error_msg)

        # 检查Python版本
        python_version_tuple: tuple = sys.version_info
        if python_version_tuple < (3, 7):
            error_msg: str = (
                f"Python版本过低: {python_version}。需要Python 3.7或更高版本"
            )
            self.logger.error(error_msg)
            raise RuntimeError(error_msg)

        # 平台特定的检查
        if current_platform == "linux":
            self._check_linux_requirements()
        elif current_platform == "windows":
            self._check_windows_requirements()

        self.logger.info(f"平台兼容性检查通过: {current_platform}")

    def _check_linux_requirements(self) -> None:
        """检查Linux系统特定要求"""
        self.logger.info("执行Linux系统要求检查...")

        # 检查必要的系统命令
        required_commands: List[str] = ["python3", "pip3"]
        for cmd in required_commands:
            try:
                import subprocess

                result = subprocess.run(["which", cmd], capture_output=True, text=True)
                if result.returncode != 0:
                    self.logger.warning(f"未找到命令: {cmd}。请确保已安装")
            except Exception as e:
                self.logger.warning(f"检查命令 {cmd} 时出错: {e}")

        # 检查文件权限
        current_dir: str = os.getcwd()
        if not os.access(current_dir, os.W_OK):
            self.logger.warning(f"当前目录没有写权限: {current_dir}")

    def _check_windows_requirements(self) -> None:
        """检查Windows系统特定要求"""
        self.logger.info("执行Windows系统要求检查...")

        # 检查Python路径
        python_exe: str = sys.executable
        if "python" not in python_exe.lower():
            self.logger.warning("Python执行路径可能不正确")

        # 检查Windows特定路径分隔符
        if "\\" not in os.path.sep:
            self.logger.warning("路径分隔符可能不兼容Windows")

    def _setup_logger(self) -> None:
        """配置日志系统，支持跨平台颜色显示"""
        # 创建logger对象
        self.logger: logging.Logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.DEBUG)
        # 阻止日志消息向上传播到父logger，避免重复输出
        self.logger.propagate = False

        # 定义跨平台颜色格式化器
        class CrossPlatformFormatter(logging.Formatter):
            # ANSI颜色代码（支持Linux和Windows 10+）
            COLORS: Dict[str, str] = {
                "DEBUG": "\033[36m",  # 青色
                "INFO": "\033[34m",  # 蓝色
                "WARNING": "\033[33m",  # 黄色
                "ERROR": "\033[31m",  # 红色
                "CRITICAL": "\033[41m\033[37m",  # 红色背景白色文字
                "RESET": "\033[0m",  # 重置
            }

            def __init__(
                self, fmt: Optional[str] = None, datefmt: Optional[str] = None
            ) -> None:
                super().__init__(fmt, datefmt)
                self.supports_color: bool = self._check_color_support()

            def _check_color_support(self) -> bool:
                """检查终端是否支持颜色"""
                # 检查是否在终端中运行
                if not sys.stdout.isatty():
                    return False

                # 检查平台
                current_platform: str = platform.system().lower()
                if current_platform == "windows":
                    # Windows 10+ 支持ANSI颜色
                    try:
                        import ctypes

                        kernel32 = ctypes.windll.kernel32
                        # 检查是否支持虚拟终端序列
                        return bool(
                            kernel32.GetConsoleMode(kernel32.GetStdHandle(-11)) & 0x0004
                        )
                    except:
                        return False
                elif current_platform == "linux":
                    # Linux通常支持颜色
                    return True
                else:
                    # 其他平台默认不支持
                    return False

            def format(self, record: logging.LogRecord) -> str:
                """格式化日志记录"""
                # 获取原始日志格式
                log_message: str = super().format(record)

                # 如果支持颜色，添加颜色
                if self.supports_color:
                    color_start: str = self.COLORS.get(record.levelname, "")
                    color_end: str = self.COLORS["RESET"]
                    return f"{color_start}{log_message}{color_end}"
                else:
                    # 不支持颜色，返回原始消息
                    return log_message

        # 创建文件格式化器（无颜色）
        file_formatter: logging.Formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )

        # 创建控制台格式化器（跨平台颜色）
        console_formatter: CrossPlatformFormatter = CrossPlatformFormatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )

        # 创建控制台处理器
        console_handler: logging.StreamHandler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(console_formatter)

        # 创建文件处理器，每天一个日志文件
        log_dir: str = "logs"
        os.makedirs(log_dir, exist_ok=True)
        log_file: str = os.path.join(log_dir, f'{time.strftime("%Y-%m-%d")}.log')
        file_handler: logging.FileHandler = logging.FileHandler(
            log_file, encoding="utf-8"
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(file_formatter)

        # 清除已有的处理器
        if self.logger.handlers:
            self.logger.handlers.clear()

        # 添加处理器到logger
        self.logger.addHandler(console_handler)
        self.logger.addHandler(file_handler)

        # 重新定义根logger以确保所有模块的日志也被捕获
        root_logger: logging.Logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)
        if root_logger.handlers:
            root_logger.handlers.clear()

        # 为root logger创建新的处理器实例，避免与self.logger共享处理器
        root_console_handler: logging.StreamHandler = logging.StreamHandler()
        root_console_handler.setLevel(logging.INFO)
        root_console_handler.setFormatter(console_formatter)

        root_file_handler: logging.FileHandler = logging.FileHandler(
            log_file, encoding="utf-8"
        )
        root_file_handler.setLevel(logging.DEBUG)
        root_file_handler.setFormatter(file_formatter)

        root_logger.addHandler(root_console_handler)
        root_logger.addHandler(root_file_handler)

    def send_message(
        self,
        user_id: str,
        message: str,
        group_id: Optional[str] = None,
        private: bool = True,
    ) -> None:
        """发送消息函数"""
        try:
            payload: Dict[str, Any]
            if private:
                # 发送私聊消息
                payload = {
                    "action": "send_private_msg",
                    "params": {"user_id": user_id, "message": message},
                }
            else:
                # 发送群消息
                payload = {
                    "action": "send_group_msg",
                    "params": {"group_id": group_id, "message": message},
                }

            # 如果配置了Token，添加到请求中
            if self.config["NAPCAT_TOKEN"]:
                payload["params"]["access_token"] = self.config["NAPCAT_TOKEN"]

            # 通过WebSocket发送消息
            if self.ws and self.ws.sock and self.ws.sock.connected:
                message_json: str = json.dumps(payload)
                self.ws.send(message_json)
                self.logger.info(f"消息发送成功: {message[:20]}...")
            else:
                self.logger.warning("WebSocket连接未建立，消息发送失败")
        except Exception as e:
            self.logger.error(f"发送消息失败: {e}")

    def send_file(self, user_id, file_path, group_id=None, private=True):
        # 发送文件函数
        try:
            # 添加详细调试日志
            self.logger.debug(
                f"准备发送文件: {file_path}, 用户ID: {user_id}, 群ID: {group_id}, 私聊模式: {private}"
            )

            if not os.path.exists(file_path):
                self.logger.error(f"文件不存在: {file_path}")
                error_msg = f"❌ 文件不存在哦~，请让我下载之后再发送(｡•﹃•｡)"
                self.send_message(user_id, error_msg, group_id, private)
                return

            # 检查文件是否可读
            if not os.access(file_path, os.R_OK):
                self.logger.error(f"文件不可读: {file_path}")
                error_msg = f"❌ 文件不可读，叫主人帮我检查一下吧∑(O_O；)"
                self.send_message(user_id, error_msg, group_id, private)
                return

            # 获取文件名
            file_name = os.path.basename(file_path)
            self.logger.debug(f"原始文件名: {file_name}")

            # 简化处理：直接使用原始的绝对路径
            file_path_to_send = os.path.abspath(file_path)
            self.logger.debug(f"使用原始绝对路径: {file_path_to_send}")

            # 直接使用消息段数组方式发送文件，这是NapCat支持的方式
            self.logger.info(f"使用消息段数组方式发送文件")

            # 构建消息段数组
            message_segments = [
                {"type": "file", "data": {"file": file_path_to_send, "name": file_name}}
            ]

            # 发送消息
            if private:
                payload = {
                    "action": "send_private_msg",
                    "params": {"user_id": user_id, "message": message_segments},
                }
            else:
                payload = {
                    "action": "send_group_msg",
                    "params": {"group_id": group_id, "message": message_segments},
                }

            if self.config["NAPCAT_TOKEN"]:
                payload["params"]["access_token"] = self.config["NAPCAT_TOKEN"]

            if self.ws and self.ws.sock and self.ws.sock.connected:
                message_json = json.dumps(payload)
                self.logger.debug(f"发送消息段数组文件: {message_json}")
                self.ws.send(message_json)
                self.logger.info(f"使用消息段数组发送文件请求已发送: {file_name}")
                # 等待一小段时间让API请求有机会返回结果
                time.sleep(1)
            else:
                self.logger.warning("WebSocket连接未建立，文件发送失败")
                raise Exception("WebSocket连接未建立")

        except Exception as e:
            self.logger.error(f"发送文件失败: {e}")
            error_msg = f"❌ 发送文件失败: {str(e)}\n快让主人帮我检查一下ヽ(ﾟДﾟ)ﾉ"
            self.send_message(user_id, error_msg, group_id, private)

    def on_message(self, ws, message):
        # WebSocket消息处理函数
        try:
            self.logger.info(f"收到WebSocket消息: {message[:100]}...")
            data = json.loads(message)
            # 处理接收到的消息
            self.handle_event(data)
        except Exception as e:
            self.logger.error(f"处理WebSocket消息出错: {e}")

    def on_close(self, ws, close_status_code, close_msg):
        # WebSocket连接关闭处理
        self.logger.info(f"WebSocket连接已关闭: {close_status_code} - {close_msg}")

    def on_error(self, ws, error):
        # WebSocket连接错误处理
        self.logger.error(f"WebSocket连接错误: {error}")

    def on_open(self, ws):
        # WebSocket连接打开处理
        self.logger.info("WebSocket连接已打开")

    def connect_websocket(self):
        # 连接WebSocket的函数
        try:
            # 记录连接信息时不显示token，保护安全
            ws_url_display = self.config['NAPCAT_WS_URL']
            if 'token=' in ws_url_display:
                # 隐藏token值，只显示部分信息
                parts = ws_url_display.split('token=')
                ws_url_display = f"{parts[0]}token=****"
                
            self.logger.info(f"正在连接WebSocket: {ws_url_display}")
            self.ws = websocket.WebSocketApp(
                self.config["NAPCAT_WS_URL"],  # 这里使用完整的URL，可能已包含token
                on_open=self.on_open,
                on_message=self.on_message,
                on_error=self.on_error,
                on_close=self.on_close,
                # 可选：添加额外的HTTP头进行token认证
                header={
                    'Authorization': (
                        f'Bearer {self.config["NAPCAT_TOKEN"]}'
                        if self.config["NAPCAT_TOKEN"]
                        else None
                    )
                }
            )

            # 启动WebSocket线程，添加重连选项
            threading.Thread(
                target=lambda: self.ws.run_forever(
                    ping_interval=30, ping_timeout=10, reconnect=5
                ),
                daemon=True,
            ).start()
            self.logger.info("WebSocket连接启动成功，将自动尝试重连")
        except Exception as e:
            self.logger.error(f"连接WebSocket失败: {e}")

    def websocket_reconnect_manager(self):
        # WebSocket重连管理线程
        while True:
            time.sleep(10)  # 每10秒检查一次连接状态

            if self.ws and (not self.ws.sock or not self.ws.sock.connected):
                self.logger.info("检测到WebSocket未连接，尝试重新连接...")
                try:
                    # 关闭现有连接
                    if self.ws:
                        self.ws.close()
                    # 重新连接
                    self.connect_websocket()
                except Exception as e:
                    self.logger.error(f"重连WebSocket失败: {e}")

    def handle_event(self, data):
        # 事件处理函数
        # 调试日志，记录所有收到的事件
        self.logger.debug(
            f"收到事件: {data.get('post_type')}, {data.get('meta_event_type') or data.get('message_type')}"
        )

        # 直接从消息的根级别获取self_id
        if "self_id" in data and data["self_id"]:
            if not self.SELF_ID or self.SELF_ID != data["self_id"]:
                self.SELF_ID = data["self_id"]
                self.logger.info(f"从消息中获取到自身ID: {self.SELF_ID}")

        # 处理元事件
        if data.get("post_type") == "meta_event":
            return

        # 处理私聊消息（私聊消息无需@）
        if data.get("post_type") == "message" and data.get("message_type") == "private":
            user_id = data.get("user_id")
            message = data.get("raw_message")
            self.logger.info(f"收到私聊消息 - 用户{user_id}: {message}")
            # 确保私聊消息始终被处理，不检查@
            try:
                self.handle_command(user_id, message, private=True)
                self.logger.debug(f"私聊消息处理完成 - 用户{user_id}")
            except Exception as e:
                self.logger.error(f"处理私聊消息时出错: {e}")
                # 即使出错也尝试通知用户
                try:
                    self.send_message(
                        user_id,
                        f"处理消息时出错: {str(e)}\n快让主人帮我检查一下ヽ(ﾟДﾟ)ﾉ",
                        private=True,
                    )
                except:
                    pass  # 避免嵌套异常
        # 处理群消息（需要被@才回应）
        elif data.get("post_type") == "message" and data.get("message_type") == "group":
            group_id = data.get("group_id")
            user_id = data.get("user_id")
            message = data.get("raw_message")
            message_content = data.get("message", "")

            self.logger.info(f"收到群消息 - 群{group_id} 用户{user_id}: {message}")

            # 检查是否被@
            at_self = False

            # 简化@检测逻辑
            if self.SELF_ID:
                # 方法1：检查raw_message中是否包含@机器人信息
                if (
                    f"@{self.SELF_ID}" in message
                    or f"[CQ:at,qq={self.SELF_ID}]" in message
                ):
                    at_self = True
                self.logger.debug(f"SELF_ID: {self.SELF_ID}, 被@状态: {at_self}")
            else:
                self.logger.warning("SELF_ID未初始化，无法检测@状态")

            # 如果没有被@，则不处理消息
            if not at_self:
                self.logger.debug("未被@，忽略消息")
                return

            # 如果被@，移除@部分，只保留命令内容
            # 移除CQ码格式的@
            message = message.replace(f"[CQ:at,qq={self.SELF_ID}]", "")
            # 移除纯文本格式的@
            message = message.replace(f"@{self.SELF_ID}", "")
            # 移除多余的空格
            message = message.strip()

            self.logger.info(f"收到群消息并被@ - 群{group_id} 用户{user_id}: {message}")
            self.handle_command(user_id, message, group_id=group_id, private=False)

    def handle_command(self, user_id, message, group_id=None, private=True):
        # 命令处理函数
        # 确保message不为None
        if message is None:
            self.logger.warning("收到空消息，忽略处理")
            self.send_message(
                user_id,
                "(｡•﹃•｡)叽里咕噜说什么呢，听不懂。\n发送漫画帮助看看我怎么用吧！",
                group_id,
                private,
            )
            return

        # 提取命令和参数
        command_parts = message.strip().split(" ", 1)
        cmd = command_parts[0].lower() if command_parts else ""
        args = command_parts[1] if len(command_parts) > 1 else ""

        self.logger.debug(
            f"处理命令 - 用户{user_id}: 命令='{cmd}', 参数='{args}', 私聊={private}"
        )

        # 帮助命令
        if cmd in ["漫画帮助", "帮助漫画"]:
            self.send_help(user_id, group_id, private)
        # 漫画下载命令
        elif cmd in ["漫画下载", "下载漫画", "下载"]:
            self.handle_manga_download(user_id, args, group_id, private)
        # 发送已下载漫画命令
        elif cmd in ["发送", "发送漫画", '漫画发送']:
            self.handle_manga_send(user_id, args, group_id, private)
        # 查询已下载漫画列表命令
        elif cmd in ["漫画列表", "列表漫画"]:
            self.query_downloaded_manga(user_id, group_id, private)
        # 查询指定漫画ID是否已下载
        elif cmd in ["查询漫画", "漫画查询"]:
            self.query_manga_existence(user_id, args, group_id, private)
        # 漫画版本查询命令
        elif cmd in ["漫画版本", "版本", "version"]:
            self.send_version_info(user_id, group_id, private)
        # 测试命令，显示当前SELF_ID状态
        elif cmd in ["测试id"]:
            # 测试命令，显示机器人当前的SELF_ID状态
            if self.SELF_ID:
                self.send_message(
                    user_id, f"✅ 机器人ID: {self.SELF_ID}", group_id, private
                )
            else:
                self.send_message(user_id, "❌ 机器人ID未获取", group_id, private)
        elif cmd in ["测试文件"]:
            # 测试文件发送功能
            self.send_message(user_id, "🔍 开始测试文件发送功能...", group_id, private)

            # 创建一个简单的测试文件
            test_file_path = os.path.join(os.getcwd(), "test_file.txt")
            try:
                with open(test_file_path, "w", encoding="utf-8") as f:
                    f.write("这是一个测试文件，用于验证机器人的文件发送功能。\n")
                    f.write(f"测试时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                    f.write(f"机器人ID: {self.SELF_ID or '未获取'}\n")

                self.send_message(
                    user_id, f"📄 已创建测试文件: {test_file_path}", group_id, private
                )
                self.send_message(user_id, "🚀 开始发送测试文件...", group_id, private)

                # 发送测试文件
                self.send_file(user_id, test_file_path, group_id, private)

                # 清理测试文件
                if os.path.exists(test_file_path):
                    os.remove(test_file_path)
                    self.logger.debug(f"已清理测试文件: {test_file_path}")

            except Exception as e:
                self.logger.error(f"创建测试文件失败: {e}")
                self.send_message(
                    user_id, f"❌ 创建测试文件失败: {str(e)}", group_id, private
                )
        # 欢迎消息
        elif any(
            keyword in message.lower() for keyword in ["你好", "hi", "hello", "在吗"]
        ):
            response = "你好！我是高性能JM机器人૮₍♡>𖥦<₎ა，可以帮你下载JMComic的漫画哦~~~\n输入 '漫画帮助' 就可以查看我的使用方法啦~"
            self.send_message(user_id, response, group_id, private)

    def query_downloaded_manga(self, user_id, group_id, private):
        # 查询已下载的漫画
        try:
            # 检查下载目录是否存在
            if not os.path.exists(self.config["MANGA_DOWNLOAD_PATH"]):
                self.send_message(
                    user_id,
                    "❌ 下载目录不存在！\n快让主人帮我检查一下ヽ(ﾟДﾟ)ﾉ",
                    group_id,
                    private,
                )
                return

            # 查找所有PDF格式的文件
            pdf_files = []
            for file_name in os.listdir(self.config["MANGA_DOWNLOAD_PATH"]):
                if file_name.endswith(".pdf"):
                    # 提取文件名（不含扩展名）
                    name_without_ext = os.path.splitext(file_name)[0]
                    pdf_files.append(name_without_ext)

            # 根据漫画ID进行排序
            pdf_files.sort()

            # 构建回复消息
            if not pdf_files:
                response = "📚↖(^ω^)↗ 目前没有已下载的漫画PDF文件！\n把你们珍藏的车牌号都统统交给我吧~~~"
            else:
                response = "📚 已下载的漫画列表：\n\n"
                # 每5个漫画为一组显示
                for i in range(0, len(pdf_files), 5):
                    group = pdf_files[i : i + 5]
                    response += "\n".join(
                        [f"{j+1}. {name}" for j, name in enumerate(group, start=i)]
                    )
                    response += "\n\n"

                response += f"总计：{len(pdf_files)} 个漫画PDF文件"

            self.send_message(user_id, response, group_id, private)
        except Exception as e:
            self.logger.error(f"查询已下载漫画出错: {e}")
            self.send_message(
                user_id, f"❌ 查询失败了(｡•﹃•｡)：{str(e)}", group_id, private
            )

    def query_manga_existence(self, user_id, manga_id, group_id, private):
        # 查询指定漫画ID是否已下载或正在下载
        try:
            if not manga_id:
                self.send_message(
                    user_id, "请输入漫画ID，例如：查询漫画 422866", group_id, private
                )
                return

            # 检查下载目录是否存在
            if not os.path.exists(self.config["MANGA_DOWNLOAD_PATH"]):
                self.send_message(
                    user_id,
                    "❌ 下载目录不存在！快让主人帮我检查一下ヽ(ﾟДﾟ)ﾉ",
                    group_id,
                    private,
                )
                return

            # 首先检查是否正在下载
            if manga_id in self.downloading_mangas:
                response = (
                    f"⏳ 漫画ID {manga_id} 正在下载中！请耐心等待下载完成后再尝试发送。"
                )
                self.send_message(user_id, response, group_id, private)
                return

            # 查找是否存在对应的PDF文件
            found = False
            found_files = []

            # 遍历所有PDF文件
            for file_name in os.listdir(self.config["MANGA_DOWNLOAD_PATH"]):
                if file_name.endswith(".pdf"):
                    # 检查文件名是否包含该漫画ID
                    name_without_ext = os.path.splitext(file_name)[0]
                    # 检查文件名是否以ID开头或包含ID-格式
                    if (
                        name_without_ext.startswith(manga_id + "-")
                        or name_without_ext == manga_id
                    ):
                        found = True
                        found_files.append(name_without_ext)

            # 构建回复消息
            if found:
                response = f"✅ദ്ദി˶>ω<)✧ 漫画ID {manga_id} 已经下载好啦！\n\n"
                response += "找到以下文件：\n"
                for i, file_name in enumerate(found_files, 1):
                    response += f"{i}. {file_name}\n"
            else:
                response = f"❌（｀Δ´）！ 漫画ID {manga_id} 还没有下载！"

            self.send_message(user_id, response, group_id, private)
        except Exception as e:
            self.logger.error(f"查询漫画存在性出错: {e}")
            self.send_message(
                user_id,
                f"❌ 查询失败：{str(e)}快让主人帮我检查一下ヽ(ﾟДﾟ)ﾉ",
                group_id,
                private,
            )

    def send_help(self, user_id, group_id, private):
        # 发送帮助信息
        help_text = f"📚 本小姐的帮助 📚(版本{self.VERSION})\n\n"

        # 群聊中添加@说明
        if not private:
            help_text += "⚠️ 在群聊中请先@我再发送命令！\n\n"

        help_text += "💡 可用命令：\n"
        help_text += "- 漫画下载 <漫画ID>：下载指定ID的漫画\n"
        help_text += "- 发送 <漫画ID>：发送指定ID的已下载漫画（只支持PDF格式）\n"
        help_text += "- 查询漫画 <漫画ID>：查询指定ID的漫画是否已下载\n"
        help_text += "- 漫画列表：查询已下载的所有漫画\n"
        help_text += "- 漫画帮助：显示此帮助信息\n"
        help_text += "- 漫画版本：显示机器人当前版本信息\n\n"
        help_text += "⚠️ 注意事项：\n"
        help_text += "- 命令与漫画ID之间记得加空格\n"
        help_text += "- 请确保输入正确的漫画ID\n"
        help_text += "- 下载过程可能需要一些时间，请耐心等待\n"
        help_text += "- 下载的漫画将保存在配置的目录中\n"
        help_text += "- 发送漫画前请确保该漫画已成功下载并转换为PDF格式\n"
        help_text += f"- 当前版本只支持发送PDF格式的漫画文件\n\n" + f"🔖 当前版本: {self.VERSION}"
        self.send_message(user_id, help_text, group_id, private)
        
    def send_version_info(self, user_id, group_id, private):
        # 发送版本信息
        version_text = f"🔖 JMComic QQ机器人\n" \
                      f"📌 当前版本: {self.VERSION}\n" \
                      f"💻 运行平台: {platform.system()} {platform.release()}\n" \
                      f"✨ 感谢使用JMComic QQ机器人！\n" \
                      f"📚 输入'漫画帮助'查看所有可用命令" 
        self.send_message(user_id, version_text, group_id, private)

    def handle_manga_download(self, user_id, manga_id, group_id, private):
        # 处理漫画下载
        if not manga_id:
            response = "请输入漫画ID，例如：漫画下载 422866"
            self.send_message(user_id, response, group_id, private)
            return

        # 在下载前先检查漫画是否已存在
        try:
            # 检查下载目录是否存在
            if not os.path.exists(self.config["MANGA_DOWNLOAD_PATH"]):
                # 目录不存在，需要创建并继续下载
                os.makedirs(self.config["MANGA_DOWNLOAD_PATH"], exist_ok=True)
                self.logger.info(f"创建下载目录: {self.config['MANGA_DOWNLOAD_PATH']}")
            else:
                # 查找是否存在对应的PDF文件
                found = False
                found_files = []

                # 遍历所有PDF文件
                for file_name in os.listdir(self.config["MANGA_DOWNLOAD_PATH"]):
                    if file_name.endswith(".pdf"):
                        # 检查文件名是否包含该漫画ID
                        name_without_ext = os.path.splitext(file_name)[0]
                        # 检查文件名是否以ID开头或包含ID-格式
                        if (
                            name_without_ext.startswith(manga_id + "-")
                            or name_without_ext == manga_id
                        ):
                            found = True
                            found_files.append(name_without_ext)

                # 如果已存在，则通知用户
                if found:
                    response = f"✅૮₍ ˶•‸•˶₎ა 漫画ID {manga_id} 已经下载过了！\n\n"
                    response += "找到以下文件：\n"
                    for i, file_name in enumerate(found_files, 1):
                        response += f"{i}. {file_name}\n"
                    response += "\n你可以使用 '发送 {manga_id}' 命令获取该漫画哦~"
                    self.send_message(user_id, response, group_id, private)
                    return
        except Exception as e:
            self.logger.error(f"检查漫画是否已下载时出错: {e}")
            # 检查出错时继续下载，避免因检查失败而影响用户体验

        # 发送开始下载的消息
        response = f"开始下载漫画ID：{manga_id}啦~，请稍候..."
        self.send_message(user_id, response, group_id, private)

        # 在新线程中下载漫画，避免阻塞
        threading.Thread(
            target=self.download_manga, args=(user_id, manga_id, group_id, private)
        ).start()

    def download_manga(self, user_id, manga_id, group_id, private):
        # 下载漫画函数
        try:
            # 标记该漫画正在下载中
            self.downloading_mangas[manga_id] = True

            # 使用jmcomic库下载漫画
            self.logger.info("开始下载漫画ID: %s", manga_id)
            # 从配置文件创建下载选项对象（使用相对路径）
            option = jmcomic.create_option_by_file("option.yml")
            # 确保使用环境变量中的下载路径
            option.dir_rule.base_dir = self.config["MANGA_DOWNLOAD_PATH"]

            # 设置目录命名规则，将漫画ID和名称组合在同一个文件夹名中
            # 使用f-string格式的规则，这样会创建 {base_dir}/{album_id}-{album_title}/{photo_title} 的目录结构
            # 在jmcomic v2.5.36+版本支持这种语法
            new_rule = "Bd / {Aid}-{Atitle}"
            from jmcomic.jm_option import DirRule

            # 创建新的DirRule对象并替换原有的
            option.dir_rule = DirRule(new_rule, base_dir=option.dir_rule.base_dir)

            jmcomic.download_album(manga_id, option=option)

            # 查找漫画文件夹 - 简化逻辑，只检查是否以漫画ID开头
            manga_dir = None
            # 直接在基础下载目录下查找
            download_path = str(self.config["MANGA_DOWNLOAD_PATH"])
            if os.path.exists(download_path):
                for dir_name in os.listdir(download_path):
                    dir_path = os.path.join(download_path, dir_name)
                    # 检查是否是目录且以漫画ID开头
                    if os.path.isdir(dir_path) and dir_name.startswith(f"{manga_id}-"):
                        manga_dir = dir_path
                        break

            # 如果在基础目录没找到，再尝试递归查找（兼容可能的其他情况）
            if not manga_dir:
                for root, dirs, files in os.walk(download_path):
                    for dir_name in dirs:
                        if dir_name.startswith(f"{manga_id}-"):
                            manga_dir = os.path.join(root, dir_name)
                            break
                    if manga_dir:
                        break

            if manga_dir and os.path.exists(manga_dir):
                # 从manga_dir路径中提取文件夹名称
                folder_name = os.path.basename(manga_dir)
                pdf_path = os.path.join(download_path, f"{folder_name}.pdf")
                import shutil
                import sys

                # 安装必要的依赖（如果没有的话）
                try:
                    from PIL import Image
                except ImportError:
                    self.logger.info("正在安装PIL库...")
                    import subprocess

                    subprocess.check_call(
                        [sys.executable, "-m", "pip", "install", "Pillow"]
                    )
                    from PIL import Image

                # 收集所有图片文件
                image_extensions = [".jpg", ".jpeg", ".png", ".gif", ".webp"]
                image_files = []

                for root, _, files in os.walk(manga_dir):
                    for file in files:
                        if any(file.lower().endswith(ext) for ext in image_extensions):
                            image_files.append(os.path.join(root, file))

                # 按文件名排序
                image_files.sort()

                if not image_files:
                    self.logger.warning(f"在漫画文件夹中未找到图片文件: {manga_dir}")
                    response = f"✅（｀Δ´）！ 漫画ID {manga_id} 下载完成！\n未找到图片文件，无法转换为PDF\n\n⚠️ 注意：当前版本只支持发送PDF格式的漫画文件"
                    self.send_message(user_id, response, group_id, private)
                    return

                self.logger.info(f"找到 {len(image_files)} 个图片文件，开始转换为PDF")

                # 转换为PDF
                try:
                    # 打开第一张图片作为PDF的第一页
                    first_image = Image.open(image_files[0])
                    # 确保图片为RGB模式
                    if first_image.mode == "RGBA":
                        first_image = first_image.convert("RGB")

                    # 准备其他图片
                    other_images = []
                    for img_path in image_files[1:]:
                        img = Image.open(img_path)
                        # 确保图片为RGB模式
                        if img.mode == "RGBA":
                            img = img.convert("RGB")
                        other_images.append(img)

                    # 保存为PDF
                    first_image.save(
                        pdf_path, save_all=True, append_images=other_images
                    )
                    self.logger.info(f"成功将漫画 {manga_id} 转换为PDF: {pdf_path}")

                    # 删除原漫画文件夹
                    self.logger.info(f"删除原漫画文件夹: {manga_dir}")
                    shutil.rmtree(manga_dir)

                    response = f"✅ദ്ദി˶>ω<)✧ 漫画ID {manga_id} 下载并转换为PDF完成！\n\n友情提示：输入'发送 {manga_id}'可以将PDF发送给您"
                except Exception as pdf_error:
                    self.logger.error(f"转换为PDF失败: {pdf_error}")
                    response = f"✅（｀Δ´）！ 漫画ID {manga_id} 下载完成，但转换为PDF失败: {str(pdf_error)}\n\n⚠️ 注意：当前版本只支持发送PDF格式的漫画文件，请确保漫画成功转换为PDF后再尝试发送"
            else:
                response = f"✅（｀Δ´）！ 漫画ID {manga_id} 下载完成！\n未找到漫画文件夹，无法转换为PDF\n\n⚠️ 注意：当前版本只支持发送PDF格式的漫画文件，请确保漫画成功转换为PDF后再尝试发送"

            self.send_message(user_id, response, group_id, private)
        except Exception as e:
            self.logger.error(f"下载漫画出错: {e}")
            error_msg = f"❌ 下载失败：{str(e)}\n\n快让主人帮我检查一下∑(O_O；)"
            self.send_message(user_id, error_msg, group_id, private)
        finally:
            # 下载完成或失败后，移除正在下载的标记
            if manga_id in self.downloading_mangas:
                del self.downloading_mangas[manga_id]

    def handle_manga_send(self, user_id, manga_id, group_id, private):
        # 处理漫画发送
        if not manga_id:
            response = "请输入漫画ID，例如：发送 422866"
            self.send_message(user_id, response, group_id, private)
            return

        # 发送开始发送的消息
        response = f"ฅ( ̳• ·̫ • ̳ฅ)正在查找并准备发送漫画ID：{manga_id}，请稍候..."
        self.send_message(user_id, response, group_id, private)

        # 在新线程中处理文件发送，避免阻塞
        threading.Thread(
            target=self.send_manga_files, args=(user_id, manga_id, group_id, private)
        ).start()

    def send_manga_files(self, user_id, manga_id, group_id, private):
        # 发送漫画文件函数 - 只发送PDF文件
        try:
            # 首先检查是否正在下载
            if manga_id in self.downloading_mangas:
                response = f"⏳ 漫画ID {manga_id} 正在下载中！请耐心等待下载完成后再尝试发送。\n\n你可以使用 '查询漫画 {manga_id}' 命令检查下载状态。"
                self.send_message(user_id, response, group_id, private)
                return

            # 检查是否有PDF文件，查找以漫画ID开头的PDF文件
            pdf_path = None
            download_path = str(self.config["MANGA_DOWNLOAD_PATH"])
            if os.path.exists(download_path):
                for file_name in os.listdir(download_path):
                    if file_name.startswith(f"{manga_id}-") and file_name.endswith(
                        ".pdf"
                    ):
                        pdf_path = os.path.join(download_path, file_name)
                        break

            if pdf_path and os.path.exists(pdf_path):
                # 发送PDF文件
                self.logger.info(f"找到PDF文件: {pdf_path}")
                self.send_message(
                    user_id, f"找到漫画PDF文件，开始发送...", group_id, private
                )
                self.send_file(user_id, pdf_path, group_id, private)
                self.send_message(
                    user_id, "✅ฅ( ̳• ·̫ • ̳ฅ) 漫画PDF发送完成！", group_id, private
                )
                return
            else:
                # 未找到PDF文件的情况
                error_msg = f"❌( っ`-´c)ﾏ 未找到漫画ID {manga_id} 的PDF文件，请先下载该漫画并确保已转换为PDF格式"
                self.send_message(user_id, error_msg, group_id, private)
                return

        except Exception as e:
            self.logger.error(f"发送漫画出错: {e}")
            error_msg = f"❌ 发送失败：{str(e)}\n快让主人帮我检查一下ヽ(ﾟДﾟ)ﾉ"
            self.send_message(user_id, error_msg, group_id, private)

    def run(self):
        # 运行机器人主函数
        self.logger.info("JMComic下载机器人启动中...")

        # 连接WebSocket
        self.connect_websocket()

        # 启动WebSocket重连管理线程
        threading.Thread(target=self.websocket_reconnect_manager, daemon=True).start()

        # 保持主程序运行
        while True:
            time.sleep(1)

    def handle_safe_close(self) -> None:
        """安全关闭机器人，确保所有资源都被正确释放"""
        signal.signal(signal.SIGINT, self._safe_sigint_handler)

    def _get_one_char(self) -> str|None:
        """跨平台获取单个字符输入"""
        # 检查是否为Linux系统
        if platform.system() != "Linux":
            # 在非Linux系统上，使用通用的输入方法
            return input()
        
        # Linux系统：使用termios和tty进行原始输入
        try:
            import termios
            import tty
        except ImportError:
            # 如果导入失败，回退到普通输入
            return input()
            
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        return ch

    def _confirm_close(self) -> bool:
        """询问用户是否确认关闭机器人"""
        print("是否确认关闭JMComic下载机器人？(y/n)")
        ch = self._get_one_char()
        return ch.lower() == "y"

    def _safe_sigint_handler(self, signum, frame) -> None:
        """安全处理SIGINT信号"""
        if self._confirm_close():
            try:
                # 关闭所有资源 - Fail Fast原则：失败就抛出异常
                self._close_resources()
                print("JMComic下载机器人已安全关闭")
            except Exception as e:
                # Fail Fast：关闭资源失败，抛出异常并退出程序
                self.logger.error(f"关闭资源时发生严重错误: {e}")
                print(f"关闭过程中发生严重错误，但仍将强制退出: {e}")
                # 不继续抛出异常，而是直接退出，因为用户已经确认要关闭
            finally:
                # 恢复默认信号处理并重新触发信号强制退出
                signal.signal(signal.SIGINT, signal.SIG_DFL)
                signal.raise_signal(signal.SIGINT)
                return
        else:
            # 用户取消操作程序继续运行
            print("关闭操作被取消，程序继续运行")
    
    def _close_resources(self) -> None:
        """关闭所有资源，确保程序安全退出"""
        try:
            self.logger.info("开始关闭JMComic下载机器人资源...")
            
            # 1. 关闭WebSocket连接
            if self.ws is not None:
                try:
                    if self.ws.sock and self.ws.sock.connected:
                        self.logger.info("关闭WebSocket连接...")
                        self.ws.close()
                        self.logger.info("WebSocket连接已成功关闭")
                    else:
                        self.logger.info("WebSocket连接已断开，无需关闭")
                except Exception as ws_error:
                    self.logger.error(f"关闭WebSocket连接时出错: {ws_error}")
                    raise ws_error  # Fail Fast：重新抛出异常，让调用者知道关闭过程失败
            
            # 2. 清理下载状态
            if self.downloading_mangas:
                self.logger.info(f"清理正在下载的漫画任务: {list(self.downloading_mangas.keys())}")
                self.downloading_mangas.clear()
            
            # 3. 重置实例状态
            self.ws = None
            self.SELF_ID = None
            
            # 4. 执行其他资源清理
            self.logger.info("执行其他资源清理...")
            
            print("JMComic下载机器人已安全关闭")
            self.logger.info("JMComic下载机器人资源关闭完成")
            
        except Exception as e:
            self.logger.error(f"关闭资源时发生严重错误: {e}")
            print(f"关闭资源时发生错误: {e}")
            raise  # Fail Fast：重新抛出异常，让调用者知道关闭过程失败
        


# 如果直接运行此文件
if __name__ == "__main__":
    # 创建机器人实例
    bot = MangaBot()
    # 设置安全关闭机制，确保程序可以正确响应Ctrl+C信号
    bot.handle_safe_close()
    # 运行机器人
    bot.run()
