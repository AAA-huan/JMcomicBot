"""WebServer 受控线程生命周期测试。"""

from threading import Event
from typing import Any

import pytest
from fastapi import FastAPI

from src.web.server import WebServer


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
        8000,
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
        8000,
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
        8000,
        server_factory=FakeUvicornServer,
    )

    assert server.is_running is False
    assert server.stop(timeout=0.1) is True
