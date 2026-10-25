"""WebServer 受控线程生命周期与启动地址测试。"""

from threading import Event
from typing import Any, List

import pytest
from fastapi import FastAPI

from src.web.server import WebServer, detect_lan_ip


class FakeLogger:
    """收集启动日志，避免测试输出依赖真实日志文件。"""

    def __init__(self) -> None:
        self.info_messages: List[str] = []
        self.warning_messages: List[str] = []

    def info(self, message: str) -> None:
        self.info_messages.append(message)

    def warning(self, message: str) -> None:
        self.warning_messages.append(message)


class FakeSocket:
    """模拟 UDP socket 的出口 IP 探测。"""

    def __init__(self, ip: str | None = None, error: OSError | None = None) -> None:
        self.ip = ip
        self.error = error
        self.address: tuple[str, int] | None = None
        self.closed = False

    def connect(self, address: tuple[str, int]) -> None:
        self.address = address
        if self.error is not None:
            raise self.error

    def getsockname(self) -> tuple[str, int]:
        assert self.ip is not None
        return (self.ip, 54321)

    def close(self) -> None:
        self.closed = True


class FakeUvicornServer:
    """模拟 Uvicorn 启动与退出标志的可控服务。"""

    def __init__(self, _config: Any) -> None:
        self.started = False
        self.should_exit = False
        self.entered = Event()

    def run(self) -> None:
        self.started = True
        self.entered.set()
        while not self.should_exit:
            self.entered.wait(0.01)


class FailingUvicornServer(FakeUvicornServer):
    """模拟监听端口等启动错误。"""

    def run(self) -> None:
        raise OSError("端口已占用")


def test_web_server_starts_and_stops_idempotently() -> None:
    fake_server: FakeUvicornServer | None = None

    def create_server(config: Any) -> Any:
        nonlocal fake_server
        fake_server = FakeUvicornServer(config)
        return fake_server

    server = WebServer(
        FastAPI(),
        "127.0.0.1",
        7999,
        server_factory=create_server,
    )

    server.start(timeout=0.5)

    assert fake_server is not None
    assert fake_server.entered.is_set()
    assert server.is_running is True
    server.start(timeout=0.5)
    assert server.stop(timeout=0.5) is True
    assert server.stop(timeout=0.5) is True
    assert server.is_running is False


def test_web_server_surfaces_startup_error() -> None:
    server = WebServer(
        FastAPI(),
        "127.0.0.1",
        7999,
        server_factory=FailingUvicornServer,
    )

    with pytest.raises(RuntimeError, match="WebUI 启动失败") as error_info:
        server.start(timeout=0.5)

    assert isinstance(error_info.value.__cause__, OSError)
    assert server.stop(timeout=0.5) is True


def test_constructing_web_server_does_not_start_thread() -> None:
    server = WebServer(
        FastAPI(),
        "127.0.0.1",
        7999,
        server_factory=FakeUvicornServer,
    )

    assert server.is_running is False
    assert server.stop(timeout=0.1) is True


def _start_with_logger(
    host: str, logger_instance: FakeLogger, timeout: float = 0.5
) -> WebServer:
    """用可控 Uvicorn 替身启动服务，返回已停止的服务实例。"""
    server = WebServer(
        FastAPI(),
        host,
        7999,
        logger_instance=logger_instance,
        server_factory=FakeUvicornServer,
    )
    server.start(timeout=timeout)
    assert server.stop(timeout=timeout) is True
    return server


def test_detect_lan_ip_returns_socket_address(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_socket = FakeSocket(ip="192.168.1.20")
    monkeypatch.setattr("src.web.server.socket.socket", lambda *_args: fake_socket)

    assert detect_lan_ip() == "192.168.1.20"
    assert fake_socket.address == ("8.8.8.8", 80)
    assert fake_socket.closed is True


def test_detect_lan_ip_returns_none_when_connect_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_socket = FakeSocket(error=OSError("网络不可达"))
    monkeypatch.setattr("src.web.server.socket.socket", lambda *_args: fake_socket)

    assert detect_lan_ip() is None
    assert fake_socket.closed is True


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
def test_loopback_host_logs_local_address(
    host: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_detect() -> str | None:
        raise AssertionError("回环地址不应探测局域网 IP")

    monkeypatch.setattr("src.web.server.detect_lan_ip", fail_detect)
    logger_instance = FakeLogger()

    _start_with_logger(host, logger_instance)

    assert logger_instance.info_messages == [
        "WebUI 已启动（本地访问）: http://127.0.0.1:7999",
        "WebUI 已停止",
    ]
    assert logger_instance.warning_messages == []


@pytest.mark.parametrize("host", ["0.0.0.0", "::"])
def test_any_interface_host_logs_local_and_lan_addresses(
    host: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("src.web.server.detect_lan_ip", lambda: "192.168.1.20")
    logger_instance = FakeLogger()

    _start_with_logger(host, logger_instance)

    assert logger_instance.info_messages == [
        "WebUI 已启动（本地访问）: http://127.0.0.1:7999",
        "WebUI 已启动（局域网访问）: http://192.168.1.20:7999",
        "WebUI 已停止",
    ]
    assert logger_instance.warning_messages == []


@pytest.mark.parametrize("host", ["0.0.0.0", "::"])
def test_any_interface_host_warns_and_falls_back_when_detection_fails(
    host: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("src.web.server.detect_lan_ip", lambda: None)
    logger_instance = FakeLogger()

    _start_with_logger(host, logger_instance)

    assert logger_instance.warning_messages == [
        "未能探测到局域网 IP，请手动查询本机 IP"
    ]
    assert logger_instance.info_messages == [
        "WebUI 已启动（本地访问）: http://127.0.0.1:7999",
        "WebUI 已启动（监听地址）: http://0.0.0.0:7999",
        "WebUI 已停止",
    ]


def test_specific_host_keeps_configured_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_detect() -> str | None:
        raise AssertionError("指定网卡地址不应探测局域网 IP")

    monkeypatch.setattr("src.web.server.detect_lan_ip", fail_detect)
    logger_instance = FakeLogger()

    _start_with_logger("192.168.1.10", logger_instance)

    assert logger_instance.info_messages[0] == (
        "WebUI 已启动（监听地址）: http://192.168.1.10:7999"
    )
    assert logger_instance.warning_messages == []
