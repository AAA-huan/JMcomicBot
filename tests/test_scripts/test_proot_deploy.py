"""验证 proot 隔离和托管 Python，不执行安装或联网。"""

from pathlib import Path

import subprocess

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def run_proot(body: str) -> subprocess.CompletedProcess:
    """加载函数，用 shell 替身模拟 uv。"""
    return subprocess.run(
        [
            "bash",
            "-c",
            'source "$1/scripts/deploy-proot.sh"\n' + body,
            "proot-test",
            str(PROJECT_ROOT),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_proot_clears_host_environment() -> None:
    result = run_proot("""
export PREFIX=/data/data/com.termux/files/usr
export PYTHONPATH=/termux/python VIRTUAL_ENV=/termux/venv
export UV_NO_MANAGED_PYTHON=1 UV_PYTHON=/termux/python
prepare_proot_environment
[[ "$PATH" != *com.termux* && "$UV_PYTHON" == 3.12 && "$UV_MANAGED_PYTHON" == 1 ]]
[[ -z ${PREFIX+x} && -z ${PYTHONPATH+x} && -z ${VIRTUAL_ENV+x} && -z ${UV_NO_MANAGED_PYTHON+x} ]]
""")
    assert result.returncode == 0, result.stderr


def test_proot_installs_missing_managed_python() -> None:
    result = run_proot("""
load_deployment_functions
configure_proot_functions
installed=0
uv() {
    echo "$*" >&2
    if [[ "$*" == "python find --managed-python --no-project --no-python-downloads 3.12" ]]; then
        [[ $installed == 1 ]] || return 1
        echo /bin/true
    elif [[ "$*" == "python install 3.12" ]]; then
        installed=1
    else
        return 99
    fi
}
ensure_python
""")
    assert result.returncode == 0, result.stderr
    assert "python install 3.12" in result.stderr


def test_proot_install_failure_stops_deployment() -> None:
    """托管 Python 安装失败必须暴露错误，不能使用宿主 Python。"""
    result = run_proot("""
load_deployment_functions
configure_proot_functions
uv() { return 1; }
ensure_python
echo SHOULD_NOT_RUN
""")
    assert result.returncode != 0
    assert "uv 托管 Python 安装失败" in result.stderr
    assert "SHOULD_NOT_RUN" not in result.stdout
