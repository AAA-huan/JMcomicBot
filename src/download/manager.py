"""下载管理器模块，负责漫画下载功能并对下载队列进行管理"""

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

import os
import queue
import shutil
import threading
import time

import jmcomic
from jmcomic.jm_option import DirRule

from src.database.repositories import (
    MangaRepository,
    MangaTagRepository,
    TaskLogRepository,
)
from src.service import OperationContext, TaskService
from src.service.contracts import DownloadNotifier
from src.service.results import DownloadRequestItem
from src.utils.helpers import sanitize_filename


@dataclass(frozen=True)
class QQDownloadNotifier:
    """把下载过程通知转发到 QQ 消息与文件发送器的适配器。"""

    message_sender: Callable[[str, str, Optional[str], bool], None]
    file_sender: Optional[Callable[[str, str, Optional[str], bool], None]]
    user_id: str
    group_id: Optional[str]
    private: bool

    def message(self, text: str) -> None:
        """发送下载过程文本消息。"""
        self.message_sender(self.user_id, text, self.group_id, self.private)

    def file(self, file_path: str) -> None:
        """发送下载完成的 PDF 文件；未配置文件发送器时明确报错。"""
        if self.file_sender is None:
            raise RuntimeError("未配置文件发送器，无法发送下载文件")
        self.file_sender(self.user_id, file_path, self.group_id, self.private)


@dataclass(frozen=True)
class DownloadQueueItem:
    """下载队列中的单个任务；Web 来源不传通知器表示静默。"""

    manga_id: str
    context: OperationContext
    operation_task_id: Optional[str]
    notifier: Optional[DownloadNotifier]


def build_pdf_filename(manga_id: str, safe_title: str, chapter_count: int) -> str:
    """构造漫画 PDF 文件名（不含后缀），标题使用已清洗的安全标题，规避文件名超长/非法字符问题"""
    filename = f"{manga_id}-{safe_title}({chapter_count}章)"
    # 大括号会干扰 jmcomic f-string 规则解析，替换为下划线
    return filename.replace("{", "_").replace("}", "_")


def build_pdf_plugin_config(
    manga_id: str, safe_title: str, chapter_count: int, pdf_dir: str
) -> Dict[str, Any]:
    """构造 img2pdf 插件的 YAML 风格配置，供代码注入 option.plugins 使用"""
    return {
        "plugin": "img2pdf",
        "kwargs": {
            "pdf_dir": pdf_dir,
            "filename_rule": build_pdf_filename(manga_id, safe_title, chapter_count),
            "delete_original_file": True,
        },
    }


def inject_img2pdf_plugin(
    option: Any, manga_id: str, safe_title: str, chapter_count: int, pdf_dir: str
) -> None:
    """向 jmcomic option 注入或覆盖 img2pdf 插件配置

    无论用户是否已在 option.yml 自定义 img2pdf 插件，filename_rule 与 pdf_dir
    始终由代码覆盖，确保 PDF 文件名使用真实章节数、输出到 pdf_dir 指定目录；
    用户配置的 delete_original_file 等其余 kwargs 予以保留。

    Args:
        option: jmcomic 配置对象，其 plugins 会被就地修改
        manga_id: 漫画ID
        safe_title: 已清洗的安全标题
        chapter_count: 真实章节数（来自 episode_list 长度）
        pdf_dir: PDF 输出目录，始终覆盖为用户配置的下载目录
    """
    pdf_filename_rule = build_pdf_filename(manga_id, safe_title, chapter_count)
    after_album = option.plugins.get("after_album") or []
    img2pdf_plugin = next(
        (p for p in after_album if p.get("plugin") == "img2pdf"), None
    )
    if img2pdf_plugin is None:
        option.plugins["after_album"] = after_album + [
            build_pdf_plugin_config(manga_id, safe_title, chapter_count, pdf_dir)
        ]
    else:
        # 尊重用户对 delete_original_file 等的配置，但强制覆盖文件名规则与输出目录
        img2pdf_plugin["kwargs"] = {
            **img2pdf_plugin.get("kwargs", {}),
            "pdf_dir": pdf_dir,
            "filename_rule": pdf_filename_rule,
        }


def build_progress_plugin_config(log_file: str) -> Dict[str, Any]:
    """构造 download_progress 插件的 YAML 风格配置，供代码注入 option.plugins 使用"""
    return {
        "plugin": "download_progress",
        "kwargs": {
            "log_file": log_file,
            "terminal_log_lines": 6,
        },
    }


class DownloadManager:
    """漫画下载管理器，负责漫画下载功能并对下载队列进行管理"""

    def __init__(
        self,
        logger_instance: Any,
        config: Dict[str, Any],
        message_sender: Callable[[str, str, Optional[str], bool], None],
        file_sender: Optional[Callable[[str, str, Optional[str], bool], None]] = None,
        manga_repo: Optional[MangaRepository] = None,
        task_log_repo: Optional[TaskLogRepository] = None,
        tag_repo: Optional[MangaTagRepository] = None,
        operation_task_service: Optional[TaskService] = None,
        send_conflict_checker: Optional[Callable[[str], bool]] = None,
    ) -> None:
        """
        初始化下载管理器

        Args:
            logger_instance: 日志记录器
            config: 配置字典
            message_sender: 消息发送函数
            file_sender: 文件发送函数（用于低占用模式自动发送）
            manga_repo: 漫画元数据仓储，持久化漫画信息到数据库
            task_log_repo: 任务日志仓储，记录下载任务到数据库
            tag_repo: 漫画标签仓储，下载时记录漫画标签
            operation_task_service: 持久化操作任务服务
        """
        self.logger = logger_instance
        self.config = config
        self.message_sender = message_sender
        self.file_sender = file_sender
        self.manga_repo = manga_repo
        self.task_log_repo = task_log_repo
        self.tag_repo = tag_repo
        self.operation_task_service = operation_task_service
        self.send_conflict_checker = send_conflict_checker
        self.download_queue: queue.Queue = queue.Queue()
        self.queue_running: bool = True
        self._stop_event: threading.Event = threading.Event()
        self._queue_state_lock: threading.Lock = threading.Lock()
        self._queue_thread: Optional[threading.Thread] = None
        self.queued_tasks: Dict[str, DownloadQueueItem] = {}
        self.downloading_mangas: Dict[str, bool] = {}
        self._start_download_queue_processor()

        # 取消下载任务标记：排队中尚未开始的任务可通过取消标记被跳过
        self.cancelled_downloads: Dict[str, bool] = {}
        self.operation_task_ids: Dict[str, str] = {}

        # 检查是否启用低占用模式
        self.low_memory_mode: bool = bool(self.config.get("LOW_MEMORY_MODE", False))
        # 低内存模式下发送完成后的文件删除延迟（分钟），可被 SettingsService 动态更新
        self.low_memory_delete_delay: int = int(
            self.config.get("LOW_MEMORY_DELETE_DELAY", 3)
        )

        # 如果启用低占用模式，启动时清空下载文件夹
        if self.low_memory_mode:
            self._clear_download_folder()

    def get_queue_status(self) -> Dict[str, object]:
        """返回不包含用户信息和本地路径的下载队列状态。

        queue_size 为任务总数（排队 + 正在下载），pending_count 为排队数，
        current_manga_id 为正在下载的漫画 ID；任务被 worker 取走后总数保持不变。
        """
        current_manga_id = next(iter(self.downloading_mangas), None)
        pending_count = self.download_queue.qsize()
        return {
            "running": self.queue_running,
            "queue_size": pending_count + (1 if current_manga_id is not None else 0),
            "pending_count": pending_count,
            "current_manga_id": current_manga_id,
        }

    def _start_download_queue_processor(self) -> None:
        """
        启动下载队列处理线程
        该线程将不断从队列中取出下载任务并顺序执行
        """

        def process_queue() -> None:
            """下载队列处理函数，顺序执行队列中的下载任务"""
            while not self._stop_event.is_set():
                try:
                    item = self.download_queue.get(timeout=1)
                    if item is None or self._stop_event.is_set():
                        self.download_queue.task_done()
                        return
                    self._process_download_task(item)
                    self.download_queue.task_done()
                except queue.Empty:
                    continue
                except Exception as e:  # pylint: disable=broad-exception-caught
                    self.logger.error(f"处理下载队列任务时出错: {e}")
                    try:
                        self.download_queue.task_done()
                    except Exception:  # pylint: disable=broad-exception-caught
                        pass

        self._queue_thread = threading.Thread(
            target=process_queue,
            daemon=True,
            name="download-queue",
        )
        self._queue_thread.start()
        self.logger.info("下载队列处理线程已启动")

    def stop(self, timeout: float = 1.0) -> bool:
        """停止接收下载任务，并有限等待当前下载线程退出

        jmcomic 的进行中下载无法从外部安全中断，因此只做有界等待；未完成的
        临时文件会由下次启动清理。

        Args:
            timeout: 等待下载线程退出的最长秒数

        Returns:
            bool: 下载线程是否已退出
        """
        with self._queue_state_lock:
            self.queue_running = False
            self._stop_event.set()
            self.queued_tasks.clear()
            self.download_queue.put(None)
        if self._queue_thread is not None:
            self._queue_thread.join(timeout=timeout)
            if self._queue_thread.is_alive():
                active_ids = list(self.downloading_mangas.keys())
                self.logger.warning(
                    f"下载线程未在限定时间内停止，进行中的任务将随进程退出: {active_ids}"
                )
                return False
        self.logger.info("下载队列线程已停止")
        return True

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
        except Exception as e:  # pylint: disable=broad-exception-caught
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
            except Exception as e:  # pylint: disable=broad-exception-caught
                self.logger.error(f"延迟删除文件时出错: {e}")

        deletion_thread = threading.Thread(target=delete_after_delay, daemon=True)
        deletion_thread.start()
        self.logger.info(
            f"已安排在 {delay_minutes} 分钟后删除文件: {os.path.basename(file_path)}"
        )

    def _process_download_task(self, item: DownloadQueueItem) -> None:
        """
        处理队列中的下载任务
        通过 jmcomic 原生 download_album 整本下载，并注入 img2pdf 插件在下载完成后自动合并为单个 PDF。
        """
        manga_id = item.manga_id
        operation_task_id = item.operation_task_id
        operation_context = item.context
        temp_download_dir = None
        try:
            # 若任务已被取消（排队期间被 -c 取消），直接跳过不执行下载
            if manga_id in self.cancelled_downloads:
                del self.cancelled_downloads[manga_id]
                if manga_id in self.queued_tasks:
                    del self.queued_tasks[manga_id]
                self.logger.info(f"漫画ID {manga_id} 的下载任务已被取消，跳过")
                return

            if manga_id in self.queued_tasks:
                del self.queued_tasks[manga_id]
            self.downloading_mangas[manga_id] = True
            if self.operation_task_service is not None and operation_task_id:
                self.operation_task_service.start(operation_task_id, "downloading")

            self.logger.info(f"开始下载漫画ID: {manga_id}")
            # option.yml 缺失时回退到 jmcomic 默认配置，避免下载全线失败
            try:
                option = jmcomic.create_option_by_file("option.yml")
            except FileNotFoundError:
                self.logger.warning("option.yml 不存在，使用 jmcomic 默认配置")
                option = jmcomic.JmOption.default()
            download_path = str(self.config["MANGA_DOWNLOAD_PATH"])
            temp_download_dir = os.path.join(download_path, "temp")
            os.makedirs(temp_download_dir, exist_ok=True)

            # 获取 album 元数据 → 章节列表（已按 photo_index 排序）
            client = option.new_jm_client()
            album = client.get_album_detail(manga_id)
            episode_list = album.episode_list
            album_name = album.name
            album_author = ",".join(getattr(album, "authors", []))
            album_tags = ",".join(getattr(album, "tags", []))
            chapter_count = len(episode_list)

            # 配置下载目录规则：临时目录下按 漫画ID/章节序号 组织图片目录，
            # 供 img2pdf 插件在 after_album 阶段逐章收集图片合并为单个 PDF
            safe_title = sanitize_filename(album_name)
            option.dir_rule = DirRule("Bd/{Aid}/{Pindex}", base_dir=temp_download_dir)

            # 注入 img2pdf 插件：filename_rule 与 pdf_dir 始终由代码覆盖，
            # 确保 PDF 文件名使用真实章节数、输出到 MANGA_DOWNLOAD_PATH 指定目录
            inject_img2pdf_plugin(
                option, manga_id, safe_title, chapter_count, download_path
            )

            after_init = option.plugins.get("after_init") or []
            if not any(p.get("plugin") == "download_progress" for p in after_init):
                log_file = os.path.join("logs", "jmcomic-download.log")
                option.plugins["after_init"] = after_init + [
                    build_progress_plugin_config(log_file)
                ]
                # create_option_by_file 已执行过 after_init 插件组，此处手动触发补充注入的插件
                option.call_all_plugin("after_init", safe=True)

            # 整本下载，完成后自动触发 img2pdf 插件合并 PDF（含删除原图）
            result = jmcomic.download_album(manga_id, option=option)
            if isinstance(result, set):
                raise RuntimeError(f"漫画 {manga_id} 批量下载返回了集合，不符合预期")

            if self._stop_event.is_set():
                self.logger.info(
                    f"程序正在关闭，漫画 {manga_id} 下载结果不再入库或发送"
                )
                return

            # 从下载清单获取实际生成的 PDF 路径与实际成功下载的图片数
            pdf_paths = result.manifest.get_export_filepath_list("pdf")
            if not pdf_paths:
                raise RuntimeError(f"漫画 {manga_id} 下载完成但未生成PDF文件")
            pdf_path = pdf_paths[0]
            total_pages = len(result.manifest.image_filepath_list)

            # 持久化漫画元数据：首次下载时写入漫画记录与 PDF 文件记录
            if self.manga_repo is not None:
                try:
                    self.manga_repo.upsert(
                        manga_id=manga_id,
                        title=album_name,
                        author=album_author,
                        chapter_count=chapter_count,
                        page_count=total_pages,
                    )
                    self.manga_repo.add_file(
                        manga_id=manga_id,
                        file_path=pdf_path,
                        page_count=total_pages,
                    )
                except Exception as e:  # pylint: disable=broad-exception-caught
                    self.logger.error(f"持久化漫画元数据失败: {e}")
            if self.tag_repo is not None:
                try:
                    self._sync_tags_to_db(manga_id, album_tags)
                except Exception as e:  # pylint: disable=broad-exception-caught
                    self.logger.error(f"同步漫画标签失败: {e}")
            if self.task_log_repo is not None and item.context.source == "qq":
                # TaskLog 只保留 QQ 来源的历史记录，Web 来源以操作任务与审计为准
                try:
                    self.task_log_repo.add(
                        task_type="download",
                        status="success",
                        manga_id=manga_id,
                        user_id=item.context.actor_user_id or "",
                        group_id=item.context.actor_group_id or "",
                        private=item.context.actor_group_id is None,
                        message=f"标题: {album_name}, 共{total_pages}页",
                    )
                except Exception as e:  # pylint: disable=broad-exception-caught
                    self.logger.error(f"记录下载任务日志失败: {e}")

            # 生成响应消息；通知器为空表示 Web/系统来源，只记录状态不发送 QQ 消息
            chapter_info = f"（{chapter_count} 个章节）" if chapter_count > 1 else ""
            # 低内存模式：QQ 有文件发送器或 Web 静默来源都按模式延迟删除文件
            low_memory_delivery = item.notifier is None or self.file_sender is not None
            if self.low_memory_mode and low_memory_delivery:
                delete_delay = self.low_memory_delete_delay
                response = (
                    f"✅ദ്ദി˶>ω<)✧ "
                    f"漫画ID {manga_id}{chapter_info} 下载完成！\n\n"
                    f"成功生成PDF文件（共{total_pages}页）\n"
                    f"⚠️ 低占用模式：文件将在{delete_delay}分钟后自动删除"
                )
                if item.notifier is not None:
                    try:
                        item.notifier.file(pdf_path)
                        self.logger.info(
                            f"低占用模式：已自动发送PDF文件: "
                            f"{os.path.basename(pdf_path)}"
                        )
                    # 此边界记录发送失败并继续完成下载任务。
                    # pylint: disable-next=broad-exception-caught
                    except Exception as send_error:
                        self.logger.error(f"发送PDF文件失败: {send_error}")
                else:
                    self.logger.info(
                        f"低占用模式：Web 来源下载 {manga_id} 不发送 QQ 文件"
                    )
                self._schedule_file_deletion(pdf_path, delete_delay)
            else:
                response = (
                    f"✅ദ്ദി˶>ω<)✧ "
                    f"漫画ID {manga_id}{chapter_info} 下载并转换为PDF完成！\n\n"
                    f"成功生成PDF文件（共{total_pages}页）\n"
                    f"友情提示：输入'发送 {manga_id}'可以将PDF发送给您"
                )

            if item.notifier is not None:
                item.notifier.message(response)
            if self.operation_task_service is not None and operation_task_id:
                self.operation_task_service.succeed(
                    operation_task_id,
                    metadata={"page_count": total_pages},
                    context=operation_context,
                )

        except Exception as e:  # pylint: disable=broad-exception-caught
            self.logger.error(f"下载漫画出错: {e}")
            if self.operation_task_service is not None and operation_task_id:
                self.operation_task_service.fail(
                    operation_task_id,
                    error_code="download_failed",
                    error_message=type(e).__name__,
                    context=operation_context,
                )
            if self.task_log_repo is not None and item.context.source == "qq":
                try:
                    self.task_log_repo.add(
                        task_type="download",
                        status="failed",
                        manga_id=manga_id,
                        user_id=item.context.actor_user_id or "",
                        group_id=item.context.actor_group_id or "",
                        private=item.context.actor_group_id is None,
                        message=str(e),
                    )
                except Exception as log_error:  # pylint: disable=broad-exception-caught
                    self.logger.error(f"记录下载失败日志出错: {log_error}")
            error_msg = f"❌ 下载失败：{str(e)}\n\n快让主人帮我检查一下∑(O_O；)"
            if item.notifier is not None:
                item.notifier.message(error_msg)
        finally:
            if manga_id in self.downloading_mangas:
                del self.downloading_mangas[manga_id]
            self.operation_task_ids.pop(manga_id, None)
            if temp_download_dir is not None:
                shutil.rmtree(temp_download_dir, ignore_errors=True)

    def _sync_tags_to_db(self, manga_id: str, tags: str) -> None:
        """将漫画标签同步到标签表

        Args:
            manga_id: 漫画ID
            tags: 逗号分隔的标签字符串
        """
        if self.tag_repo is None or not tags:
            return

        for tag in tags.split(","):
            tag = tag.strip()
            if tag:
                self.tag_repo.add_for_existing_manga(tag, manga_id)

    def download_manga(
        self,
        user_id: str,
        manga_id: str,
        group_id: Optional[str],
        private: bool,
        operation_context: Optional[OperationContext] = None,
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

        Raises:
            RuntimeError: 下载队列已经停止时
        """
        context = operation_context or OperationContext.qq(user_id, group_id)
        notifier = QQDownloadNotifier(
            message_sender=self.message_sender,
            file_sender=self.file_sender,
            user_id=user_id,
            group_id=group_id,
            private=private,
        )
        result = self.request_download(manga_id, context, notifier)
        if result.status == "duplicate":
            self.logger.info(f"漫画ID {manga_id} 已存在活动下载任务")

    def request_download(
        self,
        manga_id: str,
        context: OperationContext,
        notifier: Optional[DownloadNotifier],
    ) -> DownloadRequestItem:
        """请求下载单个漫画并入队，重复请求返回既有活动任务状态。

        Args:
            manga_id: 漫画ID
            context: 操作来源上下文，贯穿任务与审计
            notifier: 下载过程通知器，Web/系统来源传 None 表示静默

        Returns:
            DownloadRequestItem: 入队结果（queued 或 duplicate）

        Raises:
            RuntimeError: 下载队列已经停止时
        """
        with self._queue_state_lock:
            if not self.queue_running:
                raise RuntimeError("下载队列已停止")
            if manga_id in self.queued_tasks or manga_id in self.downloading_mangas:
                self.logger.info(f"漫画ID {manga_id} 已存在活动下载任务")
                return DownloadRequestItem(
                    manga_id=manga_id,
                    status="duplicate",
                    task_id=self.operation_task_ids.get(manga_id),
                )
            operation_task_id = None
            if self.operation_task_service is not None:
                operation_task = self.operation_task_service.create(
                    task_type="download",
                    context=context,
                    manga_id=manga_id,
                )
                operation_task_id = operation_task.id
                self.operation_task_ids[manga_id] = operation_task.id
            item = DownloadQueueItem(
                manga_id=manga_id,
                context=context,
                operation_task_id=operation_task_id,
                notifier=notifier,
            )
            self.queued_tasks[manga_id] = item
            self.download_queue.put(item)
        self.logger.info(f"漫画ID {manga_id} 的下载任务已添加到队列")
        return DownloadRequestItem(
            manga_id=manga_id,
            status="queued",
            task_id=operation_task_id,
        )

    def find_active_download(self, manga_id: str) -> Optional[str]:
        """返回内存中排队或下载中任务的 ID，无活动任务时返回 None。"""
        if not self.is_download_active(manga_id):
            return None
        return self.operation_task_ids.get(manga_id)

    def update_low_memory_settings(self, delete_delay: Optional[int] = None) -> None:
        """由 SettingsService 调用，显式更新低内存模式文件删除延迟（分钟）。"""
        if delete_delay is not None:
            if delete_delay < 1:
                raise ValueError("低内存模式删除延迟必须至少为 1 分钟")
            self.low_memory_delete_delay = delete_delay
            self.config["LOW_MEMORY_DELETE_DELAY"] = delete_delay
            self.logger.info(f"低内存模式删除延迟已更新为 {delete_delay} 分钟")

    def cancel_download(self, manga_id: str) -> bool:
        """取消指定漫画的下载任务（仅对排队中尚未开始的任务生效）

        Args:
            manga_id: 漫画ID

        Returns:
            bool: 是否确实取消了排队中的任务
        """
        if manga_id in self.downloading_mangas:
            self.logger.info(f"漫画ID {manga_id} 正在下载中，无法取消")
            return False

        self.cancelled_downloads[manga_id] = True
        if manga_id in self.queued_tasks:
            del self.queued_tasks[manga_id]
            self.logger.info(f"漫画ID {manga_id} 的下载任务已取消")
            operation_task_id = self.operation_task_ids.pop(manga_id, None)
            if self.operation_task_service is not None and operation_task_id:
                self.operation_task_service.cancel(operation_task_id)
            return True

        self.logger.info(f"漫画ID {manga_id} 不在下载队列中，无需取消")
        return False

    def is_download_active(self, manga_id: str) -> bool:
        """返回指定漫画是否存在排队或运行中的下载任务。"""
        return manga_id in self.queued_tasks or manga_id in self.downloading_mangas

    def cancel_all_downloads(self) -> int:
        """取消所有排队中尚未开始的下载任务

        Returns:
            int: 实际取消的任务数量
        """
        cancelled_ids = [
            manga_id
            for manga_id in self.queued_tasks
            if manga_id not in self.downloading_mangas
        ]
        for manga_id in cancelled_ids:
            self.cancelled_downloads[manga_id] = True
            del self.queued_tasks[manga_id]
            operation_task_id = self.operation_task_ids.pop(manga_id, None)
            if self.operation_task_service is not None and operation_task_id:
                self.operation_task_service.cancel(operation_task_id)
            self.logger.info(f"漫画ID {manga_id} 的下载任务已取消")
        return len(cancelled_ids)
