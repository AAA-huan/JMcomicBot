"""受 MangaBot 生命周期管理的 Uvicorn Web 服务。"""

from collections.abc import Callable
from threading import Lock, Thread
from time import monotonic, sleep
from typing import Any

import uvicorn
from fastapi import FastAPI

from src.logging.logger_config import logger

ServerFactory = Callable[[uvicorn.Config], uvicorn.Server]


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
                self.logger.info(f"WebUI 已启动: http://{self.host}:{self.port}")
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
