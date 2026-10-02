"""WebSocket 事件推送集成测试。"""

import time
from pathlib import Path

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from src.database.database import DatabaseManager
from tests.test_web.support import (
    WebTestContext,
    build_web_context,
    create_test_client,
    csrf_headers,
    setup_and_login,
)


def _make_event_client(
    db_manager: DatabaseManager,
) -> tuple[TestClient, WebTestContext]:
    """构造使用高频状态采样的测试客户端。"""
    root = Path(db_manager.db_dir).parent
    context = build_web_context(db_manager, root, root / "backups")
    client = create_test_client(context.dependencies, status_interval_seconds=0.05)
    return client, context


def test_websocket_rejects_unauthenticated(db_manager) -> None:
    """未登录的 WebSocket 握手必须被拒绝。"""
    client, _context = _make_event_client(db_manager)
    with client:
        with pytest.raises(WebSocketDisconnect) as excinfo:
            with client.websocket_connect("/api/v1/events"):
                pass

    assert excinfo.value.code == 4401


def test_websocket_rejects_untrusted_origin(db_manager) -> None:
    """来源不受信任的 WebSocket 握手必须被拒绝。"""
    client, _context = _make_event_client(db_manager)
    with client:
        setup_and_login(client)
        with pytest.raises(WebSocketDisconnect) as excinfo:
            with client.websocket_connect(
                "/api/v1/events", headers={"Origin": "http://attacker.example"}
            ):
                pass

    assert excinfo.value.code == 4403


def test_websocket_pushes_snapshot_and_task_events(db_manager) -> None:
    """连接后先收到状态快照事件，写操作再推送 task.updated。"""
    client, _context = _make_event_client(db_manager)
    with client:
        setup_and_login(client)
        headers = csrf_headers(client)
        with client.websocket_connect("/api/v1/events") as websocket:
            snapshot_types = {websocket.receive_json()["type"] for _ in range(3)}
            assert snapshot_types == {
                "queue.updated",
                "napcat.updated",
                "system.updated",
            }

            response = client.post(
                "/api/v1/tasks/downloads",
                json={"manga_ids": ["101"]},
                headers=headers,
            )
            assert response.status_code == 202

            event = websocket.receive_json()
            assert event["type"] == "task.updated"
            assert event["data"]["manga_id"] == "101"
            assert event["data"]["status"] in ("queued", "running")
            assert "requested_by" not in event["data"]
            assert event["occurred_at"]


def test_websocket_answers_ping(db_manager) -> None:
    """ping 应收到 events.pong，保持连接可探测。"""
    client, _context = _make_event_client(db_manager)
    with client:
        setup_and_login(client)
        with client.websocket_connect("/api/v1/events") as websocket:
            for _ in range(3):
                websocket.receive_json()
            websocket.send_text("ping")
            pong = websocket.receive_json()

    assert pong["type"] == "events.pong"


def test_websocket_unsubscribes_after_disconnect(db_manager) -> None:
    """连接关闭后总线应清理订阅，广播器无需继续采样。"""
    client, context = _make_event_client(db_manager)
    with client:
        setup_and_login(client)
        with client.websocket_connect("/api/v1/events") as websocket:
            assert websocket.receive_json()["type"] == "queue.updated"
            assert context.event_bus.subscriber_count == 1

        deadline = time.monotonic() + 2
        while context.event_bus.subscriber_count and time.monotonic() < deadline:
            time.sleep(0.01)

    assert context.event_bus.subscriber_count == 0
