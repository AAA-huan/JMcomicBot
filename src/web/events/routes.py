"""WebSocket 事件推送端点。"""

import asyncio
from contextlib import suppress
from typing import Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.logging.logger_config import logger
from src.web.api.common import SESSION_COOKIE_NAME
from src.web.dependencies import WebDependencies
from src.web.events.bus import EventSubscriber, build_event
from src.web.security import origin_is_trusted

# 自定义关闭码：客户端需在重连前重新登录
WS_UNAUTHORIZED_CODE = 4401
WS_FORBIDDEN_ORIGIN_CODE = 4403


async def _read_client_messages(
    websocket: WebSocket, subscriber: EventSubscriber
) -> None:
    """持续读取客户端消息，回应 ping 以便及时发现半开连接。"""
    while True:
        message = await websocket.receive_text()
        if message == "ping":
            subscriber.deliver(build_event("events.pong", {}))


async def _send_events(websocket: WebSocket, subscriber: EventSubscriber) -> None:
    """把订阅到的事件逐条发送给客户端。"""
    while True:
        event = await subscriber.get()
        await websocket.send_json(event)


def create_events_router(
    dependencies: WebDependencies,
    allowed_origins: Set[str],
    allow_any_host: bool = False,
) -> APIRouter:
    """创建 WebSocket 事件推送路由，认证与 Origin 在握手阶段校验。"""
    router = APIRouter(tags=["事件"])
    auth_service = dependencies.auth_service
    event_bus = dependencies.event_bus

    @router.websocket("/events")
    async def events(websocket: WebSocket) -> None:
        origin = websocket.headers.get("origin")
        if origin is not None and not origin_is_trusted(
            origin,
            websocket.headers.get("host"),
            allowed_origins,
            allow_any_host,
        ):
            await websocket.close(code=WS_FORBIDDEN_ORIGIN_CODE)
            return
        token = websocket.cookies.get(SESSION_COOKIE_NAME)
        authenticated = (
            await asyncio.to_thread(auth_service.authenticate, token)
            if token is not None
            else None
        )
        if authenticated is None:
            await websocket.close(code=WS_UNAUTHORIZED_CODE)
            return

        await websocket.accept()
        subscriber = event_bus.subscribe()
        logger.info(f"WebSocket 事件连接已建立（管理员 {authenticated.admin_id}）")
        try:
            reader = asyncio.create_task(_read_client_messages(websocket, subscriber))
            writer = asyncio.create_task(_send_events(websocket, subscriber))
            done, pending = await asyncio.wait(
                {reader, writer}, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
            for task in pending:
                with suppress(asyncio.CancelledError):
                    await task
            for task in done:
                with suppress(WebSocketDisconnect):
                    task.result()
        finally:
            event_bus.unsubscribe(subscriber)
            logger.info("WebSocket 事件连接已断开")

    return router
