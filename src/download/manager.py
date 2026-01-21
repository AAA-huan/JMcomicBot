"""下载管理器模块，负责漫画下载功能并对下载队列进行管理"""

import contextlib
import io
import os
import queue
import shutil
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import jmcomic
from jmcomic.jm_option import DirRule


class DownloadManager:
    """漫画下载管理器，负责漫画下载功能并对下载队列进行管理"""

    def __init__(
        self,
        logger_instance: Any,
        config: Dict[str, Any],
        message_sender: Callable[[str, str, Optional[str], bool], None],
        file_sender: Optional[Callable[[str, str, Optional[str], bool], None]] = None,
    ) -> None:
        """
        初始化下载管理器

        Args:
            logger_instance: 日志记录器
            config: 配置字典
            message_sender: 消息发送函数
            file_sender: 文件发送函数（用于低占用模式自动发送）
        """
        self.logger = logger_instance
        self.config = config
        self.message_sender = message_sender
        self.file_sender = file_sender
        self.download_queue: queue.Queue = queue.Queue()
        self.queue_running: bool = True
        self.queued_tasks: Dict[str, Tuple[str, Optional[str], bool]] = {}
        self.downloading_mangas: Dict[str, bool] = {}
        self._start_download_queue_processor()

        # 检查是否启用低占用模式
        self.low_memory_mode: bool = bool(self.config.get("LOW_MEMORY_MODE", False))

        # 如果启用低占用模式，启动时清空下载文件夹
        if self.low_memory_mode:
            self._clear_download_folder()

    def _start_download_queue_processor(self) -> None:
        """
        启动下载队列处理线程
        该线程将不断从队列中取出下载任务并顺序执行
        """

        def process_queue() -> None:
            """下载队列处理函数，顺序执行队列中的下载任务"""
            while self.queue_running:
                try:
                    task = self.download_queue.get(timeout=1)
                    user_id, manga_id, group_id, private = task
                    self._process_download_task(user_id, manga_id, group_id, private)
                    self.download_queue.task_done()
                except queue.Empty:
                    continue
                except Exception as e:
                    self.logger.error(f"处理下载队列任务时出错: {e}")
                    try:
                        self.download_queue.task_done()
                    except Exception:
                        pass

        queue_thread = threading.Thread(target=process_queue, daemon=True)
        queue_thread.start()
        self.logger.info("下载队列处理线程已启动")

    def _clear_download_folder(self) -> None:
        """
        清空下载文件夹中的所有PDF文件
        仅在低占用模式下启动时调用
        """
        download_path = str(self.config["MANGA_DOWNLOAD_PATH"])

        if not os.path.exists(download_path):
            self.logger.info(f"下载目录不存在，跳过清空: {download_path}")
            return

        deleted_count = 0
        try:
            for file_name in os.listdir(download_path):
                if file_name.endswith(".pdf"):
                    file_path = os.path.join(download_path, file_name)
                    os.remove(file_path)
                    self.logger.info(f"已删除PDF文件: {file_name}")
                    deleted_count += 1

            self.logger.info(f"低占用模式：已清空 {deleted_count} 个PDF文件")
        except Exception as e:
            self.logger.error(f"清空下载文件夹时出错: {e}")
            raise

    def _schedule_file_deletion(self, file_path: str, delay_minutes: int = 5) -> None:
        """
        延迟删除文件

        Args:
            file_path: 要删除的文件路径
            delay_minutes: 延迟分钟数，默认3分钟
        """

        def delete_after_delay() -> None:
            try:
                time.sleep(delay_minutes * 60)
                if os.path.exists(file_path):
                    os.remove(file_path)
                    self.logger.info(
                        f"低占用模式：已延迟删除文件: {os.path.basename(file_path)}"
                    )
            except Exception as e:
                self.logger.error(f"延迟删除文件时出错: {e}")

        deletion_thread = threading.Thread(target=delete_after_delay, daemon=True)
        deletion_thread.start()
        self.logger.info(
            f"已安排在 {delay_minutes} 分钟后删除文件: {os.path.basename(file_path)}"
        )

    def _find_chapter_folders(self, temp_download_dir: str, manga_id: str) -> List[str]:
        """
        查找临时下载目录中的所有章节文件夹

        Args:
            temp_download_dir: 临时下载目录
            manga_id: 漫画ID

        Returns:
            章节文件夹路径列表
        """
        chapter_folders = []
        if not os.path.exists(temp_download_dir):
            return chapter_folders

        for dir_name in os.listdir(temp_download_dir):
            dir_path = os.path.join(temp_download_dir, dir_name)
            if os.path.isdir(dir_path):
                chapter_folders.append(dir_path)

        return chapter_folders

    def _collect_images_from_chapter(self, chapter_folder: str) -> List[str]:
        """
        收集单个章节文件夹中的所有图片文件

        Args:
            chapter_folder: 章节文件夹路径

        Returns:
            排序后的图片文件路径列表
        """
        image_extensions = [".jpg", ".jpeg", ".png", ".gif", ".webp"]
        image_files = []

        for root, _, files in os.walk(chapter_folder):
            for file in files:
                if any(file.lower().endswith(ext) for ext in image_extensions):
                    image_files.append(os.path.join(root, file))

        image_files.sort()
        return image_files

    def _convert_chapter_to_pdf(self, chapter_folder: str, download_path: str) -> Optional[str]:
        """
        将单个章节文件夹转换为PDF文件

        Args:
            chapter_folder: 章节文件夹路径
            download_path: 最终PDF存放目录

        Returns:
            PDF文件路径，转换失败返回None
        """
        try:
            from PIL import Image
        except ImportError:
            self.logger.info("正在安装PIL库...")
            import subprocess
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "Pillow"]
            )
            from PIL import Image

        image_files = self._collect_images_from_chapter(chapter_folder)

        if not image_files:
            self.logger.warning(f"章节文件夹中未找到图片: {chapter_folder}")
            return None

        chapter_name = os.path.basename(chapter_folder)
        temp_pdf_path = os.path.join(os.path.dirname(chapter_folder), f"{chapter_name}.pdf")
        final_pdf_path = os.path.join(download_path, f"{chapter_name}.pdf")

        try:
            first_image = Image.open(image_files[0])
            if first_image.mode == "RGBA":
                first_image = first_image.convert("RGB")

            other_images = []
            for img_path in image_files[1:]:
                img = Image.open(img_path)
                if img.mode == "RGBA":
                    img = img.convert("RGB")
                other_images.append(img)

            first_image.save(
                temp_pdf_path, save_all=True, append_images=other_images
            )
            self.logger.info(f"成功将章节 {chapter_name} 转换为PDF: {temp_pdf_path}")

            # 移动PDF到downloads目录
            shutil.move(temp_pdf_path, final_pdf_path)
            self.logger.info(f"已移动PDF到: {final_pdf_path}")
            return final_pdf_path

        except Exception as e:
            self.logger.error(f"转换章节 {chapter_name} 为PDF失败: {e}")
            return None

    def _cleanup_chapter_folders(self, temp_download_dir: str) -> None:
        """
        清理临时下载目录中的所有章节文件夹

        Args:
            temp_download_dir: 临时下载目录
        """
        if not os.path.exists(temp_download_dir):
            return

        try:
            for item in os.listdir(temp_download_dir):
                item_path = os.path.join(temp_download_dir, item)
                if os.path.isdir(item_path):
                    shutil.rmtree(item_path)
            self.logger.info(f"已清理临时下载目录中的章节文件夹: {temp_download_dir}")
        except Exception as e:
            self.logger.error(f"清理临时下载目录 {temp_download_dir} 中的章节文件夹时出错: {e}")

    def _process_download_task(
        self, user_id: str, manga_id: str, group_id: str, private: bool
    ) -> None:
        """
        处理队列中的下载任务
        实际执行漫画下载的方法，确保下载任务按顺序执行，避免并发下载导致的资源竞争

        Args:
            user_id: 用户ID，用于回复下载状态
            manga_id: 漫画ID，指定要下载的漫画
            group_id: 群ID，用于在群聊中发送消息
            private: 是否为私聊，决定消息发送的目标
        """
        try:
            if manga_id in self.queued_tasks:
                del self.queued_tasks[manga_id]
            self.downloading_mangas[manga_id] = True

            self.logger.info(f"开始下载漫画ID: {manga_id}")
            option = jmcomic.create_option_by_file("option.yml")
            
            # 使用临时文件夹存放下载内容，避免与其他下载冲突
            download_path = str(self.config["MANGA_DOWNLOAD_PATH"])
            temp_download_dir = os.path.join(download_path, "temp")
            option.dir_rule.base_dir = temp_download_dir

            new_rule = "Bd / {Aid}-{Ptitle}"
            option.dir_rule = DirRule(new_rule, base_dir=option.dir_rule.base_dir)

            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                jmcomic.download_album(manga_id, option=option)

            # 查找临时文件夹中的所有章节文件夹
            chapter_folders = self._find_chapter_folders(temp_download_dir, manga_id)

            if not chapter_folders:
                response = (
                    f"✅（｀Δ´）！ 漫画ID {manga_id} 下载完成！\n"
                    f"未找到章节文件夹，无法转换为PDF\n\n"
                    f"⚠️ 注意：当前版本只支持发送PDF格式的漫画文件，"
                    f"请确保漫画成功转换为PDF后再尝试发送"
                )
                self.message_sender(user_id, response, group_id, private)
                return

            # 为每个章节单独生成PDF
            success_count = 0
            failed_count = 0
            pdf_files = []

            for chapter_folder in chapter_folders:
                chapter_name = os.path.basename(chapter_folder)
                pdf_path = self._convert_chapter_to_pdf(chapter_folder, download_path)

                if pdf_path:
                    pdf_files.append(pdf_path)
                    success_count += 1
                else:
                    failed_count += 1

            # 清理临时文件夹
            self._cleanup_chapter_folders(temp_download_dir)

            # 生成响应消息
            if success_count > 0:
                chapter_info = f"（{success_count} 个章节）" if success_count > 1 else ""
                if self.low_memory_mode and self.file_sender:
                    # 低占用模式：自动发送所有PDF
                    delete_delay = self.config.get("LOW_MEMORY_DELETE_DELAY", 3)
                    response = (
                        f"✅ദ്ദി˶>ω<)✧ "
                        f"漫画ID {manga_id}{chapter_info} 下载完成！\n\n"
                        f"成功生成 {success_count} 个PDF文件\n"
                        f"⚠️ 低占用模式：文件将在{delete_delay}分钟后自动删除"
                    )
                    self.message_sender(user_id, response, group_id, private)

                    # 自动发送所有PDF文件
                    for pdf_path in pdf_files:
                        try:
                            self.file_sender(user_id, pdf_path, group_id, private)
                            self.logger.info(
                                f"低占用模式：已自动发送PDF文件: {os.path.basename(pdf_path)}"
                            )
                        except Exception as send_error:
                            self.logger.error(f"发送PDF文件失败: {send_error}")

                    # 安排延迟删除所有PDF文件
                    for pdf_path in pdf_files:
                        self._schedule_file_deletion(pdf_path, delete_delay)
                else:
                    # 普通模式
                    response = (
                        f"✅ദ്ദി˶>ω<)✧ "
                        f"漫画ID {manga_id}{chapter_info} 下载并转换为PDF完成！\n\n"
                        f"成功生成 {success_count} 个PDF文件\n"
                        f"友情提示：输入'发送 {manga_id}'可以将PDF发送给您"
                    )
            else:
                response = (
                    f"❌ 漫画ID {manga_id} 下载完成，但所有章节转换失败\n"
                    f"失败：{failed_count} 个章节\n"
                    f"请查看日志获取详细错误信息"
                )

            self.message_sender(user_id, response, group_id, private)

        except Exception as e:
            self.logger.error(f"下载漫画出错: {e}")
            error_msg = f"❌ 下载失败：{str(e)}\n\n快让主人帮我检查一下∑(O_O；)"
            self.message_sender(user_id, error_msg, group_id, private)
        finally:
            if manga_id in self.downloading_mangas:
                del self.downloading_mangas[manga_id]

    def download_manga(
        self, user_id: str, manga_id: str, group_id: Optional[str], private: bool
    ) -> None:
        """
        下载漫画的兼容方法
        保持向后兼容，实际操作是将任务添加到下载队列，而不是直接执行下载
        这样可以确保所有下载任务按顺序执行，避免资源冲突和混乱

        Args:
            user_id: 用户ID，用于回复下载状态
            manga_id: 漫画ID，指定要下载的漫画
            group_id: 群ID，用于在群聊中发送消息
            private: 是否为私聊，决定消息发送的目标
        """
        self.queued_tasks[manga_id] = (user_id, group_id, private)
        self.download_queue.put((user_id, manga_id, group_id, private))
        self.logger.info(f"漫画ID {manga_id} 的下载任务已添加到队列")

    def delete_manga(
        self, user_id: str, manga_id: str, group_id: Optional[str], private: bool
    ) -> None:
        """
        删除指定ID的漫画PDF文件

        Args:
            user_id: 用户ID，用于回复删除状态
            manga_id: 漫画ID，指定要删除的漫画
            group_id: 群ID，用于在群聊中发送消息
            private: 是否为私聊，决定消息发送的目标

        Raises:
            FileNotFoundError: 当下载目录不存在时
        """
        download_path = str(self.config["MANGA_DOWNLOAD_PATH"])

        if not os.path.exists(download_path):
            error_msg = "❌ 下载目录不存在！\n快让主人帮我检查一下ヽ(ﾟДﾟ)ﾉ"
            self.message_sender(user_id, error_msg, group_id, private)
            raise FileNotFoundError(f"下载目录不存在: {download_path}")

        pdf_path = None
        for file_name in os.listdir(download_path):
            if file_name.startswith(f"{manga_id}-") and file_name.endswith(".pdf"):
                pdf_path = os.path.join(download_path, file_name)
                break

        if not pdf_path:
            response = f"❌（｀Δ´）！ 未找到漫画ID {manga_id} 的PDF文件"
            self.message_sender(user_id, response, group_id, private)
            return

        try:
            os.remove(pdf_path)
            self.logger.info(f"成功删除漫画PDF文件: {pdf_path}")
            response = f"✅ദ്ദി˶>ω<)✧ 漫画ID {manga_id} 的PDF文件已成功删除！"
            self.message_sender(user_id, response, group_id, private)
        except Exception as e:
            self.logger.error(f"删除漫画PDF文件失败: {e}")
            error_msg = f"❌ 删除失败：{str(e)}\n快让主人帮我检查一下ヽ(ﾟДﾟ)ﾉ"
            self.message_sender(user_id, error_msg, group_id, private)
            raise
