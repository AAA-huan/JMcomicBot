"""审计只读接口与手动文件校验的集成回归。"""

from hashlib import sha256
from pathlib import Path

from src.database.repositories import AuditEventRepository, MangaRepository
from tests.test_web.support import create_client_for, csrf_headers, setup_and_login


def test_audit_requires_login_and_returns_stable_filtered_pages(db_manager) -> None:
    """审计应认证、稳定分页、支持筛选且不泄露内部元数据。"""
    repository = AuditEventRepository(db_manager)
    for index in range(3):
        repository.record(
            "manga.metadata_updated",
            "qq",
            "succeeded",
            target_id=str(index),
            metadata={"changed_fields": ["title"]},
        )
    client, _context = create_client_for(db_manager)
    with client:
        assert client.get("/api/v1/audit-events").status_code == 401
        setup_and_login(client)
        query = {"event_type": "manga.metadata_updated", "source": "qq", "page_size": 2}
        first = client.get("/api/v1/audit-events", params=query)
        second = client.get("/api/v1/audit-events", params={**query, "page": 2})
        assert first.status_code == 200
        assert first.json()["total"] == 3
        assert first.json()["pages"] == 2
        assert [event["target_id"] for event in first.json()["items"]] == ["2", "1"]
        assert [event["target_id"] for event in second.json()["items"]] == ["0"]
        assert "metadata_json" not in first.text
        assert "changed_fields" not in first.text
        assert client.get("/api/v1/audit-events?source=invalid").status_code == 400
        assert client.get("/api/v1/audit-events?page_size=101").status_code == 422


def test_verify_hashes_registered_file_and_persists_web_task(db_manager) -> None:
    """校验复用真实服务，写 SHA-256、任务和操作来源审计。"""
    root = Path(db_manager.db_dir).parent
    file = root / "renamed.pdf"
    file.write_bytes(b"%PDF registered test data")
    mangas = MangaRepository(db_manager, str(root))
    mangas.upsert("100", "测试漫画", "作者", 1, 10)
    registered = mangas.add_file("100", str(file))
    client, _context = create_client_for(db_manager)
    with client:
        assert (
            client.post(
                "/api/v1/maintenance/verify", json={"manga_ids": ["100"]}
            ).status_code
            == 403
        )
        setup_and_login(client)
        response = client.post(
            "/api/v1/maintenance/verify",
            json={"manga_ids": ["100", "100"]},
            headers=csrf_headers(client),
        )
        assert response.status_code == 200
        assert response.json()["file_count"] == 1
        assert response.json()["ready_count"] == 1
        task = client.get(f"/api/v1/tasks/{response.json()['task_id']}").json()
        assert task["task_type"] == "verify"
        assert task["source"] == "web"
        assert task["status"] == "succeeded"
    assert (
        mangas.get_file(registered.id).sha256 == sha256(file.read_bytes()).hexdigest()
    )
    events = AuditEventRepository(db_manager).list()
    event = next(
        item for item in events if item.event_type == "library.verify_completed"
    )
    assert event.source == "web"
    assert event.client_ip == "127.0.0.1"


def test_verify_validates_ids_limits_csrf_and_busy_files(db_manager) -> None:
    """拒绝任意路径、超量请求和正在下载的目标。"""
    client, _context = create_client_for(db_manager)
    with client:
        setup_and_login(client)
        headers = csrf_headers(client)
        for ids in [[], ["../secret.pdf"], [str(index) for index in range(101)]]:
            assert (
                client.post(
                    "/api/v1/maintenance/verify",
                    json={"manga_ids": ids},
                    headers=headers,
                ).status_code
                == 422
            )
        assert (
            client.post(
                "/api/v1/maintenance/verify", json={"manga_ids": ["100"]}
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/v1/maintenance/verify",
                json={"manga_ids": ["100"]},
                headers=headers,
            ).status_code
            == 400
        )
        client.post(
            "/api/v1/tasks/downloads", json={"manga_ids": ["100"]}, headers=headers
        )
        response = client.post(
            "/api/v1/maintenance/verify", json={"manga_ids": ["100"]}, headers=headers
        )
        assert response.status_code == 409
        assert response.json()["code"] == "MANGA_BUSY"
