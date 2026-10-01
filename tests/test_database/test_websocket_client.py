"""WebSocket 客户端地址校验测试。"""

from src.websocket.client import WebSocketClient, _validate_ws_url


def test_validate_ws_url_accepts_standard_addresses() -> None:
    """标准 ws/wss 地址应通过校验。"""
    assert _validate_ws_url("ws://127.0.0.1:3001/qq") is None
    assert _validate_ws_url("wss://example.com/ws") is None


def test_validate_ws_url_rejects_invalid_addresses() -> None:
    """空地址、错误协议与占位符端口都应给出明确的中文错误说明。"""
    assert "未配置" in str(_validate_ws_url(""))
    assert "ws:// 或 wss://" in str(_validate_ws_url("http://localhost:8080/qq"))
    assert "端口不是合法数字" in str(_validate_ws_url("ws://localhost:port/qq"))


def test_connect_skips_invalid_url_without_background_thread() -> None:
    """地址非法时不创建连接线程、不抛异常，WebUI 等其它功能保持可用。"""
    client = WebSocketClient(
        {"NAPCAT_WS_URL": "ws://localhost:port/qq", "NAPCAT_TOKEN": ""}
    )

    client.connect()
    client.connect()

    assert client.run_thread is None
    assert client.is_connected() is False
    assert client.close() is True
