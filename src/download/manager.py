"""下载管理器模块，负责漫画下载功能并对下载队列进行管理"""

import os
import queue
import shutil
import tempfile
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import img2pdf
import jmcomic
from jmcomic.jm_config import JmModuleConfig
from jmcomic.jm_option import DirRule
from pypdf import PdfWriter

from src.download.progress_tracker import ProgressTracker


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

    def _process_download_task(
        self, user_id: str, manga_id: str, group_id: str, private: bool
    ) -> None:
        """
        处理队列中的下载任务
        串行下载各个章节，每章下载后立即收集图片，最后统一通过 img2pdf + pypdf 合并为单个 PDF。
        """
        temp_download_dir = None
        try:
            if manga_id in self.queued_tasks:
                del self.queued_tasks[manga_id]
            self.downloading_mangas[manga_id] = True

            self.logger.info(f"开始下载漫画ID: {manga_id}")
            option = jmcomic.create_option_by_file("option.yml")
            download_path = str(self.config["MANGA_DOWNLOAD_PATH"])
            temp_download_dir = os.path.join(download_path, "temp")
            os.makedirs(temp_download_dir, exist_ok=True)

            # 获取 album 元数据 → 章节列表（已按 photo_index 排序）
            client = option.new_jm_client()
            album = client.get_album_detail(manga_id)
            episode_list = album.episode_list
            album_name = album.name
            chapter_count = len(episode_list)

            # 安装进度追踪器（先注入 album 元数据，再安装日志处理器）
            tracker = ProgressTracker(self.logger, manga_id)
            tracker.setup_from_album(album)
            original_executor = JmModuleConfig.EXECUTOR_LOG  # type: ignore
            JmModuleConfig.EXECUTOR_LOG = tracker.make_log_handler()  # type: ignore
            JmModuleConfig.FLAG_ENABLE_JM_LOG = True

            # 创建累积 PDF
            pdf_path = os.path.join(
                download_path,
                f"{manga_id}-{album_name}({chapter_count}章).pdf",
            )
            pdf_writer = PdfWriter()
            total_pages = 0

            try:
                for photo_id, photo_index, photo_title, *_ in episode_list:
                    # 本章唯一临时目录（扁平，无子文件夹）
                    chapter_dir = tempfile.mkdtemp(dir=temp_download_dir)
                    option.dir_rule = DirRule("Bd", base_dir=chapter_dir)

                    # 下载本章
                    jmcomic.download_photo(photo_id, option=option)

                    # 收集图片
                    image_extensions = [".jpg", ".jpeg", ".png", ".gif", ".webp"]
                    images = sorted(
                        [
                            os.path.join(chapter_dir, f)
                            for f in os.listdir(chapter_dir)
                            if any(f.lower().endswith(ext) for ext in image_extensions)
                        ]
                    )

                    if not images:
                        self.logger.warning(f"章节 {photo_title} 中未找到图片，跳过")
                        continue

                    # 本章图片 → 临时 PDF → 追加到累积 PDF
                    chapter_pdf = os.path.join(chapter_dir, "chapter.pdf")
                    with open(chapter_pdf, "wb") as f:
                        img2pdf.convert(
                            images,
                            outputstream=f,
                            rotation=img2pdf.Rotation.ifvalid,
                        )
                    pdf_writer.append(chapter_pdf)
                    total_pages += len(images)

                    # 清理本章临时目录
                    shutil.rmtree(chapter_dir)
            finally:
                JmModuleConfig.EXECUTOR_LOG = original_executor  # type: ignore
                tracker.finish()

            # 写出最终 PDF
            with open(pdf_path, "wb") as f:
                pdf_writer.write(f)
            pdf_writer.close()

            # 生成响应消息
            chapter_info = f"（{chapter_count} 个章节）" if chapter_count > 1 else ""
            if self.low_memory_mode and self.file_sender:
                delete_delay = self.config.get("LOW_MEMORY_DELETE_DELAY", 3)
                response = (
                    f"✅ദ്ദി˶>ω<)✧ "
                    f"漫画ID {manga_id}{chapter_info} 下载完成！\n\n"
                    f"成功生成PDF文件（共{total_pages}页）\n"
                    f"⚠️ 低占用模式：文件将在{delete_delay}分钟后自动删除"
                )
                try:
                    self.file_sender(user_id, pdf_path, group_id, private)
                    self.logger.info(
                        f"低占用模式：已自动发送PDF文件: "
                        f"{os.path.basename(pdf_path)}"
                    )
                except Exception as send_error:
                    self.logger.error(f"发送PDF文件失败: {send_error}")
                self._schedule_file_deletion(pdf_path, delete_delay)
            else:
                response = (
                    f"✅ദ്ദി˶>ω<)✧ "
                    f"漫画ID {manga_id}{chapter_info} 下载并转换为PDF完成！\n\n"
                    f"成功生成PDF文件（共{total_pages}页）\n"
                    f"友情提示：输入'发送 {manga_id}'可以将PDF发送给您"
                )

            self.message_sender(user_id, response, group_id, private)

        except Exception as e:
            self.logger.error(f"下载漫画出错: {e}")
            error_msg = f"❌ 下载失败：{str(e)}\n\n快让主人帮我检查一下∑(O_O；)"
            self.message_sender(user_id, error_msg, group_id, private)
        finally:
            if manga_id in self.downloading_mangas:
                del self.downloading_mangas[manga_id]
            if temp_download_dir is not None:
                shutil.rmtree(temp_download_dir, ignore_errors=True)

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

        pdf_paths: List[str] = []
        for file_name in os.listdir(download_path):
            if file_name.endswith(".pdf") and (
                file_name.startswith(f"{manga_id}-") or file_name == f"{manga_id}.pdf"
            ):
                pdf_paths.append(os.path.join(download_path, file_name))

        if not pdf_paths:
            response = f"❌（｀Δ´）！ 未找到漫画ID {manga_id} 的PDF文件"
            self.message_sender(user_id, response, group_id, private)
            return

        try:
            deleted_count = 0
            for pdf_path in pdf_paths:
                os.remove(pdf_path)
                self.logger.info(f"成功删除漫画PDF文件: {pdf_path}")
                deleted_count += 1
            response = (
                f"✅ദ്ദി˶>ω<)✧ 漫画ID {manga_id} 的{deleted_count}个PDF文件已成功删除！"
            )
            self.message_sender(user_id, response, group_id, private)
        except Exception as e:
            self.logger.error(f"删除漫画PDF文件失败: {e}")
            error_msg = f"❌ 删除失败：{str(e)}\n快让主人帮我检查一下ヽ(ﾟДﾟ)ﾉ"
            self.message_sender(user_id, error_msg, group_id, private)
            raise
