"""在隔离目录验证部署函数，不安装软件、不更新项目、不启动机器人。"""

from pathlib import Path
from typing import Callable

import base64
import shutil
import subprocess

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _ps_string(value: str) -> str:
    """将路径或测试输入编码为 PowerShell 单引号字面量。"""
    return "'" + value.replace("'", "''") + "'"


def _windows_path(path: Path) -> str:
    return subprocess.run(
        ["wslpath", "-w", str(path)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.fixture(params=["bash", "powershell"])
def run_script(request, tmp_path: Path) -> Callable:
    """加载脚本函数；Windows PowerShell 通过 WSL 调用并显式传入测试输入。"""
    engine = request.param
    executable = shutil.which("bash" if engine == "bash" else "powershell.exe")
    if executable is None:
        pytest.skip(f"当前环境没有 {engine}")

    def run(bash: str, powershell: str, user_input: str = ""):
        if engine == "bash":
            command = [
                executable,
                "-c",
                'source "$1/scripts/deploy.sh"\n' + bash,
                "deploy-test",
                str(PROJECT_ROOT),
            ]
        else:
            script_path = _ps_string(_windows_path(PROJECT_ROOT / "scripts/deploy.bat"))
            directory = _ps_string(_windows_path(tmp_path))
            source = (
                # 与 .bat 入口一样，按 UTF-8 读取并提取内嵌 PowerShell 部分。
                "$ErrorActionPreference = 'Stop'\n"
                + ". ([scriptblock]::Create(([IO.File]::ReadAllText("
                + script_path
                + ", [Text.Encoding]::UTF8) -split '(?m)^# JMBOT_POWERSHELL_START\\r?$', 2)[1]))\n"
                + "Set-Location "
                + directory
                + "\n[Console]::SetIn([IO.StringReader]::new("
                + _ps_string(user_input)
                + "))\n"
                + powershell
            )
            encoded = base64.b64encode(source.encode("utf-16-le")).decode("ascii")
            command = [executable, "-NoProfile", "-EncodedCommand", encoded]
        return subprocess.run(
            command,
            cwd=tmp_path,
            input=user_input,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=15,
            check=False,
        )

    return run


@pytest.mark.parametrize(
    "value, expected",
    [
        ("3001", "ws://localhost:3001/qq"),
        ("1", "ws://localhost:1/qq"),
        ("65535", "ws://localhost:65535/qq"),
        ("03001", "ws://localhost:3001/qq"),
        (" 3001 ", "ws://localhost:3001/qq"),
        ("ws://example.com:3001/custom", "ws://example.com:3001/custom"),
        ("wss://example.com/qq", "wss://example.com/qq"),
        ("ws://[::1]:3001/qq", "ws://[::1]:3001/qq"),
        ("", "INVALID"),
        ("0", "INVALID"),
        ("65536", "INVALID"),
        ("99999999999999999999", "INVALID"),
        ("ws://localhost:port/qq", "INVALID"),
        ("ws://", "INVALID"),
        ("http://localhost:3001/qq", "INVALID"),
        ("ws://localhost:0/qq", "INVALID"),
        ("ws://localhost:65536/qq", "INVALID"),
        ("ws://localhost:/qq", "INVALID"),
        ("ws://bad host:3001/qq", "INVALID"),
        ("ws://localhost:3001/qq#fragment", "INVALID"),
    ],
)
def test_normalize_ws_url(run_script: Callable, value: str, expected: str):
    """端口转换及非法地址判断在两个平台上保持一致。"""
    # 测试数据不含单引号，可直接作为 Bash 单引号字面量。
    result = run_script(
        f"normalize_ws_url '{value}' || printf 'INVALID'",
        f"$result = Normalize-WsUrl {_ps_string(value)}; "
        "if ($result) { $result } else { 'INVALID' }",
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == expected


@pytest.mark.parametrize(
    "line, expected",
    [
        ('NAPCAT_WS_URL="ws://localhost:port/qq" # 模板', "ws://localhost:port/qq"),
        (" NAPCAT_WS_URL = '3001' # 端口", "3001"),
        ("NAPCAT_WS_URL=3001 # 端口", "3001"),
        ('NAPCAT_WS_URL="value#inside" # 注释', "value#inside"),
    ],
)
def test_get_env(run_script: Callable, tmp_path: Path, line: str, expected: str):
    (tmp_path / ".env").write_text(line + "\n", encoding="utf-8")
    result = run_script("get_env NAPCAT_WS_URL .env", "Get-Env 'NAPCAT_WS_URL' '.env'")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == expected


@pytest.mark.parametrize(
    "current, user_input",
    [
        ("3001", "\n\n\n"),
        ('"ws://localhost:port/qq" # 模板', "0\n65536\n3001\n\n\n\n"),
        ('"ws://localhost:port/qq" # 模板', "\n\n\n\n"),
        ("", "\n\n\n\n"),
        ("ws://localhost:65536/qq", "3001\n\n\n\n"),
        ("ws://localhost:3001/qq", "\n\n\n"),
    ],
)
def test_interactive_config(
    run_script: Callable, tmp_path: Path, current: str, user_input: str
):
    """真实输入和写入流程能够修复旧端口配置、重新询问非法值并保留其他项。"""
    env_file = tmp_path / ".env"
    env_file.write_text(
        f"NAPCAT_WS_URL={current}\nNAPCAT_TOKEN=test-token\n"
        'LOW_MEMORY_MODE="true"\nWEBUI_ENABLED=false\nUNRELATED=keep-me\n',
        encoding="utf-8",
    )
    result = run_script("interactive_config", "Interactive-Config", user_input)
    assert result.returncode == 0, result.stderr
    content = env_file.read_text(encoding="utf-8-sig")
    assert "NAPCAT_WS_URL=ws://localhost:3001/qq" in content
    assert "NAPCAT_TOKEN=test-token" in content
    assert "LOW_MEMORY_MODE=true" in content
    assert "WEBUI_ENABLED=false" in content
    assert "UNRELATED=keep-me" in content


def test_port_recommendation_preserves_custom_port(
    run_script: Callable, tmp_path: Path
):
    """推荐范围不是限制，已有自定义端口不被默认值覆盖。"""
    env_file = tmp_path / ".env"
    env_file.write_text("NAPCAT_WS_URL=ws://localhost:9001/qq\n", encoding="utf-8")
    result = run_script("interactive_config", "Interactive-Config", "\n\n\n")
    assert result.returncode == 0, result.stderr
    assert "NAPCAT_WS_URL=ws://localhost:9001/qq" in env_file.read_text(
        encoding="utf-8-sig"
    )


def test_existing_python_is_used_without_download(run_script: Callable):
    """已有符合要求的系统 Python 时，仅确保 uv 可用。"""
    result = run_script(
        """
find_system_python() { echo /bin/true; }
ensure_uv() { echo UV_READY; }
uv() { echo SHOULD_NOT_INSTALL; return 99; }
ensure_python
printf 'SELECTED:%s\n' "$DEPLOY_PYTHON"
""",
        """
function TestPython { $global:LASTEXITCODE = 0; 'Python 3.12.8' }
function Find-SystemPython { 'TestPython' }
function Ensure-Uv { 'UV_READY' }
function uv { throw 'SHOULD_NOT_INSTALL' }
Ensure-Python
"SELECTED:$script:DeployPython"
""",
    )
    assert result.returncode == 0, result.stderr
    assert "UV_READY" in result.stdout
    assert "SELECTED:" in result.stdout
    assert "SHOULD_NOT_INSTALL" not in result.stdout + result.stderr


@pytest.mark.parametrize("already_installed", [False, True])
def test_managed_python_install_or_reuse(run_script: Callable, already_installed: bool):
    """没有系统 Python 时先查 uv，缺失才安装，已安装时直接复用。"""
    result = run_script(
        f"installed={int(already_installed)}\n" + """
find_system_python() { return 1; }
ensure_uv() { echo UV_READY; }
uv() {
    if [[ "$1 $2" == 'python find' ]]; then
        [[ "$*" == 'python find --managed-python --no-project --no-python-downloads >=3.12' ]] || return 99
        [[ -f installed ]] || [[ $installed == 1 ]] || return 1
        echo /bin/true
    elif [[ "$*" == 'python install 3.12' ]]; then
        touch installed
        echo INSTALLED
    else
        return 99
    fi
}
ensure_python
printf 'SELECTED:%s\n' "$DEPLOY_PYTHON"
""",
        "$script:installed = $" + str(already_installed).lower() + "\n" + """
function TestPython { $global:LASTEXITCODE = 0; 'Python 3.12.8' }
function Find-SystemPython { $null }
function Ensure-Uv { 'UV_READY' }
function uv {
    if ($args[0] -eq 'python' -and $args[1] -eq 'find') {
        if (($args -join ' ') -ne 'python find --managed-python --no-project --no-python-downloads >=3.12') { throw 'Unexpected arguments' }
        if (-not $script:installed) { $global:LASTEXITCODE = 1; return }
        $global:LASTEXITCODE = 0
        'TestPython'
    } elseif (($args -join ' ') -eq 'python install 3.12') {
        $script:installed = $true
        $global:LASTEXITCODE = 0
        'INSTALLED'
    } else { throw 'Unexpected command' }
}
Ensure-Python
"SELECTED:$script:DeployPython"
""",
    )
    assert result.returncode == 0, result.stderr
    assert "SELECTED:" in result.stdout
    assert ("INSTALLED" in result.stdout) is (not already_installed)
    assert ("将通过 uv 下载 Python 3.12" in result.stdout) is (not already_installed)


def test_python_install_failure_stops(run_script: Callable):
    """下载失败直接退出，不继续克隆或创建环境。"""
    result = run_script(
        "find_system_python() { return 1; }; ensure_uv() { :; }; uv() { return 1; }; ensure_python; echo SHOULD_NOT_CONTINUE",
        "function Find-SystemPython { $null }; function Ensure-Uv {}; function uv { $global:LASTEXITCODE = 1 }; Ensure-Python; 'SHOULD_NOT_CONTINUE'",
    )
    assert result.returncode != 0
    assert "uv 安装 Python 失败" in result.stdout + result.stderr
    assert "SHOULD_NOT_CONTINUE" not in result.stdout


def test_sync_uses_selected_interpreter_with_spaces(
    run_script: Callable, tmp_path: Path
):
    """同步依赖明确使用已选解释器，路径含空格时保持单个参数。"""
    (tmp_path / "JMcomicBot").mkdir()
    result = run_script(
        """
DEPLOY_PYTHON='/tmp/Python path/python'
uv() { printf '<%s>' "$@"; }
setup_python_env
""",
        r"""
$script:DeployPython = 'C:\Python path\python.exe'
function uv { foreach ($argument in $args) { Write-Host "<$argument>" -NoNewline }; $global:LASTEXITCODE = 0 }
Setup-PythonEnv
""",
    )
    assert result.returncode == 0, result.stderr
    assert "<sync><--no-dev><--python>" in result.stdout
    assert "<--no-python-downloads>" in result.stdout
    assert "<venv>" not in result.stdout
    assert "Python path" in result.stdout


def test_set_env_special_characters(run_script: Callable, tmp_path: Path):
    """写入 token 时保留替换分隔符，且只修改指定配置项。"""
    env_file = tmp_path / ".env"
    env_file.write_text(" NAPCAT_TOKEN = old\nOTHER=keep\n", encoding="utf-8")
    result = run_script(
        "set_env NAPCAT_TOKEN 'abc|def&ghi' .env",
        "Set-Env 'NAPCAT_TOKEN' 'abc|def&ghi' '.env'",
    )
    assert result.returncode == 0, result.stderr
    assert not env_file.read_bytes().startswith(b"\xef\xbb\xbf")
    assert env_file.read_text(encoding="utf-8-sig").splitlines() == [
        "NAPCAT_TOKEN=abc|def&ghi",
        "OTHER=keep",
    ]


@pytest.mark.parametrize("content", [None, "OTHER=keep\n"])
def test_set_env_append(run_script: Callable, tmp_path: Path, content):
    """不存在的文件和只有一行的文件都能正确追加新配置。"""
    env_file = tmp_path / ".env"
    if content is not None:
        env_file.write_text(content, encoding="utf-8")
    result = run_script(
        "set_env NAPCAT_WS_URL ws://localhost:3001/qq .env",
        "Set-Env 'NAPCAT_WS_URL' 'ws://localhost:3001/qq' '.env'",
    )
    assert result.returncode == 0, result.stderr
    assert env_file.read_text(encoding="utf-8") == (
        (content or "") + "NAPCAT_WS_URL=ws://localhost:3001/qq\n"
    )


def test_input_eof_stops(run_script: Callable):
    result = run_script("ask '测试输入' n", "Ask '测试输入' 'n'")
    assert result.returncode != 0
    assert "输入已结束" in result.stdout + result.stderr


def test_boolean_retries(run_script: Callable):
    result = run_script(
        "ask_boolean '测试开关' true", "Ask-Boolean '测试开关' 'true'", "typo\nfalse\n"
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("false")
    assert "请输入 true 或 false" in result.stdout + result.stderr


def test_update_failure_stops(run_script: Callable, tmp_path: Path):
    (tmp_path / "JMcomicBot/.git").mkdir(parents=True)
    result = run_script(
        "git() { return 1; }; clone_or_update; printf 'SHOULD_NOT_CONTINUE'",
        "function git { $global:LASTEXITCODE = 1 }; Clone-Or-Update; 'SHOULD_NOT_CONTINUE'",
    )
    assert result.returncode != 0
    assert "部署已中止" in result.stdout + result.stderr
    assert "SHOULD_NOT_CONTINUE" not in result.stdout


def test_windows_batch_entry_check() -> None:
    """通过真实 CMD 验证入口，只检查语法而不执行部署。"""
    executable = shutil.which("powershell.exe")
    if executable is None:
        pytest.skip("当前环境没有 Windows PowerShell")
    batch_path = _windows_path(PROJECT_ROOT / "scripts/deploy.bat")
    command = (
        "& cmd.exe /d /c "
        + _ps_string('call "' + batch_path + '" --check')
        + "; exit $LASTEXITCODE"
    )
    encoded = base64.b64encode(command.encode("utf-16-le")).decode("ascii")
    result = subprocess.run(
        [executable, "-NoProfile", "-EncodedCommand", encoded],
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "Windows 部署脚本语法检查通过" in result.stdout.decode("utf-8")
