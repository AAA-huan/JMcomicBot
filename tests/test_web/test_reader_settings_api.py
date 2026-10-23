"""阅读器设置 Web API 集成测试。"""

from pathlib import Path

from starlette.testclient import TestClient

from src.database.database import DatabaseManager
from src.database.repositories import AuditEventRepository, ReadingSettingRepository
from tests.test_web.support import (
    build_web_context,
    create_test_client,
    csrf_headers,
    setup_and_login,
)


def _make_client(db_manager: DatabaseManager) -> TestClient:
    """构造阅读设置接口测试客户端。"""
    root = Path(db_manager.db_dir).parent
    context = build_web_context(db_manager, root)
    return create_test_client(context.dependencies)


def test_reader_settings_require_login_and_csrf(db_manager) -> None:
    """读写接口必须经过登录；写接口必须携带 CSRF。"""
    client = _make_client(db_manager)
    with client:
        assert client.get("/api/v1/reader/settings").status_code == 401
        assert client.put("/api/v1/reader/settings", json={}).status_code == 403
        client.cookies.set("jmbot_csrf", "csrf-token")
        response = client.put(
            "/api/v1/reader/settings",
            json={},
            headers={"X-CSRF-Token": "csrf-token"},
        )
        assert response.status_code == 401
        assert response.json()["code"] == "AUTH_REQUIRED"


def test_reader_settings_defaults_and_persistence(db_manager) -> None:
    """首次读取返回默认值且不落库；保存后读取与部分更新保持一致。"""
    client = _make_client(db_manager)
    with client:
        setup_and_login(client)
        headers = csrf_headers(client)

        initial = client.get("/api/v1/reader/settings")
        assert initial.status_code == 200
        payload = initial.json()
        assert payload["reading_mode"] == "normal"
        assert payload["continuous"] is False
        assert payload["click_to_turn"] is False
        assert payload["reverse_click"] is False
        assert payload["dark_background"] is False
        assert payload["updated_at"] is not None
        assert ReadingSettingRepository(db_manager).get(1) is None

        saved = client.put(
            "/api/v1/reader/settings",
            json={
                "reading_mode": "manga",
                "continuous": True,
                "click_to_turn": True,
                "reverse_click": True,
                "dark_background": True,
            },
            headers=headers,
        )
        assert saved.status_code == 200
        assert saved.json()["reading_mode"] == "manga"
        assert saved.json()["continuous"] is True
        assert saved.json()["click_to_turn"] is True
        assert saved.json()["reverse_click"] is True
        assert saved.json()["dark_background"] is True

        partial = client.put(
            "/api/v1/reader/settings",
            json={"dark_background": False},
            headers=headers,
        )
        assert partial.status_code == 200
        assert partial.json()["reading_mode"] == "manga"
        assert partial.json()["continuous"] is True
        assert partial.json()["dark_background"] is False

        reloaded = client.get("/api/v1/reader/settings")
        assert reloaded.json()["reading_mode"] == "manga"
        assert reloaded.json()["dark_background"] is False

    stored = ReadingSettingRepository(db_manager).get(1)
    assert stored is not None
    assert stored.reading_mode == "manga"
    events = AuditEventRepository(db_manager).list(page_size=20)
    assert [event.event_type for event in events[:2]] == [
        "reader.setting_changed",
        "reader.setting_changed",
    ]
    assert {event.source for event in events[:2]} == {"web"}


def test_reader_settings_invalid_combinations(db_manager) -> None:
    """非法模式、未知模式与反转依赖缺失返回稳定 400 错误码。"""
    client = _make_client(db_manager)
    with client:
        setup_and_login(client)
        headers = csrf_headers(client)

        invalid_mode = client.put(
            "/api/v1/reader/settings",
            json={"reading_mode": "single"},
            headers=headers,
        )
        reverse_without_click = client.put(
            "/api/v1/reader/settings",
            json={"reverse_click": True},
            headers=headers,
        )
        enable_both = client.put(
            "/api/v1/reader/settings",
            json={"click_to_turn": True, "reverse_click": True},
            headers=headers,
        )
        disable_click_keeps_reverse = client.put(
            "/api/v1/reader/settings",
            json={"click_to_turn": False},
            headers=headers,
        )

    assert invalid_mode.status_code == 400
    assert invalid_mode.json()["code"] == "READER_SETTING_INVALID"
    assert reverse_without_click.status_code == 400
    assert reverse_without_click.json()["code"] == "READER_SETTING_INVALID"
    assert enable_both.status_code == 200
    assert enable_both.json()["reverse_click"] is True
    # 关闭点击翻页时反转仍为 true，后端拒绝而不是静默修正。
    assert disable_click_keeps_reverse.status_code == 400
    assert disable_click_keeps_reverse.json()["code"] == "READER_SETTING_INVALID"
    stored = ReadingSettingRepository(db_manager).get(1)
    assert stored is not None
    assert stored.click_to_turn is True
    assert stored.reverse_click is True
