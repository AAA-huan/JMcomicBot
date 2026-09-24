"""下载管理器模块，负责漫画下载功能并对下载队列进行管理"""

import os
import queue
import shutil
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import jmcomic
from jmcomic.jm_option import DirRule

from src.database.repositories import (
    MangaRepository,
    MangaTagRepository,
    TaskLogRepository,
)
from src.utils.helpers import sanitize_filename


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
        """
        self.logger = logger_instance
        self.config = config
        self.message_sender = message_sender
        self.file_sender = file_sender
        self.manga_repo = manga_repo
        self.task_log_repo = task_log_repo
        self.tag_repo = tag_repo
        self.download_queue: queue.Queue = queue.Queue()
        self.queue_running: bool = True
        self.queued_tasks: Dict[str, Tuple[str, Optional[str], bool]] = {}
        self.downloading_mangas: Dict[str, bool] = {}
        self._start_download_queue_processor()

        # 取消下载任务标记：排队中尚未开始的任务可通过取消标记被跳过
        self.cancelled_downloads: Dict[str, bool] = {}

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
        通过 jmcomic 原生 download_album 整本下载，并注入 img2pdf 插件在下载完成后自动合并为单个 PDF。
        """
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
            album_author = ",".join(getattr(album, "authors", []))
            album_tags = ",".join(getattr(album, "tags", []))
            chapter_count = len(episode_list)

            # 配置下载目录规则：临时目录下按 漫画ID/章节序号 组织图片目录，
            # 供 img2pdf 插件在 after_album 阶段逐章收集图片合并为单个 PDF
            safe_title = sanitize_filename(album_name)
            option.dir_rule = DirRule("Bd/{Aid}/{Pindex}", base_dir=temp_download_dir)

            # 注入插件（若用户已在 option.yml 自定义同名插件则尊重用户配置）
            after_album = option.plugins.get("after_album") or []
            if not any(p.get("plugin") == "img2pdf" for p in after_album):
                option.plugins["after_album"] = after_album + [
                    build_pdf_plugin_config(
                        manga_id, safe_title, chapter_count, download_path
                    )
                ]

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
                        tags=album_tags,
                        chapter_count=chapter_count,
                        page_count=total_pages,
                    )
                    file_size_mb = round(os.path.getsize(pdf_path) / (1024 * 1024), 2)
                    self.manga_repo.add_file(
                        manga_id=manga_id,
                        file_path=pdf_path,
                        file_size_mb=file_size_mb,
                    )
                except Exception as e:
                    self.logger.error(f"持久化漫画元数据失败: {e}")
            if self.tag_repo is not None:
                try:
                    self._sync_tags_to_db(manga_id, album_tags, pdf_path)
                except Exception as e:
                    self.logger.error(f"同步漫画标签失败: {e}")
            if self.task_log_repo is not None:
                try:
                    self.task_log_repo.add(
                        task_type="download",
                        status="success",
                        manga_id=manga_id,
                        user_id=user_id,
                        group_id=group_id or "",
                        private=private,
                        message=f"标题: {album_name}, 共{total_pages}页",
                    )
                except Exception as e:
                    self.logger.error(f"记录下载任务日志失败: {e}")

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
            if self.task_log_repo is not None:
                try:
                    self.task_log_repo.add(
                        task_type="download",
                        status="failed",
                        manga_id=manga_id,
                        user_id=user_id,
                        group_id=group_id or "",
                        private=private,
                        message=str(e),
                    )
                except Exception as log_error:
                    self.logger.error(f"记录下载失败日志出错: {log_error}")
            error_msg = f"❌ 下载失败：{str(e)}\n\n快让主人帮我检查一下∑(O_O；)"
            self.message_sender(user_id, error_msg, group_id, private)
        finally:
            if manga_id in self.downloading_mangas:
                del self.downloading_mangas[manga_id]
            if temp_download_dir is not None:
                shutil.rmtree(temp_download_dir, ignore_errors=True)

    def _sync_tags_to_db(self, manga_id: str, tags: str, pdf_path: str) -> None:
        """将漫画标签及其PDF文件名同步到标签表

        Args:
            manga_id: 漫画ID
            tags: 逗号分隔的标签字符串
            pdf_path: PDF文件路径
        """
        if self.tag_repo is None or not tags:
            return

        pdf_name = os.path.basename(pdf_path)
        for tag in tags.split(","):
            tag = tag.strip()
            if tag:
                self.tag_repo.add(tag, manga_id, pdf_name)

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
            return True

        self.logger.info(f"漫画ID {manga_id} 不在下载队列中，无需取消")
        return False

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
            self.logger.info(f"漫画ID {manga_id} 的下载任务已取消")
        return len(cancelled_ids)

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

            # 同步删除数据库中的漫画元数据与PDF文件记录
            if self.manga_repo is not None:
                try:
                    self.manga_repo.delete(manga_id)
                except Exception as e:
                    self.logger.error(f"删除数据库漫画记录失败: {e}")
            if self.tag_repo is not None:
                try:
                    self.tag_repo.delete_by_manga_id(manga_id)
                except Exception as e:
                    self.logger.error(f"删除漫画标签记录失败: {e}")
            if self.task_log_repo is not None:
                try:
                    self.task_log_repo.add(
                        task_type="delete",
                        status="success",
                        manga_id=manga_id,
                        user_id=user_id,
                        group_id=group_id or "",
                        private=private,
                        message=f"删除{deleted_count}个PDF文件",
                    )
                except Exception as e:
                    self.logger.error(f"记录删除任务日志失败: {e}")

            response = (
                f"✅ദ്ദി˶>ω<)✧ 漫画ID {manga_id} 的{deleted_count}个PDF文件已成功删除！"
            )
            self.message_sender(user_id, response, group_id, private)
        except Exception as e:
            self.logger.error(f"删除漫画PDF文件失败: {e}")
            error_msg = f"❌ 删除失败：{str(e)}\n快让主人帮我检查一下ヽ(ﾟДﾟ)ﾉ"
            self.message_sender(user_id, error_msg, group_id, private)
            raise
