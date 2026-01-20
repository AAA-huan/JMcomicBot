import os
import queue
import threading
from typing import Any, Callable, Dict, Optional, Tuple

import jmcomic

from src.logging.logger_config import logger


class DownloadManager:
    """漫画下载管理器，负责漫画下载功能并对下载队列进行管理"""

    def __init__(
        self,
        logger: Any,
        config: Dict[str, Any],
        message_sender: Callable[[str, str, Optional[str], bool], None],
    ) -> None:
        """
        初始化下载管理器

        Args:
            logger: 日志记录器
            config: 配置字典
            message_sender: 消息发送函数
        """
        self.logger = logger
        self.config = config
        self.message_sender = message_sender
        self.download_queue: queue.Queue = queue.Queue()
        self.queue_running: bool = True
        self.queued_tasks: Dict[str, Tuple[str, Optional[str], bool]] = {}
        self.downloading_mangas: Dict[str, bool] = {}
        self._start_download_queue_processor()

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
                    except:
                        pass

        queue_thread = threading.Thread(target=process_queue, daemon=True)
        queue_thread.start()
        self.logger.info("下载队列处理线程已启动")

    def _process_download_task(self, user_id: str, manga_id: str, group_id: str, private: bool) -> None:
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
            from jmcomic.jm_option import DirRule

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
                import shutil
                import sys

                try:
                    from PIL import Image
                except ImportError:
                    self.logger.info("正在安装PIL库...")
                    import subprocess

                    subprocess.check_call([sys.executable, "-m", "pip", "install", "Pillow"])
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
                    response = f"✅（｀Δ´）！ 漫画ID {manga_id} 下载完成！\n未找到图片文件，无法转换为PDF\n\n⚠️ 注意：当前版本只支持发送PDF格式的漫画文件"
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

                    first_image.save(pdf_path, save_all=True, append_images=other_images)
                    self.logger.info(f"成功将漫画 {manga_id} 转换为PDF: {pdf_path}")

                    self.logger.info(f"删除原漫画文件夹: {manga_dir}")
                    shutil.rmtree(manga_dir)

                    response = f"✅ദ്ദി˶>ω<)✧ 漫画ID {manga_id} 下载并转换为PDF完成！\n\n友情提示：输入'发送 {manga_id}'可以将PDF发送给您"
                except Exception as pdf_error:
                    self.logger.error(f"转换为PDF失败: {pdf_error}")
                    response = f"✅（｀Δ´）！ 漫画ID {manga_id} 下载完成，但转换为PDF失败: {str(pdf_error)}\n\n⚠️ 注意：当前版本只支持发送PDF格式的漫画文件，请确保漫画成功转换为PDF后再尝试发送"
            else:
                response = f"✅（｀Δ´）！ 漫画ID {manga_id} 下载完成！\n未找到漫画文件夹，无法转换为PDF\n\n⚠️ 注意：当前版本只支持发送PDF格式的漫画文件，请确保漫画成功转换为PDF后再尝试发送"

            self.message_sender(user_id, response, group_id, private)
        except Exception as e:
            self.logger.error(f"下载漫画出错: {e}")
            error_msg = f"❌ 下载失败：{str(e)}\n\n快让主人帮我检查一下∑(O_O；)"
            self.message_sender(user_id, error_msg, group_id, private)
        finally:
            if manga_id in self.downloading_mangas:
                del self.downloading_mangas[manga_id]

    def download_manga(self, user_id: str, manga_id: str, group_id: str, private: bool) -> None:
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
