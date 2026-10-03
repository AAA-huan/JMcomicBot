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
            script_path = _ps_string(_windows_path(PROJECT_ROOT / "scripts/deploy.ps1"))
            directory = _ps_string(_windows_path(tmp_path))
            source = (
                # 模拟 irm 将原始 UTF-8 字节解码为字符串的路径；ReadAllText
                # 会自动移除 BOM，从而掩盖脚本首行的 CommandNotFoundException。
                "$ErrorActionPreference = 'Stop'\n"
                + ". ([scriptblock]::Create([Text.Encoding]::UTF8.GetString([IO.File]::ReadAllBytes("
                + script_path
                + "))))\n"
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
