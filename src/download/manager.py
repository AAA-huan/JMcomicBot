"""下载管理器模块，负责漫画下载功能并对下载队列进行管理"""

import os
import queue
import shutil
import sys
import threading
import time
from typing import Any, Callable, Dict, Optional, Tuple

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
            delay_minutes: 延迟分钟数，默认5分钟
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

            self.logger.info("开始下载漫画ID: %s", manga_id)
            option = jmcomic.create_option_by_file("option.yml")
            option.dir_rule.base_dir = self.config["MANGA_DOWNLOAD_PATH"]

            new_rule = "Bd / {Aid}-{Atitle}"
            option.dir_rule = DirRule(new_rule, base_dir=option.dir_rule.base_dir)

            jmcomic.download_album(manga_id, option=option)

            manga_dir = None
            download_path = str(self.config["MANGA_DOWNLOAD_PATH"])
            if os.path.exists(download_path):
                for dir_name in os.listdir(download_path):
                    dir_path = os.path.join(download_path, dir_name)
                    if os.path.isdir(dir_path) and dir_name.startswith(f"{manga_id}-"):
                        manga_dir = dir_path
                        break

            if not manga_dir:
                for root, dirs, files in os.walk(download_path):
                    for dir_name in dirs:
                        if dir_name.startswith(f"{manga_id}-"):
                            manga_dir = os.path.join(root, dir_name)
                            break
                    if manga_dir:
                        break

            if manga_dir and os.path.exists(manga_dir):
                folder_name = os.path.basename(manga_dir)
                pdf_path = os.path.join(download_path, f"{folder_name}.pdf")

                try:
                    from PIL import Image
                except ImportError:
                    self.logger.info("正在安装PIL库...")
                    import subprocess

                    subprocess.check_call(
                        [sys.executable, "-m", "pip", "install", "Pillow"]
                    )
                    from PIL import Image

                image_extensions = [".jpg", ".jpeg", ".png", ".gif", ".webp"]
                image_files = []

                for root, _, files in os.walk(manga_dir):
                    for file in files:
                        if any(file.lower().endswith(ext) for ext in image_extensions):
                            image_files.append(os.path.join(root, file))

                image_files.sort()

                if not image_files:
                    self.logger.warning(f"在漫画文件夹中未找到图片文件: {manga_dir}")
                    response = (
                        f"✅（｀Δ´）！ 漫画ID {manga_id} 下载完成！\n"
                        f"未找到图片文件，无法转换为PDF\n\n"
                        f"⚠️ 注意：当前版本只支持发送PDF格式的漫画文件"
                    )
                    self.message_sender(user_id, response, group_id, private)
                    return

                self.logger.info(f"找到 {len(image_files)} 个图片文件，开始转换为PDF")

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
                        pdf_path, save_all=True, append_images=other_images
                    )
                    self.logger.info(f"成功将漫画 {manga_id} 转换为PDF: {pdf_path}")

                    self.logger.info(f"删除原漫画文件夹: {manga_dir}")
                    shutil.rmtree(manga_dir)

                    if self.low_memory_mode and self.file_sender:
                        # 低占用模式：自动发送PDF
                        response = (
                            f"✅ദ്ദി˶>ω<)✧ "
                            f"漫画ID {manga_id} 下载完成！正在自动发送...\n\n"
                            f"⚠️ 低占用模式：文件将在5分钟后自动删除"
                        )
                        self.message_sender(user_id, response, group_id, private)

                        # 自动发送文件
                        try:
                            self.file_sender(user_id, pdf_path, group_id, private)
                            self.logger.info(
                                f"低占用模式：已自动发送PDF文件: {os.path.basename(pdf_path)}"
                            )

                            # 安排延迟删除
                            self._schedule_file_deletion(pdf_path, 5)
                        except Exception as send_error:
                            self.logger.error(f"低占用模式自动发送失败: {send_error}")
                            error_response = f"❌ 自动发送失败：{str(send_error)}"
                            self.message_sender(
                                user_id, error_response, group_id, private
                            )
                    else:
                        # 普通模式
                        response = (
                            f"✅ദ്ദി˶>ω<)✧ "
                            f"漫画ID {manga_id} 下载并转换为PDF完成！\n\n"
                            f"友情提示：输入'发送 {manga_id}'可以将PDF发送给您"
                        )
                except Exception as pdf_error:
                    self.logger.error(f"转换为PDF失败: {pdf_error}")
                    response = (
                        f"✅（｀Δ´）！ 漫画ID {manga_id} 下载完成，"
                        f"但转换为PDF失败: {str(pdf_error)}\n\n"
                        f"⚠️ 注意：当前版本只支持发送PDF格式的漫画文件，"
                        f"请确保漫画成功转换为PDF后再尝试发送"
                    )
            else:
                response = (
                    f"✅（｀Δ´）！ 漫画ID {manga_id} 下载完成！\n"
                    f"未找到漫画文件夹，无法转换为PDF\n\n"
                    f"⚠️ 注意：当前版本只支持发送PDF格式的漫画文件，"
                    f"请确保漫画成功转换为PDF后再尝试发送"
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
