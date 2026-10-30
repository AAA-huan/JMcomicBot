"""中断下载恢复询问协调器：终端与 WebUI 双渠道，超时默认取消。"""

from math import ceil
from threading import Event, Lock
from time import monotonic
from typing import Optional


class RecoveryPrompt:
    """在多个渠道间共享一次恢复决定，先到先得且只生效一次。"""

    def __init__(self, task_count: int, timeout_seconds: int = 180) -> None:
        self.task_count = task_count
        self.timeout_seconds = timeout_seconds
        self._event = Event()
        self._lock = Lock()
        self._decision: Optional[str] = None
        self._started_at = monotonic()

    @property
    def decision(self) -> Optional[str]:
        """返回已确定的动作；仍在等待时为 None。"""
        with self._lock:
            return self._decision

    def remaining_seconds(self) -> int:
        """返回向上取整的剩余秒数，已决定或超时后为 0。"""
        with self._lock:
            return int(ceil(self._seconds_remaining_locked()))

    def is_pending(self) -> bool:
        """是否仍在等待任一渠道给出决定。"""
        with self._lock:
            return self._decision is None and self._seconds_remaining_locked() > 0

    def resolve(self, action: str) -> bool:
        """设置最终动作；重复提交、非法动作或已超时返回 False。"""
        if action not in ("continue", "cancel"):
            raise ValueError(f"不支持的恢复动作: {action}")
        with self._lock:
            if self._decision is not None:
                return False
            if self._seconds_remaining_locked() <= 0:
                # 超时后迟到的决定不再生效，保持与 wait 的默认取消一致
                self._decision = "cancel"
                return False
            self._decision = action
            self._event.set()
            return True

    def wait(self) -> str:
        """阻塞等待决定或超时，返回最终动作（超时默认 cancel）。"""
        with self._lock:
            if self._decision is not None:
                return self._decision
            remaining = self._seconds_remaining_locked()
        if remaining > 0:
            self._event.wait(remaining)
        with self._lock:
            if self._decision is None:
                self._decision = "cancel"
            return self._decision

    def _seconds_remaining_locked(self) -> float:
        """调用方已持锁时计算精确剩余秒数。"""
        if self._decision is not None:
            return 0.0
        elapsed = monotonic() - self._started_at
        return max(0.0, self.timeout_seconds - elapsed)
