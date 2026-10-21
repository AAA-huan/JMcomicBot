"""下载进度采集：线程安全地汇总本子/章节进度并发布 Web 事件。"""

from dataclasses import asdict, dataclass
from datetime import datetime
from threading import Lock
from time import monotonic
from typing import Any, Callable, Dict, List, Optional

from jmcomic import ProgressDownloader

from src.database.models import utc_now

ProgressPublisher = Callable[[str, Dict[str, Any]], None]
ChapterFinishedCallback = Callable[[int], None]


@dataclass(frozen=True)
class ChapterProgress:
    """单个章节的图片下载进度。"""

    photo_id: str
    done: int
    total: int
    finished: bool


@dataclass(frozen=True)
class DownloadProgressSnapshot:
    """一次漫画下载的不可变进度快照，可直接序列化为 Web 事件与 REST 响应。"""

    manga_id: str
    task_id: Optional[str]
    album_id: str
    album_total: int
    album_done: int
    chapters: List[ChapterProgress]
    started_at: datetime
    updated_at: datetime
    finished: bool
    succeeded: bool

    def to_dict(self) -> Dict[str, Any]:
        """转为 JSON 可序列化字典，时间统一为 UTC ISO8601。"""
        data = asdict(self)
        data["started_at"] = self.started_at.isoformat()
        data["updated_at"] = self.updated_at.isoformat()
        return data


@dataclass
class _ChapterState:
    """采集线程内部使用的可变章节状态。"""

    total: int
    done: int = 0
    finished: bool = False


@dataclass
class _ProgressState:
    """采集线程内部使用的可变下载状态。"""

    manga_id: str
    task_id: Optional[str]
    album_id: str
    album_total: int
    chapters: Dict[str, _ChapterState]
    started_at: datetime
    updated_at: datetime
    finished: bool = False
    succeeded: bool = False


class DownloadProgressTracker:
    """汇总 jmcomic 下载钩子产生的进度。

    图片下载由 jmcomic 的线程池并发执行，因此所有状态读写都由同一把锁
    保护。图片级事件按 ``throttle_seconds`` 节流；下载开始、章节开始、
    章节完成与下载结束事件立即推送。发布回调会在持锁期间调用，回调必须
    保持轻量且不得反向调用本对象，避免死锁。
    """

    def __init__(
        self,
        publish: Optional[ProgressPublisher] = None,
        throttle_seconds: float = 0.5,
        monotonic_clock: Callable[[], float] = monotonic,
    ) -> None:
        if throttle_seconds < 0:
            raise ValueError("进度事件节流时间不能为负数")
        self._publish = publish
        self._throttle_seconds = throttle_seconds
        self._monotonic_clock = monotonic_clock
        self._lock = Lock()
        self._state: Optional[_ProgressState] = None
        self._context: Optional[
            tuple[str, Optional[str], Optional[ChapterFinishedCallback]]
        ] = None
        self._last_publish_at = float("-inf")

    def begin(
        self,
        manga_id: str,
        task_id: Optional[str],
        on_chapter_finished: Optional[ChapterFinishedCallback] = None,
    ) -> None:
        """绑定下一次下载的漫画、任务与章节完成回调。

        真正的进度快照在 jmcomic 触发 ``start_progress`` 时创建，因此获取
        本子元数据期间不会提前展示进度。
        """
        with self._lock:
            self._context = (manga_id, task_id, on_chapter_finished)

    def start(self, album_id: str, album_total: int) -> None:
        """创建新快照并立即发布 ``started`` 事件。"""
        if album_total < 0:
            raise ValueError("章节总数不能为负数")
        with self._lock:
            if self._context is None:
                raise RuntimeError("下载进度采集尚未绑定漫画与任务上下文")
            manga_id, task_id, _ = self._context
            now = utc_now()
            self._state = _ProgressState(
                manga_id=manga_id,
                task_id=task_id,
                album_id=album_id,
                album_total=album_total,
                chapters={},
                started_at=now,
                updated_at=now,
            )
            self._last_publish_at = float("-inf")
            self._publish_locked("started")

    def chapter_started(self, photo_id: str, total: int) -> None:
        """登记新章节并立即发布进度事件。"""
        if total < 0:
            raise ValueError("章节图片总数不能为负数")
        with self._lock:
            if self._state is None or self._state.finished:
                return
            self._state.chapters[photo_id] = _ChapterState(total=total)
            self._state.updated_at = utc_now()
            self._last_publish_at = self._monotonic_clock()
            self._publish_locked("progress")

    def image_done(self, photo_id: str) -> None:
        """记录一张图片下载完成；高频事件按节流间隔合并。"""
        with self._lock:
            state = self._state
            if state is None or state.finished:
                return
            chapter = state.chapters.get(photo_id)
            if chapter is None:
                return
            if chapter.done < chapter.total:
                chapter.done += 1
            state.updated_at = utc_now()
            current = self._monotonic_clock()
            if current - self._last_publish_at >= self._throttle_seconds:
                self._last_publish_at = current
                self._publish_locked("progress")

    def chapter_finished(self, photo_id: str) -> None:
        """标记章节结束、立即推送，并通知已完成章节百分比。"""
        callback: Optional[ChapterFinishedCallback] = None
        percent = 0
        with self._lock:
            state = self._state
            if state is None or state.finished:
                return
            chapter = state.chapters.get(photo_id)
            if chapter is None:
                return
            chapter.finished = chapter.done == chapter.total
            state.updated_at = utc_now()
            self._last_publish_at = self._monotonic_clock()
            album_done = self._album_done_locked()
            if state.album_total > 0:
                percent = min(100, round(album_done * 100 / state.album_total))
            if self._context is not None:
                callback = self._context[2]
            self._publish_locked("progress")
        # 数据库写入放在锁外，避免阻塞并发图片线程
        if callback is not None:
            callback(percent)

    def flush(self) -> None:
        """立即推送当前进度，不改变完成状态；用于下载器停止时补齐末次进度。"""
        with self._lock:
            if self._state is None or self._state.finished:
                return
            self._state.updated_at = utc_now()
            self._last_publish_at = self._monotonic_clock()
            self._publish_locked("progress")

    def finish(self, succeeded: Optional[bool] = None) -> None:
        """结束当前快照并立即发布 ``finished`` 事件。

        ``succeeded`` 为空时根据章节完成情况推断；重复调用不会重复发布。
        """
        with self._lock:
            state = self._state
            if state is None or state.finished:
                return
            state.finished = True
            state.succeeded = (
                self._is_complete_locked() if succeeded is None else succeeded
            )
            state.updated_at = utc_now()
            self._publish_locked("finished")

    def snapshot(self) -> Optional[DownloadProgressSnapshot]:
        """返回当前或最近一次下载的快照；从未开始时返回 None。"""
        with self._lock:
            return self._snapshot_locked()

    def _publish_locked(self, phase: str) -> None:
        """在持锁状态下构造快照并调用发布回调。"""
        if self._publish is None:
            return
        snapshot = self._snapshot_locked()
        if snapshot is None:
            return
        self._publish(
            "download.progress",
            {**snapshot.to_dict(), "phase": phase},
        )

    def _snapshot_locked(self) -> Optional[DownloadProgressSnapshot]:
        """由内部可变状态生成不可变快照。"""
        state = self._state
        if state is None:
            return None
        chapters = [
            ChapterProgress(
                photo_id=photo_id,
                done=chapter.done,
                total=chapter.total,
                finished=chapter.finished,
            )
            for photo_id, chapter in state.chapters.items()
        ]
        return DownloadProgressSnapshot(
            manga_id=state.manga_id,
            task_id=state.task_id,
            album_id=state.album_id,
            album_total=state.album_total,
            album_done=self._album_done_locked(),
            chapters=chapters,
            started_at=state.started_at,
            updated_at=state.updated_at,
            finished=state.finished,
            succeeded=state.succeeded,
        )

    def _album_done_locked(self) -> int:
        """统计已完成章节数。"""
        if self._state is None:
            return 0
        return sum(1 for chapter in self._state.chapters.values() if chapter.finished)

    def _is_complete_locked(self) -> bool:
        """判断当前快照是否所有章节和图片均已完成。"""
        state = self._state
        if state is None or state.album_total <= 0:
            return False
        return self._album_done_locked() == state.album_total and all(
            chapter.finished for chapter in state.chapters.values()
        )


class WebProgressDownloader(ProgressDownloader):
    """在 jmcomic 原生进度下载器之上登记 WebUI 进度。

    必须由 ``DownloadManager`` 在 option 插件执行完成后调用 ``use()``，
    以替换插件安装的 ``ProgressDownloader``。所有覆写方法先执行父类逻辑，
    保持终端进度展示与原有下载行为不变。
    """

    progress_tracker: Optional[DownloadProgressTracker] = None

    @classmethod
    def configure(cls, tracker: Optional[DownloadProgressTracker]) -> None:
        """设置当前下载使用的进度采集器。"""
        cls.progress_tracker = tracker

    def start_progress(
        self, album_total: Optional[int] = None, album_id: Any = None
    ) -> None:
        """父类创建本子级进度后，创建 WebUI 快照。"""
        super().start_progress(album_total, album_id)
        tracker = self.progress_tracker
        # 单章节详情下载没有本子级总数，本应用只走整本下载，直接跳过
        if tracker is None or album_total is None or album_id is None:
            return
        tracker.start(str(album_id), album_total)

    def before_photo(self, photo: Any) -> None:
        """父类登记章节后，记录章节图片总数。"""
        super().before_photo(photo)
        tracker = self.progress_tracker
        if tracker is not None:
            tracker.chapter_started(str(photo.id), len(photo))

    def after_image(self, image: Any, img_save_path: str) -> None:
        """父类完成单图回调后，累加章节图片进度。"""
        super().after_image(image, img_save_path)
        tracker = self.progress_tracker
        if tracker is not None:
            tracker.image_done(str(image.from_photo.id))

    def after_photo(self, photo: Any) -> None:
        """父类完成章节后，标记章节完成并同步任务进度。"""
        super().after_photo(photo)
        tracker = self.progress_tracker
        if tracker is not None:
            tracker.chapter_finished(str(photo.id))

    def after_album(self, album: Any) -> None:
        """父类完成整本（含 PDF 插件）后，推送下载完成事件。"""
        super().after_album(album)
        tracker = self.progress_tracker
        if tracker is not None:
            tracker.finish()

    def stop_progress(self) -> None:
        """父类停止终端进度后，补齐一次最新 WebUI 进度。"""
        super().stop_progress()
        tracker = self.progress_tracker
        if tracker is not None:
            tracker.flush()
