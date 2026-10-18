"""restart_process 工具函数测试：验证 os.execv 调用参数。"""

from src.utils.process import restart_process


def test_restart_process_calls_execv_with_provided_args(monkeypatch) -> None:
    """显式传入 executable 与 argv 时按原样调用 os.execv。"""
    calls = []

    def fake_execv(executable, argv):
        calls.append((executable, argv))

    monkeypatch.setattr("os.execv", fake_execv)
    restart_process("/usr/bin/python3", ["python3", "main.py", "--flag"])

    assert calls == [
        ("/usr/bin/python3", ["/usr/bin/python3", "python3", "main.py", "--flag"])
    ]


def test_restart_process_defaults_to_sys_executable_and_argv(monkeypatch) -> None:
    """缺省参数时使用 sys.executable 与 sys.argv。"""
    import sys

    calls = []

    def fake_execv(executable, argv):
        calls.append((executable, argv))

    monkeypatch.setattr("os.execv", fake_execv)
    monkeypatch.setattr(sys, "executable", "/default/python")
    monkeypatch.setattr(sys, "argv", ["main.py"])
    restart_process()

    assert calls == [("/default/python", ["/default/python", "main.py"])]


def test_restart_process_propagates_oserror(monkeypatch) -> None:
    """execv 失败时直接暴露 OSError，不兜底。"""

    def fake_execv(_executable, _argv):
        raise OSError("exec failed")

    monkeypatch.setattr("os.execv", fake_execv)
    import pytest

    with pytest.raises(OSError, match="exec failed"):
        restart_process("/usr/bin/python3", ["python3"])
