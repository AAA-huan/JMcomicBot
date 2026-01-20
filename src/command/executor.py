import os
import platform
import time
import threading
from typing import Any, Callable, Dict, Optional

from src.command.parser import CommandParser
from src.logging.logger_config import logger
from src.utils.helpers import find_manga_pdf, list_downloaded_mangas


class CommandExecutor:
    """命令执行器，负责执行各种命令"""

    VERSION = "2.3.12"

    def __init__(
        self,
        message_sender: Callable[[str, str, Optional[str], bool], None],
        file_sender: Callable[[str, str, Optional[str], bool], None],
        download_manager: Any,
        config: Dict[str, Any],
        self_id_getter: Callable[[], Optional[str]],
    ) -> None:
        """
        初始化命令执行器

        Args:
            message_sender: 消息发送函数
            file_sender: 文件发送函数
            download_manager: 下载管理器实例
            config: 配置字典
            self_id_getter: 获取自身ID的函数
        """
        self.message_sender = message_sender
        self.file_sender = file_sender
        self.download_manager = download_manager
        self.config = config
        self.self_id_getter = self_id_getter
        self.command_parser = CommandParser()
        self.logger = logger

    def execute_command(self, user_id: str, message: str, group_id: Optional[str] = None, private: bool = True) -> None:
        """
        执行用户命令

        Args:
            user_id: 用户ID
            message: 原始消息内容
            group_id: 群组ID（群聊时提供）
            private: 是否为私聊

        Raises:
            ValueError: 当消息为空或命令格式错误时
        """
        command_id = hash(str(time.time()) + message[:50])
        self.logger.info(f"[命令ID:{command_id}] 开始处理命令 - 用户{user_id}, 私聊={private}")

        if message is None:
            error_msg = "(｡•﹃•｡)叽里咕噜说什么呢，听不懂。\n发送漫画帮助看看我怎么用吧！"
            self.message_sender(user_id, error_msg, group_id, private)
            raise ValueError("收到空消息")

        try:
            cmd, args = self.command_parser.parse(message)
        except ValueError as e:
            self.logger.warning(f"[命令ID:{command_id}] 命令解析失败: {e}")
            error_msg = self.command_parser.get_error_message("unknown")
            self.message_sender(user_id, error_msg, group_id, private)
            raise

        self.logger.info(
            f"[命令ID:{command_id}] 处理命令 - 用户{user_id}: 标准化命令='{cmd}', 参数='{args}', 私聊={private}"
        )

        if not self.command_parser.validate_params(cmd, args):
            error_msg = self.command_parser.get_error_message(cmd)
            self.logger.warning(f"[命令ID:{command_id}] 参数验证失败: {error_msg}")
            self.message_sender(user_id, error_msg, group_id, private)
            raise ValueError(f"参数验证失败: {error_msg}")

        self._dispatch_command(user_id, cmd, args, group_id, private)

    def _dispatch_command(
        self,
        user_id: str,
        cmd: str,
        args: str,
        group_id: Optional[str],
        private: bool,
    ) -> None:
        """
        分发命令到对应的处理函数

        Args:
            user_id: 用户ID
            cmd: 标准化的命令名
            args: 命令参数
            group_id: 群组ID
            private: 是否为私聊
        """
        command_handlers = {
            "help": self._send_help,
            "download": self._handle_manga_download,
            "send": self._handle_manga_send,
            "list": self._query_downloaded_manga,
            "query": self._query_manga_existence,
            "version": self._send_version_info,
            "progress": self._show_download_progress,
            "test_id": self._test_id,
            "test_file": self._test_file,
            "welcome": self._send_welcome,
        }

        handler = command_handlers.get(cmd)
        if handler:
            handler(user_id, args, group_id, private)
        else:
            self.logger.warning(f"未知命令: {cmd}")

    def _send_help(self, user_id: str, args: str, group_id: Optional[str], private: bool) -> None:
        """发送帮助信息"""
        help_text = f"📚 本小姐的帮助 📚(版本{self.VERSION})\n\n"

        if not private:
            help_text += "⚠️ 在群聊中请先@我再发送命令！\n\n"

        help_text += "💡 可用命令：\n"
        help_text += "- 漫画帮助：显示此帮助信息\n"
        help_text += "- 漫画下载 <漫画ID>：下载指定ID的漫画\n"
        help_text += "- 发送漫画 <漫画ID>：发送指定ID的已下载漫画（只支持PDF格式）\n"
        help_text += "- 查询漫画 <漫画ID>：查询指定ID的漫画是否已下载\n"
        help_text += "- 漫画列表：查询已下载的所有漫画\n"
        help_text += "- 下载进度：查看当前漫画下载队列的状况\n"
        help_text += "- 漫画版本：显示机器人当前版本信息\n\n"
        help_text += "⚠️ 注意事项：\n"
        help_text += "- 命令与漫画ID之间记得加空格\n"
        help_text += "- 请确保输入正确的漫画ID\n"
        help_text += "- 下载过程可能需要一些时间，请耐心等待\n"
        help_text += "- 下载的漫画将保存在配置的目录中\n"
        help_text += "- 发送漫画前请确保该漫画已成功下载并转换为PDF格式\n"
        help_text += f"- 当前版本只支持发送PDF格式的漫画文件\n\n"
        help_text += f"🔖 当前版本: {self.VERSION}"

        self.message_sender(user_id, help_text, group_id, private)

    def _handle_manga_download(self, user_id: str, manga_id: str, group_id: Optional[str], private: bool) -> None:
        """处理漫画下载请求"""
        self.logger.info(f"处理漫画下载请求 - 用户{user_id}, 漫画ID: {manga_id}")

        pdf_path = find_manga_pdf(str(self.config["MANGA_DOWNLOAD_PATH"]), manga_id)

        if pdf_path:
            response = f"✅૮₍ ˶•‸•˶₎ა 漫画ID {manga_id} 已经下载过了！\n\n"
            response += f"找到文件：{os.path.basename(pdf_path)}\n\n"
            response += f"你可以使用 '发送 {manga_id}' 命令获取该漫画哦~"
            self.message_sender(user_id, response, group_id, private)
            return

        response = f"开始下载漫画ID：{manga_id}啦~，请稍候..."
        self.message_sender(user_id, response, group_id, private)
        self.download_manager.download_manga(user_id, manga_id, group_id, private)

    def _handle_manga_send(self, user_id: str, manga_id: str, group_id: Optional[str], private: bool) -> None:
        """处理漫画发送请求"""
        self.logger.info(f"处理漫画发送请求 - 用户{user_id}, 漫画ID: {manga_id}")

        response = f"ฅ( ̳• ·̫ • ̳ฅ)正在查找并准备发送漫画ID：{manga_id}，请稍候..."
        self.message_sender(user_id, response, group_id, private)

        threading.Thread(target=self._send_manga_files, args=(user_id, manga_id, group_id, private)).start()

    def _send_manga_files(self, user_id: str, manga_id: str, group_id: Optional[str], private: bool) -> None:
        """发送漫画文件"""
        try:
            if manga_id in self.download_manager.downloading_mangas:
                response = f"⏳ 漫画ID {manga_id} 正在下载中！请耐心等待下载完成后再尝试发送。\n\n你可以使用 '查询漫画 {manga_id}' 命令检查下载状态。"
                self.message_sender(user_id, response, group_id, private)
                return

            pdf_path = find_manga_pdf(str(self.config["MANGA_DOWNLOAD_PATH"]), manga_id)

            if pdf_path:
                self.logger.info(f"找到PDF文件: {pdf_path}")
                self.message_sender(user_id, f"找到漫画PDF文件，开始发送...", group_id, private)
                self.file_sender(user_id, pdf_path, group_id, private)
                self.message_sender(user_id, "✅ฅ( ̳• ·̫ • ̳ฅ) 漫画PDF发送完成！", group_id, private)
                return

            error_msg = f"❌( っ`-´c)ﾏ 未找到漫画ID {manga_id} 的PDF文件，请先下载该漫画并确保已转换为PDF格式"
            self.message_sender(user_id, error_msg, group_id, private)

        except Exception as e:
            self.logger.error(f"发送漫画出错: {e}")
            error_msg = f"❌ 发送失败：{str(e)}\n快让主人帮我检查一下ヽ(ﾟДﾟ)ﾉ"
            self.message_sender(user_id, error_msg, group_id, private)

    def _query_downloaded_manga(self, user_id: str, args: str, group_id: Optional[str], private: bool) -> None:
        """查询已下载的漫画"""
        self.logger.info(f"开始处理漫画列表查询 - 用户{user_id}")

        try:
            pdf_files = list_downloaded_mangas(str(self.config["MANGA_DOWNLOAD_PATH"]))

            if not pdf_files:
                response = "📚↖(^ω^)↗ 目前没有已下载的漫画PDF文件！\n把你们珍藏的车牌号都统统交给我吧~~~"
            else:
                response = "📚 已下载的漫画列表：\n\n"
                for i in range(0, len(pdf_files), 5):
                    group = pdf_files[i : i + 5]
                    response += "\n".join([f"{j+1}. {name}" for j, name in enumerate(group, start=i)])
                    response += "\n\n"

                response += f"总计：{len(pdf_files)} 个漫画PDF文件"

            self.message_sender(user_id, response, group_id, private)
        except FileNotFoundError as e:
            self.logger.error(f"查询已下载漫画出错: {e}")
            error_msg = "❌ 下载目录不存在！\n快让主人帮我检查一下ヽ(ﾟДﾟ)ﾉ"
            self.message_sender(user_id, error_msg, group_id, private)

    def _query_manga_existence(self, user_id: str, manga_id: str, group_id: Optional[str], private: bool) -> None:
        """查询指定漫画ID是否已下载"""
        self.logger.info(f"查询漫画存在性 - 用户{user_id}, 漫画ID: {manga_id}")

        try:
            if manga_id in self.download_manager.downloading_mangas:
                response = f"⏳ 漫画ID {manga_id} 正在下载中！请耐心等待下载完成后再尝试发送。"
                self.message_sender(user_id, response, group_id, private)
                return

            pdf_path = find_manga_pdf(str(self.config["MANGA_DOWNLOAD_PATH"]), manga_id)

            if pdf_path:
                response = f"✅ദ്ദി˶>ω<)✧ 漫画ID {manga_id} 已经下载好啦！\n\n"
                response += f"找到文件：{os.path.basename(pdf_path)}"
            else:
                response = f"❌（｀Δ´）！ 漫画ID {manga_id} 还没有下载！"

            self.message_sender(user_id, response, group_id, private)
        except FileNotFoundError as e:
            self.logger.error(f"查询漫画存在性出错: {e}")
            error_msg = "❌ 下载目录不存在！快让主人帮我检查一下ヽ(ﾟДﾟ)ﾉ"
            self.message_sender(user_id, error_msg, group_id, private)

    def _send_version_info(self, user_id: str, args: str, group_id: Optional[str], private: bool) -> None:
        """发送版本信息"""
        version_text = (
            f"🔖 JMComic QQ机器人\n"
            f"📌 当前版本: {self.VERSION}\n"
            f"💻 运行平台: {platform.system()} {platform.release()}\n"
            f"✨ 感谢使用JMComic QQ机器人！\n"
            f"📚 输入'漫画帮助'查看所有可用命令"
        )
        self.message_sender(user_id, version_text, group_id, private)

    def _show_download_progress(self, user_id: str, args: str, group_id: Optional[str], private: bool) -> None:
        """显示当前下载队列的进度信息"""
        self.logger.info(f"显示下载进度请求 - 用户{user_id}")

        downloading_mangas = list(self.download_manager.downloading_mangas.keys())
        queued_mangas = list(self.download_manager.queued_tasks.keys())

        response = "📊 当前下载队列状态 📊\n\n"

        if downloading_mangas:
            response += f"⏳ 正在下载: {len(downloading_mangas)} 个漫画\n"
            for manga_id in downloading_mangas:
                response += f"  • {manga_id}\n"
        else:
            response += "✅ 当前没有正在下载的漫画\n"

        response += "\n"

        if queued_mangas:
            response += f"📋 队列等待: {len(queued_mangas)} 个漫画\n"
            for manga_id in queued_mangas:
                response += f"  • {manga_id}\n"
        else:
            response += "✅ 下载队列为空\n"

        response += "\n"
        response += f"📝 总任务数: {len(downloading_mangas) + len(queued_mangas)}\n"
        response += "\n💡 提示: 下载任务将按顺序执行，请耐心等待"

        self.message_sender(user_id, response, group_id, private)

    def _test_id(self, user_id: str, args: str, group_id: Optional[str], private: bool) -> None:
        """测试命令，显示当前SELF_ID状态"""
        self_id = self.self_id_getter()
        if self_id:
            self.message_sender(user_id, f"✅ 机器人ID: {self_id}", group_id, private)
        else:
            self.message_sender(user_id, "❌ 机器人ID未获取", group_id, private)

    def _test_file(self, user_id: str, args: str, group_id: Optional[str], private: bool) -> None:
        """测试文件发送功能"""
        self.message_sender(user_id, "🔍 开始测试文件发送功能...", group_id, private)

        test_file_path = os.path.join(os.getcwd(), "test_file.txt")
        try:
            with open(test_file_path, "w", encoding="utf-8") as f:
                f.write("这是一个测试文件，用于验证机器人的文件发送功能。\n")
                f.write(f"测试时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"机器人ID: {self.self_id_getter() or '未获取'}\n")

            self.message_sender(user_id, f"📄 已创建测试文件: {test_file_path}", group_id, private)
            self.message_sender(user_id, "🚀 开始发送测试文件...", group_id, private)

            self.file_sender(user_id, test_file_path, group_id, private)

            if os.path.exists(test_file_path):
                os.remove(test_file_path)
                self.logger.debug(f"已清理测试文件: {test_file_path}")

        except Exception as e:
            self.logger.error(f"创建测试文件失败: {e}")
            self.message_sender(user_id, f"❌ 创建测试文件失败: {str(e)}", group_id, private)

    def _send_welcome(self, user_id: str, args: str, group_id: Optional[str], private: bool) -> None:
        """发送欢迎消息"""
        response = "你好！我是高性能JM机器人૮₍♡>𖥦<₎ა，可以帮你下载JMComic的漫画哦~~~\n输入 '漫画帮助' 就可以查看我的使用方法啦~"
        self.message_sender(user_id, response, group_id, private)
