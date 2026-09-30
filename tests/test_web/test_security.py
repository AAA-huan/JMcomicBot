"""Web API 错误格式、安全中间件和静态托管测试。"""

from argon2 import PasswordHasher
from starlette.testclient import TestClient

from src.database.models import utc_now
from src.database.repositories import (
    AuditEventRepository,
    MangaRepository,
    MangaTagRepository,
    OperationTaskRepository,
    WebAdminRepository,
    WebSessionRepository,
)
from src.service.query_service import MangaQueryService, TaskQueryService
from src.service.system_service import SystemService
from src.service.web_auth_service import WebAuthService
from src.web.app import create_web_app
from src.web.dependencies import WebDependencies

PASSWORD = "correct-horse-battery-staple"


def _create_client(db_manager) -> TestClient:
    manga_repository = MangaRepository(db_manager, download_root=db_manager.db_dir)
    dependencies = WebDependencies(
        auth_service=WebAuthService(
            WebAdminRepository(db_manager),
            WebSessionRepository(db_manager),
            AuditEventRepository(db_manager),
            session_hours=24,
            password_hasher=PasswordHasher(
                time_cost=1,
                memory_cost=8192,
                parallelism=1,
            ),
        ),
        manga_query_service=MangaQueryService(
            manga_repository, MangaTagRepository(db_manager)
        ),
        task_query_service=TaskQueryService(OperationTaskRepository(db_manager)),
        system_service=SystemService(
            version="test-version",
            started_at=utc_now(),
            manga_repository=manga_repository,
            connection_provider=lambda: False,
            download_queue_provider=lambda: {},
            send_queue_provider=lambda: {},
        ),
    )
    return TestClient(
        create_web_app(dependencies),
        client=("127.0.0.1", 50000),
        headers={"Host": "127.0.0.1"},
    )


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
    with _create_client(db_manager) as client:
        index = client.get("/library/100")
        asset = client.get("/assets/placeholder.2b4c.css")

    assert index.status_code == 200
    assert "Web 后端已就绪" in index.text
    assert index.headers["Cache-Control"] == "no-store"
    assert asset.status_code == 200
    assert asset.headers["Cache-Control"] == "public, max-age=31536000, immutable"
