"""启动恢复询问 Web API 测试。"""

from src.service.recovery_prompt import RecoveryPrompt
from tests.test_web.support import csrf_headers, create_client_for, setup_and_login


def test_recovery_endpoints_require_login(db_manager) -> None:
    client, _context = create_client_for(db_manager)

    with client:
        assert client.get("/api/v1/system/recovery").status_code == 401
        # 提供匹配令牌，确保命中会话鉴权而不是 CSRF 中间件
        client.cookies.set("jmbot_csrf", "not-logged-in")
        response = client.post(
            "/api/v1/system/recovery",
            json={"action": "cancel"},
            headers={"X-CSRF-Token": "not-logged-in"},
        )

    assert response.status_code == 401


def test_recovery_status_without_pending_prompt(db_manager) -> None:
    client, _context = create_client_for(db_manager)

    with client:
        setup_and_login(client)
        status = client.get("/api/v1/system/recovery")
        response = client.post(
            "/api/v1/system/recovery",
            json={"action": "continue"},
            headers=csrf_headers(client),
        )

    assert status.status_code == 200
    assert status.json() == {
        "pending": False,
        "task_count": 0,
        "remaining_seconds": 0,
        "decision": None,
    }
    assert response.status_code == 409
    assert response.json()["code"] == "RECOVERY_NOT_PENDING"


def test_webui_can_continue_pending_recovery(db_manager) -> None:
    client, context = create_client_for(db_manager)
    prompt = RecoveryPrompt(task_count=2, timeout_seconds=180)
    context.recovery_prompt_holder["prompt"] = prompt

    with client:
        setup_and_login(client)
        pending = client.get("/api/v1/system/recovery")
        resolved = client.post(
            "/api/v1/system/recovery",
            json={"action": "continue"},
            headers=csrf_headers(client),
        )
        resolved_again = client.post(
            "/api/v1/system/recovery",
            json={"action": "cancel"},
            headers=csrf_headers(client),
        )
        finished = client.get("/api/v1/system/recovery")

    assert pending.status_code == 200
    assert pending.json()["pending"] is True
    assert pending.json()["task_count"] == 2
    assert pending.json()["remaining_seconds"] > 0
    assert resolved.json() == {"resolved": True}
    assert prompt.decision == "continue"
    assert resolved_again.status_code == 409
    assert finished.json()["pending"] is False
    assert finished.json()["decision"] == "continue"


def test_webui_can_cancel_pending_recovery(db_manager) -> None:
    client, context = create_client_for(db_manager)
    prompt = RecoveryPrompt(task_count=1, timeout_seconds=180)
    context.recovery_prompt_holder["prompt"] = prompt

    with client:
        setup_and_login(client)
        response = client.post(
            "/api/v1/system/recovery",
            json={"action": "cancel"},
            headers=csrf_headers(client),
        )

    assert response.status_code == 200
    assert response.json() == {"resolved": True}
    assert prompt.wait() == "cancel"


def test_recovery_rejects_invalid_action(db_manager) -> None:
    client, _context = create_client_for(db_manager)

    with client:
        setup_and_login(client)
        response = client.post(
            "/api/v1/system/recovery",
            json={"action": "retry"},
            headers=csrf_headers(client),
        )

    assert response.status_code == 422
