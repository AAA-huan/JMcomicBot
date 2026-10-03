"""写接口集成测试：认证、CSRF、参数校验、幂等与冲突语义。"""

from pathlib import Path

from starlette.testclient import TestClient

from src.database.database import DatabaseManager
from src.database.repositories import (
    AuditEventRepository,
    MangaRepository,
    MangaTagRepository,
    OperationTaskRepository,
    UserGroupRepository,
)
from tests.test_web.support import (
    PASSWORD,
    build_web_context,
    create_test_client,
    csrf_headers,
    setup_and_login,
)


def _make_client(
    db_manager: DatabaseManager, config_dict=None
) -> tuple[TestClient, object]:
    """构造写接口测试客户端与可观测上下文。"""
    root = Path(db_manager.db_dir).parent
    context = build_web_context(
        db_manager, root, root / "backups", config_dict=config_dict
    )
    return create_test_client(context.dependencies), context


def _add_manga(
    db_manager: DatabaseManager, root: Path, manga_id: str, title: str = "旧标题"
) -> Path:
    """写入漫画记录、PDF 文件与标签。"""
    pdf_path = root / f"{manga_id}-{title}(1章).pdf"
    pdf_path.write_bytes(b"%PDF")
    manga_repo = MangaRepository(db_manager, download_root=str(root))
    manga_repo.upsert(manga_id, title, "旧作者", 1, 10)
    manga_repo.add_file(manga_id, str(pdf_path))
    return pdf_path


def test_write_endpoints_require_login_and_csrf(db_manager) -> None:
    """未登录或缺少 CSRF 的写请求必须被拒绝。"""
    client, _context = _make_client(db_manager)
    with client:
        # 缺少 CSRF Cookie/头：中间件先拒绝
        assert client.post("/api/v1/system/napcat/reconnect").status_code == 403

        # CSRF 通过但未登录：认证依赖返回 401
        client.cookies.set("jmbot_csrf", "csrf-token")
        response = client.post(
            "/api/v1/system/napcat/reconnect",
            headers={"X-CSRF-Token": "csrf-token"},
        )
        assert response.status_code == 401
        assert response.json()["code"] == "AUTH_REQUIRED"


def test_manga_patch_delete_flow_with_audit(db_manager) -> None:
    """元数据修改与删除应成功、写审计并保持删除幂等。"""
    root = Path(db_manager.db_dir).parent
    pdf_path = _add_manga(db_manager, root, "100")
    MangaTagRepository(db_manager).add("旧标签", "100")

    client, _context = _make_client(db_manager)
    with client:
        setup_and_login(client)
        headers = csrf_headers(client)

        patch_response = client.patch(
            "/api/v1/mangas/100",
            json={"title": "新标题", "tags": ["冒险", "日常"]},
            headers=headers,
        )
        invalid_patch = client.patch(
            "/api/v1/mangas/100", json={"status": "deleted"}, headers=headers
        )
        missing_patch = client.patch(
            "/api/v1/mangas/999", json={"title": "x"}, headers=headers
        )
        delete_response = client.delete("/api/v1/mangas/100", headers=headers)
        repeated_delete = client.delete("/api/v1/mangas/100", headers=headers)

    assert patch_response.status_code == 200
    assert patch_response.json()["title"] == "新标题"
    assert patch_response.json()["tags"] == ["冒险", "日常"]
    assert invalid_patch.status_code == 400
    assert invalid_patch.json()["code"] == "INVALID_MANGA_METADATA"
    assert missing_patch.status_code == 404
    assert delete_response.status_code == 200
    assert delete_response.json()["deleted"] is True
    assert delete_response.json()["deleted_file_count"] == 1
    assert not pdf_path.exists()
    assert repeated_delete.status_code == 404
    assert repeated_delete.json()["code"] == "MANGA_NOT_FOUND"

    audit_types = {
        event.event_type for event in AuditEventRepository(db_manager).list()
    }
    assert "manga.metadata_updated" in audit_types
    assert "manga.deleted" in audit_types


def test_manga_delete_conflict_and_batch_delete(db_manager) -> None:
    """正在下载的漫画删除应 409；批量删除返回逐项结果。"""
    root = Path(db_manager.db_dir).parent
    _add_manga(db_manager, root, "200")
    _add_manga(db_manager, root, "300")

    client, _context = _make_client(db_manager)
    with client:
        setup_and_login(client)
        headers = csrf_headers(client)
        request_response = client.post(
            "/api/v1/tasks/downloads",
            json={"manga_ids": ["200"]},
            headers=headers,
        )
        conflict = client.delete("/api/v1/mangas/200", headers=headers)
        batch = client.post(
            "/api/v1/mangas/batch-delete",
            json={"manga_ids": ["300", "200"]},
            headers=headers,
        )

    assert request_response.status_code == 202
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "MANGA_DOWNLOADING"
    assert batch.status_code == 200
    payload = batch.json()
    assert payload["succeeded_count"] == 1
    assert payload["failed_count"] == 1
    assert payload["items"][0]["manga_id"] == "300"
    assert payload["items"][0]["succeeded"] is True
    assert payload["items"][1]["error_code"] == "download_conflict"
    assert (root / "200-旧标题(1章).pdf").exists() is True
    assert (root / "300-旧标题(1章).pdf").exists() is False


def test_download_request_dedup_and_validation(db_manager) -> None:
    """下载请求应去重、返回既有任务并校验数量与格式。"""
    client, _context = _make_client(db_manager)
    with client:
        setup_and_login(client)
        headers = csrf_headers(client)

        created = client.post(
            "/api/v1/tasks/downloads",
            json={"manga_ids": ["101", "101", "102"]},
            headers=headers,
        )
        duplicated = client.post(
            "/api/v1/tasks/downloads",
            json={"manga_ids": ["101"]},
            headers=headers,
        )
        invalid_id = client.post(
            "/api/v1/tasks/downloads",
            json={"manga_ids": ["abc"]},
            headers=headers,
        )
        over_limit = client.post(
            "/api/v1/tasks/downloads",
            json={"manga_ids": [str(100000 + i) for i in range(21)]},
            headers=headers,
        )

    assert created.status_code == 202
    assert [item["manga_id"] for item in created.json()["items"]] == ["101", "102"]
    assert created.json()["queued_count"] == 2
    assert duplicated.status_code == 202
    assert duplicated.json()["items"][0]["status"] == "duplicate"
    assert duplicated.json()["items"][0]["task_id"] is not None
    assert invalid_id.status_code == 400
    assert invalid_id.json()["code"] == "INVALID_DOWNLOAD_REQUEST"
    assert over_limit.status_code == 422
    assert over_limit.json()["code"] == "VALIDATION_ERROR"


def test_task_cancel_endpoints(db_manager) -> None:
    """单个取消与全部取消应区分状态，并拒绝已开始任务。"""
    client, _context = _make_client(db_manager)
    with client:
        setup_and_login(client)
        headers = csrf_headers(client)
        client.post(
            "/api/v1/tasks/downloads",
            json={"manga_ids": ["101", "102"]},
            headers=headers,
        )
        tasks = {
            task.manga_id: task for task in OperationTaskRepository(db_manager).list()
        }
        first_cancel = client.post(
            f"/api/v1/tasks/{tasks['101'].id}/cancel", headers=headers
        )
        repeated_cancel = client.post(
            f"/api/v1/tasks/{tasks['101'].id}/cancel", headers=headers
        )
        missing_cancel = client.post(
            "/api/v1/tasks/missing-task/cancel", headers=headers
        )
        cancel_queued = client.post("/api/v1/tasks/cancel-queued", headers=headers)

    assert first_cancel.status_code == 200
    assert first_cancel.json()["cancelled"] is True
    assert repeated_cancel.status_code == 409
    assert repeated_cancel.json()["code"] == "TASK_NOT_QUEUED"
    assert missing_cancel.status_code == 404
    assert cancel_queued.status_code == 200
    assert cancel_queued.json()["cancelled_count"] == 1


def test_permission_endpoints_with_cached_identities(db_manager) -> None:
    """权限名单增删应幂等，并返回缓存的用户与群组。"""
    UserGroupRepository(db_manager).upsert_user("10001", "测试用户")
    UserGroupRepository(db_manager).upsert_group("20001", "测试群")

    client, _context = _make_client(db_manager)
    with client:
        setup_and_login(client)
        headers = csrf_headers(client)

        added = client.post(
            "/api/v1/permissions/private_whitelist",
            json={"value": "10001"},
            headers=headers,
        )
        duplicate = client.post(
            "/api/v1/permissions/private_whitelist",
            json={"value": "10001"},
            headers=headers,
        )
        invalid_scope = client.post(
            "/api/v1/permissions/unknown_scope",
            json={"value": "10001"},
            headers=headers,
        )
        listing = client.get("/api/v1/permissions")
        removed = client.delete(
            "/api/v1/permissions/private_whitelist/10001", headers=headers
        )
        removed_again = client.delete(
            "/api/v1/permissions/private_whitelist/10001", headers=headers
        )

    assert added.json()["changed"] is True
    assert duplicate.json()["changed"] is False
    assert invalid_scope.status_code == 400
    payload = listing.json()
    assert payload["scopes"]["private_whitelist"] == ["10001"]
    assert payload["cached_users"][0]["nickname"] == "测试用户"
    assert payload["cached_groups"][0]["group_name"] == "测试群"
    assert removed.json()["changed"] is True
    assert removed_again.json()["changed"] is False


def test_setting_endpoints_mask_and_update(db_manager) -> None:
    """设置接口应遮蔽敏感值，并拒绝只读、未知与非法值。"""
    client, context = _make_client(
        db_manager,
        config_dict={"NAPCAT_TOKEN": "super-secret", "FILE_SEND_INTERVAL": 1.8},
    )
    with client:
        setup_and_login(client)
        headers = csrf_headers(client)

        listing = client.get("/api/v1/settings")
        updated = client.patch(
            "/api/v1/settings/FILE_SEND_INTERVAL",
            json={"value": 2.5},
            headers=headers,
        )
        readonly = client.patch(
            "/api/v1/settings/NAPCAT_TOKEN",
            json={"value": "leak"},
            headers=headers,
        )
        unknown = client.patch(
            "/api/v1/settings/UNKNOWN_KEY", json={"value": 1}, headers=headers
        )
        invalid = client.patch(
            "/api/v1/settings/FILE_SEND_INTERVAL",
            json={"value": 999},
            headers=headers,
        )

    assert listing.status_code == 200
    assert "super-secret" not in listing.text
    token_view = next(
        item for item in listing.json()["items"] if item["key"] == "NAPCAT_TOKEN"
    )
    assert token_view["sensitive"] is True
    assert token_view["value"] is None
    assert token_view["is_set"] is True
    assert updated.status_code == 200
    assert updated.json()["value"] == 2.5
    assert context.applied_settings["FILE_SEND_INTERVAL"] == 2.5
    assert readonly.status_code == 200
    assert readonly.json()["value"] is None
    assert readonly.json()["restart_required"] is True
    assert "leak" not in readonly.text
    assert unknown.status_code == 404
    assert unknown.json()["code"] == "SETTING_NOT_FOUND"
    assert invalid.status_code == 400


def test_system_reconnect_and_shutdown(db_manager) -> None:
    """重连接口返回接受并写审计；关闭接口先返回再由后台任务触发。"""
    client, context = _make_client(db_manager)
    with client:
        setup_and_login(client)
        headers = csrf_headers(client)

        reconnect = client.post("/api/v1/system/napcat/reconnect", headers=headers)
        shutdown = client.post("/api/v1/system/shutdown", headers=headers)

    assert reconnect.status_code == 200
    assert reconnect.json() == {"accepted": True}
    assert context.reconnect_calls == [True]
    assert shutdown.status_code == 202
    assert shutdown.json() == {"shutdown": True}
    assert len(context.shutdown_calls) == 1
    audit_types = {
        event.event_type for event in AuditEventRepository(db_manager).list()
    }
    assert "napcat.reconnect_requested" in audit_types


def test_maintenance_scan_repair_and_backup(db_manager) -> None:
    """扫描、修复与备份接口应完成对应操作且不暴露绝对路径。"""
    root = Path(db_manager.db_dir).parent
    (root / "123456-扫描测试(2章).pdf").write_bytes(b"%PDF")
    MangaRepository(db_manager, download_root=str(root)).upsert(
        "999999", "孤儿漫画", "", 1, 0
    )

    client, _context = _make_client(db_manager)
    with client:
        setup_and_login(client)
        headers = csrf_headers(client)

        scan = client.post("/api/v1/maintenance/scan", headers=headers)
        repair = client.post("/api/v1/maintenance/repair", headers=headers)
        backup = client.post("/api/v1/maintenance/backups", headers=headers)
        backups = client.get("/api/v1/maintenance/backups")

    assert scan.status_code == 200
    assert scan.json()["new_count"] == 1
    assert scan.json()["scanned_files"] == 1
    assert repair.status_code == 200
    assert repair.json()["cleaned_count"] >= 1
    assert backup.status_code == 201
    assert backup.json()["filename"].startswith("main-")
    assert "path" not in backup.json()
    assert backups.status_code == 200
    assert backups.json()["total"] == 1
    assert "relative_path" not in backups.text
    assert "sha256" in backups.text

    audit_events = AuditEventRepository(db_manager).list()
    scan_events = [
        event for event in audit_events if event.event_type == "library.scan_requested"
    ]
    assert scan_events
    assert scan_events[0].source == "web"


def test_password_change_requires_old_password(db_manager) -> None:
    """修改密码必须校验旧密码，成功后旧会话失效。"""
    client, _context = _make_client(db_manager)
    with client:
        setup_and_login(client)
        headers = csrf_headers(client)

        wrong_old = client.put(
            "/api/v1/auth/password",
            json={
                "old_password": "wrong-password",
                "new_password": "new-password-1234",
            },
            headers=headers,
        )
        assert wrong_old.status_code == 400

        changed = client.put(
            "/api/v1/auth/password",
            json={
                "old_password": PASSWORD,
                "new_password": "new-password-1234",
            },
            headers=headers,
        )
        assert changed.status_code == 200
        assert client.get("/api/v1/system/status").status_code == 401
