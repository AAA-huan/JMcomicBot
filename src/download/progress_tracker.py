"""下载进度追踪器，替换 jmcomic EXECUTOR_LOG 实现控制台进度条"""

import re
import sys
import threading
import time
from typing import Any, Callable, Optional


class ProgressTracker:
    """下载进度追踪器

    通过替换 jmcomic 的 JmModuleConfig.EXECUTOR_LOG 拦截所有日志回调，
    将低频有用信息记入项目日志，用高频的 image.after 事件驱动控制台进度条。
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
        self._downloaded_images: int = 0
        self._failed_images: int = 0
        self._start_time: float = 0.0
        self._active: bool = False
        self._progress_bar_drawn: bool = False

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
            self._start_time = time.time()
            self._active = True
            self._clear_progress_bar()
        self._logger.info(
            f"本子获取成功: {self._manga_id}, "
            f"标题: [{self._album_name}], "
            f"{self._total_chapters}章{self._total_images}页"
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
            self._clear_progress_bar()
        self._logger.info(
            f"开始下载章节: {self._current_chapter}/{self._total_chapters} "
            f"[{self._chapter_name}] {chapter_images}张图"
        )

    def _on_photo_after(self, msg: str) -> None:
        match = self._photo_after_pattern.search(msg)
        if not match:
            return
        with self._lock:
            self._clear_progress_bar()
        self._logger.info(f"章节下载完成: {match.group(2)}/{match.group(3)}")

    def _on_image_after(self) -> None:
        with self._lock:
            self._downloaded_images += 1
            self._draw_progress_bar()

    def _on_image_failed(self, msg: str) -> None:
        match = self._image_failed_pattern.search(msg)
        image_id = match.group(1) if match else "unknown"
        with self._lock:
            self._failed_images += 1
            self._clear_progress_bar()
        self._logger.warning(
            f"图片下载失败: {image_id} " f"(累计{self._failed_images}张)"
        )

    def _clear_progress_bar(self) -> None:
        if not self._active or not self._progress_bar_drawn:
            return
        sys.stdout.write("\r\033[K")
        sys.stdout.flush()
        self._progress_bar_drawn = False

    def _draw_progress_bar(self) -> None:
        if not self._active or self._total_images == 0:
            return

        pct = self._downloaded_images / self._total_images * 100
        bar_len = 16
        filled = int(bar_len * pct / 100)
        bar_chars = "█" * filled + "░" * (bar_len - filled)

        elapsed = int(time.time() - self._start_time)
        elapsed_str = f"{elapsed // 60}:{elapsed % 60:02d}"

        text = (
            f"{self._manga_id} [{bar_chars}] {pct:.1f}% "
            f"章节 {self._current_chapter}/{self._total_chapters} "
            f"图片 {self._downloaded_images}/{self._total_images} "
            f"{elapsed_str}"
        )
        if self._failed_images > 0:
            text += f" \u26a0 {self._failed_images}张失败"

        sys.stdout.write("\r\033[K" + text)
        sys.stdout.flush()
        self._progress_bar_drawn = True

    def finish(self) -> None:
        """下载完成后清理进度条并记录完成日志"""
        with self._lock:
            self._active = False
            self._clear_progress_bar()
        self._logger.info(
            f"下载完成: {self._manga_id}, "
            f"共{self._total_chapters}章{self._downloaded_images}页"
            + (f", {self._failed_images}张失败" if self._failed_images > 0 else "")
        )
