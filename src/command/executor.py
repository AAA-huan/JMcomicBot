import os
import platform
import time
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.command.parser import CommandParser
from src.logging.logger_config import logger
from src.utils.batch import (
    format_batch_response,
    parse_batch_params,
    validate_manga_ids,
)
from src.utils.helpers import (
    find_manga_pdf,
    get_file_size_mb,
    list_downloaded_mangas_with_size,
)


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
        permission_manager: Any,
    ) -> None:
        """
        初始化命令执行器

        Args:
            message_sender: 消息发送函数
            file_sender: 文件发送函数
            download_manager: 下载管理器实例
            config: 配置字典
            self_id_getter: 获取自身ID的函数
            permission_manager: 权限管理器实例
        """
        self.message_sender = message_sender
        self.file_sender = file_sender
        self.download_manager = download_manager
        self.config = config
        self.self_id_getter = self_id_getter
        self.permission_manager = permission_manager
        self.command_parser = CommandParser()
        self.logger = logger
        self.SELF_ID: Optional[str] = None

    def execute_command(
        self,
        user_id: str,
        message: str,
        group_id: Optional[str] = None,
        private: bool = True,
    ) -> None:
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
        self.logger.info(
            f"[命令ID:{command_id}] 开始处理命令 - 用户{user_id}, 私聊={private}"
        )

        if message is None:
            error_msg = (
                "(｡•﹃•｡)叽里咕噜说什么呢，听不懂。\n发送漫画帮助看看我怎么用吧！"
            )
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

        try:
            self.permission_manager.check_user_permission(user_id, group_id, private)
        except ValueError as e:
            self.logger.warning(f"[命令ID:{command_id}] 权限检查失败: {e}")
            self.message_sender(user_id, str(e), group_id, private)
            raise

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
            "delete": self._handle_manga_delete,
        }

        handler = command_handlers.get(cmd)
        if handler:
            handler(user_id, args, group_id, private)
        else:
            self.logger.warning(f"未知命令: {cmd}")

    def _send_help(
        self, user_id: str, args: str, group_id: Optional[str], private: bool
    ) -> None:
        """发送帮助信息"""
        help_text = f"📚 帮助 📚(版本{self.VERSION})\n\n"

        if not private:
            help_text += "⚠️ 在群聊中请先@我再发送命令！\n\n"

        help_text += "💡 可用命令：\n"
        help_text += "- 漫画帮助：显示此帮助信息\n"
        help_text += (
            "- 漫画下载 <漫画ID>：下载指定ID的漫画\n"
            "  支持批量下载：漫画下载 123,456,789\n"
        )
        help_text += (
            "- 发送漫画 <漫画ID>：发送指定ID的已下载漫画（只支持PDF格式）\n"
            "  支持批量发送：发送 123,456,789\n"
            "  支持发送全部：发送 --all\n"
        )
        help_text += (
            "- 查询漫画 <漫画ID>：查询指定ID的漫画是否已下载\n"
            "  支持批量查询：查询漫画 123,456,789\n"
            "  支持查询全部：查询漫画 --all\n"
        )
        help_text += "- 漫画列表：查询已下载的所有漫画\n"
        help_text += "- 下载进度：查看当前漫画下载队列的状况\n"
        help_text += "- 漫画版本：显示机器人当前版本信息\n"
        help_text += (
            "- 删除漫画 <漫画ID>：删除指定ID的已下载漫画（仅限特定用户）\n"
            "  支持批量删除：删除 123,456,789\n"
            "  支持删除全部：删除 --all\n"
        )
        help_text += "\n⚠️ 注意事项：\n"
        help_text += "- 命令与漫画ID之间记得加空格\n"
        help_text += "- 批量操作使用逗号分隔多个ID\n"
        help_text += "- 请确保输入正确的漫画ID\n"
        help_text += "- 下载过程可能需要一些时间，请耐心等待\n"
        help_text += "- 下载的漫画将保存在配置的目录中\n"
        help_text += "- 发送漫画前请确保该漫画已成功下载并转换为PDF格式\n"
        help_text += "- 当前版本只支持发送PDF格式的漫画文件\n"
        help_text += "- 删除漫画功能仅限特定用户使用\n\n"
        help_text += f"🔖 当前版本: {self.VERSION}"

        self.message_sender(user_id, help_text, group_id, private)

    def _handle_manga_download(
        self, user_id: str, params: str, group_id: Optional[str], private: bool
    ) -> None:
        """处理漫画下载请求，支持批量下载"""
        try:
            manga_ids, use_all = parse_batch_params(params)

            if use_all:
                self.message_sender(
                    user_id,
                    "❌ 下载命令不支持 --all 参数\n请提供具体的漫画ID",
                    group_id,
                    private,
                )
                return

            if not manga_ids:
                self.message_sender(
                    user_id,
                    "❌ 参数错误！请提供有效的漫画ID",
                    group_id,
                    private,
                )
                return

            manga_ids = validate_manga_ids(manga_ids)

            if len(manga_ids) == 1:
                self._download_single_manga(user_id, manga_ids[0], group_id, private)
            else:
                self._download_batch_mangas(user_id, manga_ids, group_id, private)
        except ValueError as e:
            self.logger.warning(f"批量下载参数解析失败: {e}")
            self.message_sender(user_id, str(e), group_id, private)

    def _download_single_manga(
        self, user_id: str, manga_id: str, group_id: Optional[str], private: bool
    ) -> None:
        """下载单个漫画"""
        self.logger.info(f"处理漫画下载请求 - 用户{user_id}, 漫画ID: {manga_id}")

        pdf_path = find_manga_pdf(str(self.config["MANGA_DOWNLOAD_PATH"]), manga_id)

        if pdf_path:
            response = (
                f"✅૮₍ ˶•‸•˶₎ა 漫画ID {manga_id} 已经下载过了！\n\n"
                f"找到文件：{os.path.basename(pdf_path)}\n\n"
                f"你可以使用 '发送 {manga_id}' 命令获取该漫画哦~"
            )
            self.message_sender(user_id, response, group_id, private)
            return

        response = f"开始下载漫画ID：{manga_id}啦~，请稍候..."
        self.message_sender(user_id, response, group_id, private)
        self.download_manager.download_manga(user_id, manga_id, group_id, private)

    def _download_batch_mangas(
        self, user_id: str, manga_ids: List[str], group_id: Optional[str], private: bool
    ) -> None:
        """批量下载漫画"""
        self.logger.info(
            f"处理批量漫画下载请求 - 用户{user_id}, 漫画ID数量: {len(manga_ids)}"
        )

        response = f"开始批量下载 {len(manga_ids)} 个漫画，请稍候...\n\n"
        response += "已添加到下载队列：\n"
        for i, manga_id in enumerate(manga_ids[:10], 1):
            response += f"  {i}. {manga_id}\n"
        if len(manga_ids) > 10:
            response += f"  ... 还有 {len(manga_ids) - 10} 个\n"

        self.message_sender(user_id, response, group_id, private)

        for manga_id in manga_ids:
            pdf_path = find_manga_pdf(str(self.config["MANGA_DOWNLOAD_PATH"]), manga_id)
            if not pdf_path:
                self.download_manager.download_manga(
                    user_id, manga_id, group_id, private
                )

    def _handle_manga_send(
        self, user_id: str, params: str, group_id: Optional[str], private: bool
    ) -> None:
        """处理漫画发送请求，支持批量发送"""
        try:
            manga_ids, use_all = parse_batch_params(params)

            if use_all:
                manga_ids = self._get_all_downloaded_manga_ids()
                if not manga_ids:
                    self.message_sender(
                        user_id,
                        "❌ 当前没有已下载的漫画",
                        group_id,
                        private,
                    )
                    return

            if not manga_ids:
                self.message_sender(
                    user_id,
                    "❌ 参数错误！请提供有效的漫画ID",
                    group_id,
                    private,
                )
                return

            manga_ids = validate_manga_ids(manga_ids)

            if len(manga_ids) == 1:
                self._send_single_manga(user_id, manga_ids[0], group_id, private)
            else:
                self._send_batch_mangas(user_id, manga_ids, group_id, private)
        except ValueError as e:
            self.logger.warning(f"批量发送参数解析失败: {e}")
            self.message_sender(user_id, str(e), group_id, private)

    def _get_all_downloaded_manga_ids(self) -> List[str]:
        """获取所有已下载的漫画ID列表"""
        try:
            pdf_files = list_downloaded_mangas_with_size(
                str(self.config["MANGA_DOWNLOAD_PATH"])
            )
            return [name.split("-")[0] for name, _ in pdf_files]
        except FileNotFoundError:
            return []

    def _send_single_manga(
        self, user_id: str, manga_id: str, group_id: Optional[str], private: bool
    ) -> None:
        """发送单个漫画"""
        self.logger.info(f"处理漫画发送请求 - 用户{user_id}, 漫画ID: {manga_id}")

        response = f"ฅ( ̳• ·̫ • ̳ฅ)正在查找并准备发送漫画ID：{manga_id}，请稍候..."
        self.message_sender(user_id, response, group_id, private)

        threading.Thread(
            target=self._send_manga_files, args=(user_id, manga_id, group_id, private)
        ).start()

    def _send_batch_mangas(
        self, user_id: str, manga_ids: List[str], group_id: Optional[str], private: bool
    ) -> None:
        """批量发送漫画"""
        self.logger.info(
            f"处理批量漫画发送请求 - 用户{user_id}, 漫画ID数量: {len(manga_ids)}"
        )

        response = f"开始批量发送 {len(manga_ids)} 个漫画，请稍候...\n\n"
        response += "发送队列：\n"
        for i, manga_id in enumerate(manga_ids[:10], 1):
            response += f"  {i}. {manga_id}\n"
        if len(manga_ids) > 10:
            response += f"  ... 还有 {len(manga_ids) - 10} 个\n"

        self.message_sender(user_id, response, group_id, private)

        results: List[Tuple[str, bool, str]] = []

        for manga_id in manga_ids:
            try:
                if manga_id in self.download_manager.downloading_mangas:
                    results.append(
                        (
                            manga_id,
                            False,
                            "正在下载中，请等待下载完成",
                        )
                    )
                    continue

                pdf_path = find_manga_pdf(
                    str(self.config["MANGA_DOWNLOAD_PATH"]), manga_id
                )

                if pdf_path:
                    self.logger.info(f"找到PDF文件: {pdf_path}")
                    self.file_sender(user_id, pdf_path, group_id, private)
                    results.append((manga_id, True, "发送成功"))
                else:
                    results.append((manga_id, False, "未找到PDF文件"))
            except Exception as e:
                self.logger.error(f"发送漫画 {manga_id} 出错: {e}")
                results.append((manga_id, False, str(e)))

        batch_response = format_batch_response("发送", results)
        self.message_sender(user_id, batch_response, group_id, private)

    def _send_manga_files(
        self, user_id: str, manga_id: str, group_id: Optional[str], private: bool
    ) -> None:
        """发送漫画文件"""
        try:
            if manga_id in self.download_manager.downloading_mangas:
                response = (
                    f"⏳ 漫画ID {manga_id} 正在下载中！"
                    f"请耐心等待下载完成后再尝试发送。\n\n"
                    f"你可以使用 '查询漫画 {manga_id}' 命令检查下载状态。"
                )
                self.message_sender(user_id, response, group_id, private)
                return

            pdf_path = find_manga_pdf(str(self.config["MANGA_DOWNLOAD_PATH"]), manga_id)

            if pdf_path:
                self.logger.info(f"找到PDF文件: {pdf_path}")
                self.message_sender(
                    user_id, "找到漫画PDF文件，开始发送...", group_id, private
                )
                self.file_sender(user_id, pdf_path, group_id, private)
                self.message_sender(
                    user_id, "✅ฅ( ̳• ·̫ • ̳ฅ) 漫画PDF发送完成！", group_id, private
                )
                return

            error_msg = (
                f"❌( っ`-´c)ﾏ 未找到漫画ID {manga_id} 的PDF文件，"
                f"请先下载该漫画并确保已转换为PDF格式"
            )
            self.message_sender(user_id, error_msg, group_id, private)

        except Exception as e:
            self.logger.error(f"发送漫画出错: {e}")
            error_msg = f"❌ 发送失败：{str(e)}\n快让主人帮我检查一下ヽ(ﾟДﾟ)ﾉ"
            self.message_sender(user_id, error_msg, group_id, private)

    def _query_downloaded_manga(
        self, user_id: str, args: str, group_id: Optional[str], private: bool
    ) -> None:
        """查询已下载的漫画"""
        self.logger.info(f"开始处理漫画列表查询 - 用户{user_id}")

        try:
            pdf_files = list_downloaded_mangas_with_size(
                str(self.config["MANGA_DOWNLOAD_PATH"])
            )

            if not pdf_files:
                response = (
                    "📚↖(^ω^)↗ 目前没有已下载的漫画PDF文件！\n"
                    "把你们珍藏的车牌号都统统交给我吧~~~"
                )
            else:
                response = "📚 已下载的漫画列表：\n\n"
                for i in range(0, len(pdf_files), 5):
                    group = pdf_files[i : i + 5]
                    response += "\n".join(
                        [
                            f"{j+1}. {name} ({size} MB)"
                            for j, (name, size) in enumerate(group, start=i)
                        ]
                    )
                    response += "\n\n"

                total_size = sum(size for _, size in pdf_files)
                response += (
                    f"总计：{len(pdf_files)} 个漫画PDF文件\n" f"总大小：{total_size} MB"
                )

            self.message_sender(user_id, response, group_id, private)
        except FileNotFoundError as e:
            self.logger.error(f"查询已下载漫画出错: {e}")
            error_msg = "❌ 下载目录不存在！\n快让主人帮我检查一下ヽ(ﾟДﾟ)ﾉ"
            self.message_sender(user_id, error_msg, group_id, private)

    def _query_manga_existence(
        self, user_id: str, params: str, group_id: Optional[str], private: bool
    ) -> None:
        """查询指定漫画ID是否已下载，支持批量查询"""
        try:
            manga_ids, use_all = parse_batch_params(params)

            if use_all:
                manga_ids = self._get_all_downloaded_manga_ids()
                if not manga_ids:
                    self.message_sender(
                        user_id,
                        "❌ 当前没有已下载的漫画",
                        group_id,
                        private,
                    )
                    return

            if not manga_ids:
                self.message_sender(
                    user_id,
                    "❌ 参数错误！请提供有效的漫画ID",
                    group_id,
                    private,
                )
                return

            manga_ids = validate_manga_ids(manga_ids)

            if len(manga_ids) == 1:
                self._query_single_manga(user_id, manga_ids[0], group_id, private)
            else:
                self._query_batch_mangas(user_id, manga_ids, group_id, private)
        except ValueError as e:
            self.logger.warning(f"批量查询参数解析失败: {e}")
            self.message_sender(user_id, str(e), group_id, private)

    def _query_single_manga(
        self, user_id: str, manga_id: str, group_id: Optional[str], private: bool
    ) -> None:
        """查询单个漫画"""
        self.logger.info(f"查询漫画存在性 - 用户{user_id}, 漫画ID: {manga_id}")

        try:
            if manga_id in self.download_manager.downloading_mangas:
                response = (
                    f"⏳ 漫画ID {manga_id} 正在下载中！"
                    f"请耐心等待下载完成后再尝试发送。"
                )
                self.message_sender(user_id, response, group_id, private)
                return

            pdf_path = find_manga_pdf(str(self.config["MANGA_DOWNLOAD_PATH"]), manga_id)

            if pdf_path:
                file_size_mb = get_file_size_mb(pdf_path)
                response = (
                    f"✅ദ്ദി˶>ω<)✧ 漫画ID {manga_id} 已经下载好啦！\n\n"
                    f"找到文件：{os.path.basename(pdf_path)}\n"
                    f"文件大小：{file_size_mb} MB"
                )
            else:
                response = f"❌（｀Δ´）！ 漫画ID {manga_id} 还没有下载！"

            self.message_sender(user_id, response, group_id, private)
        except FileNotFoundError as e:
            self.logger.error(f"查询漫画存在性出错: {e}")
            error_msg = "❌ 下载目录不存在！快让主人帮我检查一下ヽ(ﾟДﾟ)ﾉ"
            self.message_sender(user_id, error_msg, group_id, private)

    def _query_batch_mangas(
        self, user_id: str, manga_ids: List[str], group_id: Optional[str], private: bool
    ) -> None:
        """批量查询漫画"""
        self.logger.info(
            f"处理批量漫画查询请求 - 用户{user_id}, 漫画ID数量: {len(manga_ids)}"
        )

        results: List[Tuple[str, bool, str]] = []

        for manga_id in manga_ids:
            try:
                if manga_id in self.download_manager.downloading_mangas:
                    results.append((manga_id, False, "正在下载中"))
                    continue

                pdf_path = find_manga_pdf(
                    str(self.config["MANGA_DOWNLOAD_PATH"]), manga_id
                )

                if pdf_path:
                    file_size_mb = get_file_size_mb(pdf_path)
                    results.append((manga_id, True, f"已下载 ({file_size_mb} MB)"))
                else:
                    results.append((manga_id, False, "未下载"))
            except FileNotFoundError as e:
                self.logger.error(f"查询漫画 {manga_id} 出错: {e}")
                results.append((manga_id, False, "查询失败"))
            except Exception as e:
                self.logger.error(f"查询漫画 {manga_id} 出错: {e}")
                results.append((manga_id, False, str(e)))

        batch_response = format_batch_response("查询", results)
        self.message_sender(user_id, batch_response, group_id, private)

    def _send_version_info(
        self, user_id: str, args: str, group_id: Optional[str], private: bool
    ) -> None:
        """发送版本信息"""
        version_text = (
            f"🔖 JMComic QQ机器人\n"
            f"📌 当前版本: {self.VERSION}\n"
            f"💻 运行平台: {platform.system()} {platform.release()}\n"
            f"✨ 感谢使用JMComic QQ机器人！\n"
            f"📚 输入'漫画帮助'查看所有可用命令"
        )
        self.message_sender(user_id, version_text, group_id, private)

    def _show_download_progress(
        self, user_id: str, args: str, group_id: Optional[str], private: bool
    ) -> None:
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

    def _test_id(
        self, user_id: str, args: str, group_id: Optional[str], private: bool
    ) -> None:
        """测试命令，显示当前SELF_ID状态"""
        self_id = self.self_id_getter()
        if self_id:
            self.message_sender(user_id, f"✅ 机器人ID: {self_id}", group_id, private)
        else:
            self.message_sender(user_id, "❌ 机器人ID未获取", group_id, private)

    def _test_file(
        self, user_id: str, args: str, group_id: Optional[str], private: bool
    ) -> None:
        """测试文件发送功能"""
        self.message_sender(user_id, "🔍 开始测试文件发送功能...", group_id, private)

        test_file_path = os.path.join(os.getcwd(), "test_file.txt")
        try:
            with open(test_file_path, "w", encoding="utf-8") as f:
                f.write("这是一个测试文件，用于验证机器人的文件发送功能。\n")
                f.write(f"测试时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"机器人ID: {self.self_id_getter() or '未获取'}\n")

            self.message_sender(
                user_id, f"📄 已创建测试文件: {test_file_path}", group_id, private
            )
            self.message_sender(user_id, "🚀 开始发送测试文件...", group_id, private)

            self.file_sender(user_id, test_file_path, group_id, private)

            if os.path.exists(test_file_path):
                os.remove(test_file_path)
                self.logger.debug(f"已清理测试文件: {test_file_path}")

        except Exception as e:
            self.logger.error(f"创建测试文件失败: {e}")
            self.message_sender(
                user_id, f"❌ 创建测试文件失败: {str(e)}", group_id, private
            )

    def _send_welcome(
        self, user_id: str, args: str, group_id: Optional[str], private: bool
    ) -> None:
        """发送欢迎消息"""
        response = (
            "你好！我是高性能JM机器人૮₍♡>𖥦<₎ა，"
            "可以帮你下载JMComic的漫画哦~~~\n"
            "输入 '漫画帮助' 就可以查看我的使用方法啦~"
        )
        self.message_sender(user_id, response, group_id, private)

    def _handle_manga_delete(
        self, user_id: str, params: str, group_id: Optional[str], private: bool
    ) -> None:
        """处理漫画删除请求，支持批量删除"""
        self.logger.info(f"处理漫画删除请求 - 用户{user_id}")

        try:
            self.permission_manager.check_delete_permission(user_id)
        except ValueError as e:
            if "必须且只能有一个用户" in str(e):
                response = (
                    "❌\u001b[31m删除功能不可用："
                    "删除权限用户名单必须且只能有一个用户\u001b[0m"
                )
                self.message_sender(user_id, response, group_id, private)
                return
            if "未配置删除权限用户" in str(e):
                response = "❌\u001b[31m删除功能不可用：未配置删除权限用户\u001b[0m"
                self.message_sender(user_id, response, group_id, private)
                return
            error_msg = f"❌ 权限检查失败：{str(e)}"
            self.message_sender(user_id, error_msg, group_id, private)
            return

        try:
            manga_ids, use_all = parse_batch_params(params)

            if use_all:
                manga_ids = self._get_all_downloaded_manga_ids()
                if not manga_ids:
                    self.message_sender(
                        user_id,
                        "❌ 当前没有已下载的漫画",
                        group_id,
                        private,
                    )
                    return

            if not manga_ids:
                self.message_sender(
                    user_id,
                    "❌ 参数错误！请提供有效的漫画ID",
                    group_id,
                    private,
                )
                return

            manga_ids = validate_manga_ids(manga_ids)

            if len(manga_ids) == 1:
                self._delete_single_manga(user_id, manga_ids[0], group_id, private)
            else:
                self._delete_batch_mangas(user_id, manga_ids, group_id, private)
        except ValueError as e:
            self.logger.warning(f"批量删除参数解析失败: {e}")
            self.message_sender(user_id, str(e), group_id, private)

    def _delete_single_manga(
        self, user_id: str, manga_id: str, group_id: Optional[str], private: bool
    ) -> None:
        """删除单个漫画"""
        self.logger.info(f"处理漫画删除请求 - 用户{user_id}, 漫画ID: {manga_id}")

        response = f"ฅ( ̳• ·̫ • ̳ฅ)正在删除漫画ID：{manga_id}，请稍候..."
        self.message_sender(user_id, response, group_id, private)
        self.download_manager.delete_manga(user_id, manga_id, group_id, private)

    def _delete_batch_mangas(
        self, user_id: str, manga_ids: List[str], group_id: Optional[str], private: bool
    ) -> None:
        """批量删除漫画"""
        self.logger.info(
            f"处理批量漫画删除请求 - 用户{user_id}, 漫画ID数量: {len(manga_ids)}"
        )

        response = f"开始批量删除 {len(manga_ids)} 个漫画，请稍候...\n\n"
        response += "删除队列：\n"
        for i, manga_id in enumerate(manga_ids[:10], 1):
            response += f"  {i}. {manga_id}\n"
        if len(manga_ids) > 10:
            response += f"  ... 还有 {len(manga_ids) - 10} 个\n"

        self.message_sender(user_id, response, group_id, private)

        results: List[Tuple[str, bool, str]] = []

        for manga_id in manga_ids:
            try:
                download_path = str(self.config["MANGA_DOWNLOAD_PATH"])

                if not os.path.exists(download_path):
                    results.append((manga_id, False, "下载目录不存在"))
                    continue

                pdf_path = None
                for file_name in os.listdir(download_path):
                    if file_name.startswith(f"{manga_id}-") and file_name.endswith(
                        ".pdf"
                    ):
                        pdf_path = os.path.join(download_path, file_name)
                        break

                if not pdf_path:
                    results.append((manga_id, False, "未找到PDF文件"))
                    continue

                os.remove(pdf_path)
                self.logger.info(f"成功删除漫画PDF文件: {pdf_path}")
                results.append((manga_id, True, "删除成功"))
            except Exception as e:
                self.logger.error(f"删除漫画 {manga_id} 出错: {e}")
                results.append((manga_id, False, str(e)))

        batch_response = format_batch_response("删除", results)
        self.message_sender(user_id, batch_response, group_id, private)
