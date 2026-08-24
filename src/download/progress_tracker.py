"""下载进度追踪器，替换 jmcomic EXECUTOR_LOG 实现控制台进度条"""

import re
import sys
import threading
from typing import Any, Callable, Optional

from jmcomic.jm_entity import JmAlbumDetail
from tqdm import tqdm


class ProgressTracker:
    """下载进度追踪器

    通过替换 jmcomic 的 JmModuleConfig.EXECUTOR_LOG 拦截所有日志回调，
    将低频有用信息记入项目日志，用高频的 image.after 事件驱动 tqdm 进度条。
    """

    def __init__(self, logger: Any, manga_id: str) -> None:
        self._logger = logger
        self._manga_id = manga_id
        self._lock = threading.Lock()

        self._album_name: str = ""
        self._total_chapters: int = 0
        self._current_chapter: int = 0
        self._chapter_name: str = ""
        self._total_images: int = 0
        self._album_has_page_count: bool = False
        self._failed_images: int = 0
        self._bar: Optional[tqdm] = None
        self._refresh_stop: threading.Event = threading.Event()
        self._suppress_refresh: bool = False

        self._album_pattern = re.compile(
            r"章节数: \[(\d+)\], 总页数: \[(\d+)\], 标题: \[(.+?)\]"
        )
        self._photo_before_pattern = re.compile(
            r"\((\w+)\[(\d+)/(\d+)\]\), 标题: \[(.+?)\], 图片数为\[(\d+)\]"
        )
        self._photo_after_pattern = re.compile(r"\((\w+)\[(\d+)/(\d+)\]\)")
        self._image_failed_pattern = re.compile(r"图片下载失败: \[(.+?)\]")

    def make_log_handler(self) -> Callable[[str, str, Optional[BaseException]], None]:
        """返回可赋值给 JmModuleConfig.EXECUTOR_LOG 的日志处理函数"""

        def handler(topic: str, msg: str, _e: Optional[BaseException] = None) -> None:
            self._on_log(topic, msg)

        return handler

    def setup_from_album(self, album: JmAlbumDetail) -> None:
        """从 album 元数据设置进度追踪器（不依赖 album.before 事件）

        用于 per-chapter 下载场景（download_photo 不触发 album.before），
        在安装日志处理器前调用，手动设置章节总数、总页数、漫画标题。

        Args:
            album: 从 jmcomic 获取的 album 详情
        """
        with self._lock:
            self._total_chapters = len(album.episode_list)
            self._album_name = album.name
            if album.page_count > 0:
                self._total_images = album.page_count
                self._album_has_page_count = True
        self._logger.info(
            f"本子获取成功: id{self._manga_id}, "
            f"标题: [{self._album_name}], "
            f"{self._total_chapters}章"
        )

    def _on_log(self, topic: str, msg: str) -> None:
        if topic == "album.before":
            self._on_album_before(msg)
        elif topic == "photo.before":
            self._on_photo_before(msg)
        elif topic == "photo.after":
            self._on_photo_after(msg)
        elif topic == "image.after":
            self._on_image_after()
        elif topic == "image.failed":
            self._on_image_failed(msg)

    def _log_separator(self) -> None:
        if self._bar is not None:
            self._suppress_refresh = True
            sys.stdout.write("\n")
            sys.stdout.flush()

    def _init_bar(self, total: int = 0) -> None:
        if total == 0:
            total = self._total_images
        self._bar = tqdm(
            total=total,
            desc=self._manga_id,
            unit="img",
            file=sys.stdout,
            bar_format=("{desc} [{bar}] {percentage:.1f}% " " {postfix} [{elapsed}]"),
        )
        self._bar.clear()
        self._refresh_stop.clear()

        def refresh_loop() -> None:
            while not self._refresh_stop.wait(1):
                with self._lock:
                    if self._bar is not None and not self._suppress_refresh:
                        self._bar.refresh()

        thread = threading.Thread(target=refresh_loop, daemon=True)
        thread.start()

    def _on_album_before(self, msg: str) -> None:
        match = self._album_pattern.search(msg)
        if not match:
            return
        with self._lock:
            self._total_chapters = int(match.group(1))
            page_count = int(match.group(2))
            self._album_has_page_count = page_count > 0
            self._total_images = page_count if page_count > 0 else 0
            self._album_name = match.group(3)
        self._logger.info(
            f"本子获取成功: id{self._manga_id}, "
            f"标题: [{self._album_name}], "
            f"{self._total_chapters}章"
        )

    def _on_photo_before(self, msg: str) -> None:
        match = self._photo_before_pattern.search(msg)
        if not match:
            return
        with self._lock:
            self._current_chapter = int(match.group(2))
            self._chapter_name = match.group(4)
            chapter_images = int(match.group(5))
            if not self._album_has_page_count:
                self._total_images += chapter_images
            if self._bar is None:
                self._init_bar(total=chapter_images)
        self._log_separator()
        self._logger.info(
            f"开始下载章节: {self._current_chapter}/{self._total_chapters} "
            f"[{self._chapter_name}] {chapter_images}张图"
        )

    def _on_photo_after(self, msg: str) -> None:
        match = self._photo_after_pattern.search(msg)
        if not match:
            return
        self._log_separator()
        self._logger.info(f"章节下载完成: {match.group(2)}/{match.group(3)}")
        with self._lock:
            if self._bar is not None:
                self._bar.disable = True
                self._bar.close()
                self._bar = None

    def _on_image_after(self) -> None:
        with self._lock:
            if self._bar is None:
                return
            self._suppress_refresh = False
            self._bar.update(1)
            self._update_bar_postfix()

    def _on_image_failed(self, msg: str) -> None:
        match = self._image_failed_pattern.search(msg)
        image_id = match.group(1) if match else "unknown"
        with self._lock:
            self._failed_images += 1
            self._update_bar_postfix()
        self._log_separator()
        self._logger.warning(f"图片下载失败: {image_id} (累计{self._failed_images}张)")

    def _update_bar_postfix(self) -> None:
        if self._bar is None:
            return
        postfix = (
            f"章节{self._current_chapter}/{self._total_chapters}, "
            f"图片 {self._bar.n}/{self._bar.total}"
        )
        if self._failed_images > 0:
            postfix += f" \u26a0 {self._failed_images}张失败"
        self._bar.set_postfix_str(postfix)

    def finish(self) -> None:
        """下载完成后清理进度条并记录完成日志"""
        self._refresh_stop.set()
        with self._lock:
            if self._bar is not None:
                self._bar.disable = True
                self._bar.close()
                self._bar = None
        self._logger.info(
            f"下载完成: {self._manga_id}, "
            f"共{self._total_chapters}章"
            + (f"{self._total_images}页" if self._total_images > 0 else "")
            + (f", {self._failed_images}张失败" if self._failed_images > 0 else "")
        )
