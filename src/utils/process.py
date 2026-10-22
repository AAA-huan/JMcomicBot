"""进程级工具：重启当前进程。

抽出独立函数便于在 main 中调用与单测 monkeypatch os.execv。
"""

from typing import List, Mapping, Optional

import os
import sys


def restart_process(
    executable: str = "",
    argv: List[str] | None = None,
    env: Optional[Mapping[str, str]] = None,
) -> None:
    """用新进程替换当前进程，原进程立即终止。

    Args:
        executable: 解释器路径，缺省取 sys.executable
        argv: 传给新进程的完整参数列表（含 argv[0]，惯例与 os.execv 一致），
              缺省构造 [sys.executable, *sys.argv]
        env: 传给新进程的完整环境变量；缺省继承当前进程环境

    Raises:
        OSError: execv / execve 失败时直接暴露，由调用方记录并返回非零退出码
    """
    target_executable = executable or sys.executable
    if argv is None:
        target_argv = [sys.executable, *sys.argv]
    else:
        target_argv = list(argv)
    if env is None:
        os.execv(target_executable, target_argv)
    else:
        os.execve(target_executable, target_argv, dict(env))
