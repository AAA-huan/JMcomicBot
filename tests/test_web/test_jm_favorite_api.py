"""真实认证与 CSRF 下的 JM 收藏导入 API 测试。"""

from src.database.repositories import FavoriteRepository, MangaRepository
from tests.test_service.test_jm_favorite_service import FakeClient
from tests.test_web.support import (
    PASSWORD,
    create_client_for,
    csrf_headers,
    setup_and_login,
)


def wait_job(service):
    assert service._worker is not None
    service._worker.join(5)
    assert not service._worker.is_alive()


def test_login_import_list_download_and_web_logout(db_manager):
    client, context = create_client_for(db_manager)
    service = context.dependencies.jm_favorite_service
    fake = FakeClient()
    service.client_factory = lambda: fake
    with client:
        assert client.get("/api/v1/jm-favorites").status_code == 401
        setup_and_login(client)
        headers = csrf_headers(client)
        login_path = "/api/v1/jm-favorites/account/login"
        body = {"username": "user", "password": "secret"}
        assert client.post(login_path, json=body).status_code == 403
        logged_in = client.post(login_path, json=body, headers=headers)
        assert logged_in.status_code == 200
        assert logged_in.json()["connected"]
        assert {folder["id"] for folder in logged_in.json()["folders"]} == {
            "0",
            "7",
            "8",
        }
        assert "secret" not in logged_in.text
        invalid = client.post(
            login_path, json={"username": "user", "password": ""}, headers=headers
        )
        assert invalid.status_code == 422
        assert (
            client.post(
                "/api/v1/jm-favorites/imports", json={"folder_ids": ["7"]}
            ).status_code
            == 403
        )
        started = client.post(
            "/api/v1/jm-favorites/imports",
            json={"folder_ids": ["7", "7"]},
            headers=headers,
        )
        assert started.status_code == 202
        wait_job(service)
        job = client.get(f'/api/v1/jm-favorites/imports/{started.json()["id"]}').json()
        assert (job["status"], job["imported_count"]) == ("succeeded", 2)
        assert (
            client.get("/api/v1/jm-favorites/imports").json()["items"][0]["id"]
            == job["id"]
        )
        assert client.get("/api/v1/jm-favorites/imports/unknown").status_code == 404
        result = client.get("/api/v1/jm-favorites?search=漫画二&page_size=1").json()
        assert result["total"] == result["pages"] == 1
        assert result["items"][0]["manga_id"] == "200"
        assert client.get("/api/v1/jm-favorites?download_status=bad").status_code == 422
        assert client.get("/api/v1/jm-favorites?folder_id=%22").status_code == 422
        assert client.get("/api/v1/mangas").json()["total"] == 0
        download_path = "/api/v1/jm-favorites/downloads"
        assert (
            client.post(download_path, json={"manga_ids": ["100"]}).status_code == 403
        )
        assert (
            client.post(
                download_path, json={"manga_ids": ["999"]}, headers=headers
            ).status_code
            == 404
        )
        assert (
            client.post(
                download_path, json={"manga_ids": ["not-a-number"]}, headers=headers
            ).status_code
            == 400
        )
        assert (
            client.post(
                download_path, json={"manga_ids": ["100"] * 21}, headers=headers
            ).status_code
            == 422
        )
        assert (
            client.post(
                download_path, json={"manga_ids": ["100", "100"]}, headers=headers
            ).json()["queued_count"]
            == 1
        )
        assert context.download_queue.requested_manga_ids == ["100"]
        assert (
            client.post(
                download_path, json={"manga_ids": ["100"]}, headers=headers
            ).json()["duplicate_count"]
            == 1
        )
        assert client.post("/api/v1/auth/logout", headers=headers).status_code == 200
        assert service._sessions == {}
        assert (
            client.post("/api/v1/auth/login", json={"password": PASSWORD}).status_code
            == 200
        )
        assert not client.get("/api/v1/jm-favorites/account").json()["connected"]
        assert client.get("/api/v1/jm-favorites").json()["total"] == 2


def test_login_failure_is_sanitized_and_password_change_clears_sessions(db_manager):
    client, context = create_client_for(db_manager)
    service = context.dependencies.jm_favorite_service

    def fail_factory():
        raise RuntimeError("password=secret AVS=private")

    service.client_factory = fail_factory
    with client:
        setup_and_login(client)
        headers = csrf_headers(client)
        path = "/api/v1/jm-favorites/account/login"
        failed = client.post(
            path, json={"username": "user", "password": "secret"}, headers=headers
        )
        assert failed.status_code == 502
        assert failed.json()["code"] == "JM_LOGIN_FAILED"
        assert "secret" not in failed.text and "private" not in failed.text
        assert not client.get("/api/v1/jm-favorites/account").json()["connected"]
        service.client_factory = FakeClient
        assert (
            client.post(
                path, json={"username": "user", "password": "secret"}, headers=headers
            ).status_code
            == 200
        )
        assert client.post(
            "/api/v1/jm-favorites/account/logout", headers=headers
        ).json() == {"connected": False}
        assert (
            client.post(
                "/api/v1/jm-favorites/imports",
                json={"folder_ids": ["0"]},
                headers=headers,
            ).status_code
            == 409
        )
        client.post(
            path, json={"username": "user", "password": "secret"}, headers=headers
        )
        changed = client.put(
            "/api/v1/auth/password",
            json={"old_password": PASSWORD, "new_password": "new-password"},
            headers=headers,
        )
        assert changed.status_code == 200
        assert service._sessions == {}


def test_deleted_local_record_can_be_imported_then_downloaded_again(db_manager):
    mangas = MangaRepository(db_manager)
    mangas.upsert("100", "已删除", "", 1, 3, status="deleted")
    client, context = create_client_for(db_manager)
    context.dependencies.jm_favorite_service.client_factory = FakeClient
    with client:
        setup_and_login(client)
        headers = csrf_headers(client)
        client.post(
            "/api/v1/jm-favorites/account/login",
            json={"username": "user", "password": "secret"},
            headers=headers,
        )
        client.post(
            "/api/v1/jm-favorites/imports", json={"folder_ids": ["7"]}, headers=headers
        )
        wait_job(context.dependencies.jm_favorite_service)
        assert FavoriteRepository(db_manager).get("web_admin", "1", "100") is None
        assert mangas.get("100", include_deleted=True).status == "deleted"
        assert (
            client.get("/api/v1/jm-favorites?download_status=not_downloaded").json()[
                "total"
            ]
            == 2
        )
        response = client.post(
            "/api/v1/jm-favorites/downloads",
            json={"manga_ids": ["100"]},
            headers=headers,
        )
        assert response.status_code == 202
        assert context.download_queue.requested_manga_ids == ["100"]
