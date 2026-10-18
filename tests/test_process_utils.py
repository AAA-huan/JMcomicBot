"""restart_process 工具函数测试：验证 os.execv 调用参数。

语义：argv 是传给新进程的完整参数列表（含 argv[0]），函数直接传给 os.execv，
不在内部额外加前缀——调用方负责构造正确的 argv（惯例 argv[0]=executable）。
"""

import sys

from src.utils.process import restart_process


def test_restart_process_calls_execv_with_provided_args(monkeypatch) -> None:
    """显式传入 executable 与 argv 时按原样调用 os.execv。"""
    calls = []

    def fake_execv(executable, argv):
        calls.append((executable, argv))

    monkeypatch.setattr("os.execv", fake_execv)
    # argv 是完整列表，argv[0] 惯例为程序名
    restart_process("/usr/bin/python3", ["/usr/bin/python3", "main.py", "--flag"])

    assert calls == [("/usr/bin/python3", ["/usr/bin/python3", "main.py", "--flag"])]


def test_restart_process_defaults_to_sys_executable_and_argv(monkeypatch) -> None:
    """缺省参数时构造 [sys.executable, *sys.argv] 作为完整 argv。"""
    calls = []

    def fake_execv(executable, argv):
        calls.append((executable, argv))

    monkeypatch.setattr("os.execv", fake_execv)
    monkeypatch.setattr(sys, "executable", "/default/python")
    monkeypatch.setattr(sys, "argv", ["main.py"])
    restart_process()

    # argv[0]=executable（程序名占位），argv[1]="main.py"（脚本路径）
    assert calls == [("/default/python", ["/default/python", "main.py"])]


def test_restart_process_propagates_oserror(monkeypatch) -> None:
    """execv 失败时直接暴露 OSError，不兜底。"""
    import pytest

    def fake_execv(_executable, _argv):
        raise OSError("exec failed")

    monkeypatch.setattr("os.execv", fake_execv)

    with pytest.raises(OSError, match="exec failed"):
        restart_process("/usr/bin/python3", ["/usr/bin/python3"])
