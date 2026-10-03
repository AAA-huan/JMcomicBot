"""认证、系统状态、漫画和任务只读 API 集成测试。"""

from datetime import timedelta
from starlette.testclient import TestClient

from src.database.models import MangaFile, ReadingProgress, utc_now
from src.database.repositories import (
    MangaRepository,
    MangaTagRepository,
    OperationTaskRepository,
    WebAdminRepository,
)
from tests.test_web.support import PASSWORD, create_client_for, setup_and_login


def _create_client(db_manager, host: str = "127.0.0.1") -> TestClient:
    client, _context = create_client_for(db_manager, host)
    return client


def _setup_and_login(client: TestClient) -> None:
    setup_and_login(client)


def test_authentication_flow_and_protected_status(db_manager) -> None:
    with _create_client(db_manager) as client:
        assert client.get("/api/v1/auth/status").json() == {
            "initialized": False,
            "authenticated": False,
        }
        assert client.get("/api/v1/system/status").status_code == 401

        _setup_and_login(client)

        auth_status = client.get("/api/v1/auth/status")
        assert auth_status.json() == {"initialized": True, "authenticated": True}
        me_response = client.get("/api/v1/auth/me")
        assert me_response.status_code == 200
        assert "password_hash" not in me_response.text
        system_response = client.get("/api/v1/system/status")
        assert system_response.status_code == 200
        assert system_response.json()["version"] == "test-version"
        assert system_response.json()["napcat_connected"] is True

        logout_response = client.post(
            "/api/v1/auth/logout",
            headers={"X-CSRF-Token": client.cookies["jmbot_csrf"]},
        )
        assert logout_response.status_code == 200
        assert client.get("/api/v1/system/status").status_code == 401


def test_setup_rejects_non_loopback_client(db_manager) -> None:
    with _create_client(db_manager, host="192.168.1.20") as client:
        response = client.post("/api/v1/auth/setup", json={"password": PASSWORD})

    assert response.status_code == 403
    assert WebAdminRepository(db_manager).get() is None


def test_manga_read_api_supports_paging_search_tag_and_sort(db_manager) -> None:
    manga_repository = MangaRepository(db_manager, download_root=db_manager.db_dir)
    tag_repository = MangaTagRepository(db_manager)
    manga_repository.upsert("100", "苹果漫画", "作者甲", 2, 20)
    manga_repository.upsert("200", "香蕉漫画", "作者乙", 3, 30)
    tag_repository.add("冒险", "100")
    tag_repository.add("日常", "200")

    with _create_client(db_manager) as client:
        _setup_and_login(client)

        response = client.get(
            "/api/v1/mangas",
            params={"search": "漫画", "tag": "冒险", "sort": "id_asc"},
        )
        detail = client.get("/api/v1/mangas/100")
        missing = client.get("/api/v1/mangas/999")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["pages"] == 1
    assert payload["items"][0]["id"] == "100"
    assert payload["items"][0]["tags"] == ["冒险"]
    assert detail.status_code == 200
    assert detail.json()["title"] == "苹果漫画"
    assert "relative_path" not in detail.text
    assert missing.status_code == 404


def test_task_read_api_supports_filters_and_details(db_manager) -> None:
    task_repository = OperationTaskRepository(db_manager)
    wanted = task_repository.create("download", "qq", manga_id="100")
    task_repository.create("scan", "system")

    with _create_client(db_manager) as client:
        _setup_and_login(client)
        response = client.get(
            "/api/v1/tasks",
            params={"task_type": "download", "status": "queued", "manga_id": "100"},
        )
        detail = client.get(f"/api/v1/tasks/{wanted.id}")
        invalid = client.get("/api/v1/tasks", params={"status": "unknown"})

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["summary"] == "下载漫画 100"
    assert detail.status_code == 200
    assert detail.json()["id"] == wanted.id
    assert invalid.status_code == 400


def test_history_uses_read_time_and_pagination(db_manager) -> None:
    """历史按最近阅读排序，分页且排除未读漫画。"""
    repository = MangaRepository(db_manager)
    for manga_id in ("100", "200", "300"):
        repository.upsert(manga_id, f"漫画{manga_id}", "作者", 2, 20)
    now = utc_now()
    with db_manager.get_session() as session:
        for index, (manga_id, days) in enumerate((("100", 0), ("200", 1)), start=1):
            file = MangaFile(
                manga_id=manga_id,
                display_name=f"章节{index}.pdf",
                relative_path=f"{index}.pdf",
                status="ready",
            )
            session.add(file)
            session.flush()
            session.add(
                ReadingProgress(
                    manga_file_id=file.id,
                    page_number=2,
                    page_count=10,
                    percent=20,
                    updated_at=now - timedelta(days=days),
                )
            )
        session.commit()
    with _create_client(db_manager) as client:
        _setup_and_login(client)
        first = client.get(
            "/api/v1/mangas",
            params={
                "history_only": True,
                "sort": "read_at_desc",
                "page_size": 1,
            },
        )
        assert first.status_code == 200
        assert first.json()["total"] == 2
        assert [item["id"] for item in first.json()["items"]] == ["100"]
        second = client.get(
            "/api/v1/mangas",
            params={
                "history_only": True,
                "sort": "read_at_desc",
                "page_size": 1,
                "page": 2,
            },
        )
        assert [item["id"] for item in second.json()["items"]] == ["200"]
        searched = client.get(
            "/api/v1/mangas",
            params={
                "history_only": True,
                "sort": "read_at_desc",
                "search": "200",
            },
        )
        assert searched.json()["total"] == 1
