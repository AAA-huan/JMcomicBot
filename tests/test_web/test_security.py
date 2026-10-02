"""Web API 错误格式、安全中间件和静态托管测试。"""

from pathlib import Path

from starlette.testclient import TestClient

from tests.test_web.support import PASSWORD, create_client_for
from src.web.security import allowed_web_origins


def test_allowed_origins_include_configured_dev_origins() -> None:
    """开发服务器来源应可通过配置加入白名单。"""
    origins = allowed_web_origins(
        "127.0.0.1", 7999, {"http://127.0.0.1:5173", "http://localhost:5173"}
    )

    assert "http://127.0.0.1:7999" in origins
    assert "http://127.0.0.1:5173" in origins
    assert "http://localhost:5173" in origins


def _create_client(db_manager) -> TestClient:
    client, _context = create_client_for(db_manager)
    return client


def test_errors_use_stable_format_and_request_id(db_manager) -> None:
    with _create_client(db_manager) as client:
        response = client.get("/api/v1/unknown")

    assert response.status_code == 404
    payload = response.json()
    assert payload == {
        "code": "API_NOT_FOUND",
        "message": "接口不存在",
        "details": None,
        "request_id": response.headers["X-Request-ID"],
    }
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Cache-Control"] == "no-store"


def test_validation_error_does_not_expose_internal_details(db_manager) -> None:
    with _create_client(db_manager) as client:
        response = client.post("/api/v1/auth/setup", json={"password": "short"})

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert response.json()["message"] == "请求参数不符合要求"
    assert "traceback" not in response.text.lower()


def test_rejects_untrusted_host_and_origin(db_manager) -> None:
    with _create_client(db_manager) as client:
        invalid_host = client.get(
            "/api/v1/auth/status", headers={"Host": "attacker.example"}
        )
        invalid_origin = client.post(
            "/api/v1/auth/setup",
            json={"password": PASSWORD},
            headers={"Origin": "http://attacker.example"},
        )

    assert invalid_host.status_code == 400
    assert invalid_host.json()["code"] == "INVALID_HOST"
    assert invalid_origin.status_code == 403
    assert invalid_origin.json()["code"] == "INVALID_ORIGIN"


def test_write_request_access_log_is_debug(db_manager, monkeypatch) -> None:
    """写操作产生 DEBUG 级 URL 访问日志（含直连 IP），GET 请求不记录。"""
    messages: list[str] = []
    monkeypatch.setattr(
        "src.web.security.logger.debug", lambda message: messages.append(message)
    )

    with _create_client(db_manager) as client:
        client.get("/api/v1/auth/status")
        client.post("/api/v1/auth/setup", json={"password": "short"})

    write_logs = [message for message in messages if message.startswith("写请求")]
    assert len(write_logs) == 1
    assert "POST /api/v1/auth/setup" in write_logs[0]
    assert "IP 127.0.0.1" in write_logs[0]


def test_state_change_requires_matching_csrf_token(db_manager) -> None:
    with _create_client(db_manager) as client:
        assert (
            client.post("/api/v1/auth/setup", json={"password": PASSWORD}).status_code
            == 201
        )
        assert (
            client.post("/api/v1/auth/login", json={"password": PASSWORD}).status_code
            == 200
        )

        missing = client.post("/api/v1/auth/logout")
        mismatch = client.post(
            "/api/v1/auth/logout", headers={"X-CSRF-Token": "incorrect"}
        )
        success = client.post(
            "/api/v1/auth/logout",
            headers={"X-CSRF-Token": client.cookies["jmbot_csrf"]},
        )

    assert missing.status_code == 403
    assert missing.json()["code"] == "CSRF_FAILED"
    assert mismatch.status_code == 403
    assert success.status_code == 200


def test_login_failures_are_rate_limited_by_direct_client(db_manager) -> None:
    with _create_client(db_manager) as client:
        assert (
            client.post("/api/v1/auth/setup", json={"password": PASSWORD}).status_code
            == 201
        )
        for _attempt in range(5):
            response = client.post(
                "/api/v1/auth/login",
                json={"password": "incorrect-password"},
                headers={"X-Forwarded-For": "10.0.0.1"},
            )
            assert response.status_code == 401

        limited = client.post(
            "/api/v1/auth/login", json={"password": "incorrect-password"}
        )

    assert limited.status_code == 429
    assert limited.json()["code"] == "LOGIN_RATE_LIMITED"


def test_static_entry_and_assets_have_safe_cache_policy(db_manager) -> None:
    static_root = Path(__file__).resolve().parents[2] / "src" / "web" / "static"
    asset_files = sorted((static_root / "assets").glob("*.js"))
    assert asset_files, "前端构建产物缺失，请先执行 npm run build"
    asset_name = asset_files[0].name

    with _create_client(db_manager) as client:
        index = client.get("/library/100")
        asset = client.get(f"/assets/{asset_name}")

    assert index.status_code == 200
    assert '<div id="app">' in index.text
    assert "JMcomicBot" in index.text
    assert index.headers["Cache-Control"] == "no-store"
    assert asset.status_code == 200
    assert asset.headers["Cache-Control"] == "public, max-age=31536000, immutable"


def test_module_worker_asset_is_served_as_javascript(db_manager) -> None:
    """PDF.js 的 ESM Worker 必须以 JavaScript MIME 提供，否则浏览器拒绝加载。"""
    static_root = Path(__file__).resolve().parents[2] / "src" / "web" / "static"
    worker_files = sorted((static_root / "assets").glob("*.mjs"))
    assert worker_files, "构建产物缺少 PDF.js Worker（.mjs），请先执行 npm run build"
    worker_name = worker_files[0].name

    with _create_client(db_manager) as client:
        response = client.get(f"/assets/{worker_name}")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/javascript")
