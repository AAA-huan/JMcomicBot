"""进程级工具：重启当前进程。

抽出独立函数便于在 main 中调用与单测 monkeypatch os.execv。
"""

import os
import sys
from typing import List


def restart_process(executable: str = "", argv: List[str] | None = None) -> None:
    """用新进程替换当前进程（os.execv），原进程立即终止。

    Args:
        executable: 解释器路径，缺省取 sys.executable
        argv: 传给新进程的参数列表（含 argv[0]），缺省取当前 sys.argv

    Raises:
        OSError: execv 失败时直接暴露，由调用方记录并返回非零退出码
    """
    target_executable = executable or sys.executable
    target_argv = list(argv) if argv is not None else list(sys.argv)
    os.execv(target_executable, [target_executable, *target_argv])
