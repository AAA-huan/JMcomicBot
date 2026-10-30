"""中断下载恢复询问协调器测试。"""

import pytest

from src.service.recovery_prompt import RecoveryPrompt


def test_resolve_is_idempotent_and_wakes_waiter() -> None:
    """任一渠道先给出的决定生效，重复提交返回 False。"""
    prompt = RecoveryPrompt(task_count=3, timeout_seconds=180)

    assert prompt.is_pending() is True
    assert prompt.resolve("continue") is True
    assert prompt.resolve("cancel") is False
    assert prompt.decision == "continue"
    assert prompt.wait() == "continue"
    assert prompt.is_pending() is False
    assert prompt.remaining_seconds() == 0


def test_timeout_defaults_to_cancel() -> None:
    """无人操作时等待超时，默认取消恢复。"""
    prompt = RecoveryPrompt(task_count=2, timeout_seconds=0)

    assert prompt.wait() == "cancel"
    assert prompt.decision == "cancel"
    assert prompt.is_pending() is False
    # 超时后的迟到决定不再生效
    assert prompt.resolve("continue") is False
    assert prompt.decision == "cancel"


def test_remaining_seconds_counts_down(monkeypatch) -> None:
    """剩余秒数按单调时钟递减并向上取整。"""
    now = [100.0]
    monkeypatch.setattr("src.service.recovery_prompt.monotonic", lambda: now[0])
    prompt = RecoveryPrompt(task_count=1, timeout_seconds=10)
    assert prompt.remaining_seconds() == 10

    now[0] += 2.5
    assert prompt.remaining_seconds() == 8
    assert prompt.is_pending() is True

    now[0] += 8
    assert prompt.remaining_seconds() == 0
    assert prompt.is_pending() is False


def test_rejects_unknown_action() -> None:
    """非法动作明确报错，不污染已有决定。"""
    prompt = RecoveryPrompt(task_count=1, timeout_seconds=10)

    with pytest.raises(ValueError, match="不支持的恢复动作"):
        prompt.resolve("retry")

    assert prompt.decision is None
    assert prompt.is_pending() is True
