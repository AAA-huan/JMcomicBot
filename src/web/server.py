"""受 MangaBot 生命周期管理的 Uvicorn Web 服务。"""

from collections.abc import Callable
from threading import Lock, Thread
from time import monotonic, sleep
from typing import Any, List, Tuple

import socket

import uvicorn
from fastapi import FastAPI

from src.logging.logger_config import logger

ServerFactory = Callable[[uvicorn.Config], uvicorn.Server]

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
ANY_INTERFACE_HOSTS = {"0.0.0.0", "::"}


def detect_lan_ip() -> str | None:
    """探测本机局域网出口 IP，无法确定路由时返回 None。"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # UDP connect 不真正发包，只借路由选择确定本机出口 IP
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return None
    finally:
        sock.close()


class WebServer:
    """在线程中运行 Uvicorn，不拥有进程信号和应用总生命周期。"""

    def __init__(
        self,
        app: FastAPI,
        host: str,
        port: int,
        logger_instance: Any = None,
        server_factory: ServerFactory = uvicorn.Server,
    ) -> None:
        self.host = host
        self.port = port
        self.logger = logger_instance or logger
        self._server = server_factory(
            uvicorn.Config(
                app=app,
                host=host,
                port=port,
                log_config=None,
                access_log=False,
            )
        )
        self._thread: Thread | None = None
        self._lock = Lock()
        self._run_error: BaseException | None = None

    @property
    def is_running(self) -> bool:
        """返回服务线程是否存活且 Uvicorn 已完成启动。"""
        thread = self._thread
        return thread is not None and thread.is_alive() and self._server.started

    def _run(self) -> None:
        """线程入口，保留启动异常供主线程精确报告。"""
        try:
            self._server.run()
        except BaseException as error:  # pylint: disable=broad-exception-caught
            self._run_error = error

    def _access_urls(self) -> List[Tuple[str, str]]:
        """按监听地址生成带用途标签的访问链接。"""
        local_url = f"http://127.0.0.1:{self.port}"
        if self.host in LOOPBACK_HOSTS:
            return [("本地访问", local_url)]
        if self.host in ANY_INTERFACE_HOSTS:
            lan_ip = detect_lan_ip()
            if lan_ip is None:
                self.logger.warning("未能探测到局域网 IP，请手动查询本机 IP")
                return [
                    ("本地访问", local_url),
                    ("监听地址", f"http://0.0.0.0:{self.port}"),
                ]
            # 绑定全部网卡时，本机和局域网设备都能访问
            return [
                ("本地访问", local_url),
                ("局域网访问", f"http://{lan_ip}:{self.port}"),
            ]
        # 绑定指定网卡时直接使用配置中的地址
        return [("监听地址", f"http://{self.host}:{self.port}")]

    def start(self, timeout: float = 5.0) -> None:
        """启动服务并等待监听成功，失败或超时会明确抛错。"""
        if timeout <= 0:
            raise ValueError("Web 服务启动超时必须大于 0")
        with self._lock:
            if self.is_running:
                return
            if self._thread is not None:
                raise RuntimeError("Web 服务已经停止，不能重复启动")
            self._thread = Thread(
                target=self._run,
                name="jmcomic-web-server",
                daemon=False,
            )
            self._thread.start()

        deadline = monotonic() + timeout
        while monotonic() < deadline:
            if self._server.started:
                for label, url in self._access_urls():
                    self.logger.info(f"WebUI 已启动（{label}）: {url}")
                return
            if not self._thread.is_alive():
                if self._run_error is not None:
                    raise RuntimeError("WebUI 启动失败") from self._run_error
                raise RuntimeError("WebUI 启动失败，服务线程已提前退出")
            sleep(0.01)

        self._server.should_exit = True
        self._thread.join(timeout=timeout)
        raise TimeoutError(f"WebUI 未能在 {timeout:g} 秒内完成启动")

    def stop(self, timeout: float = 5.0) -> bool:
        """幂等请求 Uvicorn 退出，并在限定时间内等待线程结束。"""
        if timeout < 0:
            raise ValueError("Web 服务停止超时不能小于 0")
        with self._lock:
            thread = self._thread
            if thread is None or not thread.is_alive():
                return True
            self._server.should_exit = True
        thread.join(timeout=timeout)
        stopped = not thread.is_alive()
        if stopped:
            self.logger.info("WebUI 已停止")
        return stopped
