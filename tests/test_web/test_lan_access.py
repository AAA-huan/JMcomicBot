"""局域网模式（WEBUI_HOST=0.0.0.0）的 Host 与 Origin 放行测试。"""

from pathlib import Path

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from tests.test_web.support import PASSWORD, build_web_context, create_test_client

LAN_HOST = "172.23.7.69:8000"


def _make_lan_client(db_manager) -> TestClient:
    """构造绑定 0.0.0.0、Host 头为局域网地址的测试客户端。"""
    root = Path(db_manager.db_dir).parent
    context = build_web_context(db_manager, root, root / "backups")
    return create_test_client(
        context.dependencies,
        web_host="0.0.0.0",
        host_header=LAN_HOST,
    )


def test_lan_mode_allows_device_host(db_manager) -> None:
    """绑定 0.0.0.0 时，局域网 IP 的 Host 可访问页面与只读接口。"""
    with _make_lan_client(db_manager) as client:
        index = client.get("/")
        status = client.get("/api/v1/auth/status")

    assert index.status_code == 200
    assert '<div id="app">' in index.text
    assert status.status_code == 200


def test_lan_mode_allows_same_origin_write_and_rejects_cross_site(db_manager) -> None:
    """同源写请求通过 Origin 校验，跨站来源仍被 403 拒绝。"""
    with _make_lan_client(db_manager) as client:
        cross_site = client.post(
            "/api/v1/auth/setup",
            json={"password": PASSWORD},
            headers={"Origin": "http://attacker.example"},
        )
        same_origin = client.post(
            "/api/v1/auth/setup",
            json={"password": PASSWORD},
            headers={"Origin": f"http://{LAN_HOST}"},
        )

    assert cross_site.status_code == 403
    assert cross_site.json()["code"] == "INVALID_ORIGIN"
    assert same_origin.status_code == 201


def test_lan_mode_websocket_origin_rules(db_manager) -> None:
    """WebSocket 握手：跨站 Origin 关闭 4403，同源未登录关闭 4401。"""
    with _make_lan_client(db_manager) as client:
        with pytest.raises(WebSocketDisconnect) as cross_site:
            with client.websocket_connect(
                "/api/v1/events",
                headers={"Origin": "http://attacker.example", "Host": LAN_HOST},
            ):
                pass
        assert cross_site.value.code == 4403

        with pytest.raises(WebSocketDisconnect) as same_origin:
            with client.websocket_connect(
                "/api/v1/events",
                headers={"Origin": f"http://{LAN_HOST}", "Host": LAN_HOST},
            ):
                pass
        assert same_origin.value.code == 4401


def test_default_mode_still_rejects_lan_host(db_manager) -> None:
    """未启用局域网绑定时，外部 Host 仍被拒绝（默认保持本机安全）。"""
    root = Path(db_manager.db_dir).parent
    context = build_web_context(db_manager, root, root / "backups")
    with create_test_client(context.dependencies, host_header=LAN_HOST) as client:
        response = client.get("/api/v1/auth/status")

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_HOST"
