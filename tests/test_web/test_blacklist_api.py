"""漫画黑名单 Web API 集成测试。"""

from pathlib import Path

from starlette.testclient import TestClient

from src.database.database import DatabaseManager
from src.database.repositories import (
    AuditEventRepository,
    MangaBlacklistRepository,
    MangaRepository,
    OperationTaskRepository,
)
from tests.test_web.support import (
    build_web_context,
    create_test_client,
    csrf_headers,
    setup_and_login,
)


def _make_client(
    db_manager: DatabaseManager, config_dict=None
) -> tuple[TestClient, object]:
    """构造黑名单接口测试客户端与可观测上下文。"""
    root = Path(db_manager.db_dir).parent
    context = build_web_context(db_manager, root, config_dict=config_dict)
    return create_test_client(context.dependencies), context


def _add_manga(
    db_manager: DatabaseManager, root: Path, manga_id: str, title: str = "标题"
) -> Path:
    """写入漫画元数据、PDF 文件与文件记录。"""
    pdf_path = root / f"{manga_id}-{title}(1章).pdf"
    pdf_path.write_bytes(b"%PDF")
    manga_repo = MangaRepository(db_manager, download_root=str(root))
    manga_repo.upsert(manga_id, title, "作者", 1, 10)
    manga_repo.add_file(manga_id, str(pdf_path))
    return pdf_path


def test_blacklist_api_requires_login_and_csrf(db_manager) -> None:
    """黑名单写接口必须经过登录与 CSRF 校验。"""
    client, _context = _make_client(db_manager)
    with client:
        assert client.get("/api/v1/mangas/blacklist").status_code == 401
        assert client.post("/api/v1/mangas/100/blacklist").status_code == 403
        client.cookies.set("jmbot_csrf", "csrf-token")
        response = client.post(
            "/api/v1/mangas/100/blacklist",
            headers={"X-CSRF-Token": "csrf-token"},
        )
        assert response.status_code == 401
        assert response.json()["code"] == "AUTH_REQUIRED"


def test_single_blacklist_flow_and_download_skip(db_manager) -> None:
    """单条拉黑、列表、列表项状态、下载跳过与解除形成闭环。"""
    root = Path(db_manager.db_dir).parent
    pdf_path = _add_manga(db_manager, root, "100", "会被拉黑")
    _add_manga(db_manager, root, "101", "正常漫画")

    client, context = _make_client(db_manager)
    with client:
        setup_and_login(client)
        headers = csrf_headers(client)

        before = client.get("/api/v1/mangas/100")
        added = client.post(
            "/api/v1/mangas/100/blacklist",
            json={"reason": "测试原因"},
            headers=headers,
        )
        duplicated = client.post(
            "/api/v1/mangas/100/blacklist",
            json={"reason": "重复原因"},
            headers=headers,
        )
        listing = client.get("/api/v1/mangas/blacklist?search=拉黑")
        filtered = client.get("/api/v1/mangas?blacklist_only=true")
        detail = client.get("/api/v1/mangas/100")
        download = client.post(
            "/api/v1/tasks/downloads",
            json={"manga_ids": ["100", "101"]},
            headers=headers,
        )
        removed = client.delete("/api/v1/mangas/100/blacklist", headers=headers)
        removed_again = client.delete("/api/v1/mangas/100/blacklist", headers=headers)
        detail_after = client.get("/api/v1/mangas/100")

    assert before.status_code == 200
    assert before.json()["is_blacklisted"] is False
    assert added.status_code == 200
    assert added.json()["changed"] is True
    assert added.json()["status"] == "blacklisted"
    assert added.json()["deleted"] is False
    assert duplicated.status_code == 200
    assert duplicated.json()["changed"] is False
    assert duplicated.json()["status"] == "already_blacklisted"
    assert listing.json()["total"] == 1
    assert listing.json()["items"][0]["manga_id"] == "100"
    assert listing.json()["items"][0]["title"] == "会被拉黑"
    assert listing.json()["items"][0]["reason"] == "测试原因"
    assert filtered.json()["total"] == 1
    assert filtered.json()["items"][0]["id"] == "100"
    assert filtered.json()["items"][0]["is_blacklisted"] is True
    assert detail.json()["is_blacklisted"] is True
    assert download.status_code == 202
    assert download.json()["skipped_blacklisted"] == ["100"]
    assert download.json()["queued_count"] == 1
    assert [item["manga_id"] for item in download.json()["items"]] == ["101"]
    assert context.download_queue.requested_manga_ids == ["101"]
    assert removed.json()["changed"] is True
    assert removed.json()["status"] == "unblacklisted"
    assert removed_again.json()["changed"] is False
    assert removed_again.json()["status"] == "not_blacklisted"
    assert detail_after.json()["is_blacklisted"] is False
    # 默认关闭删除绑定：拉黑与解除均不影响 PDF 和漫画状态。
    assert pdf_path.exists()
    manga = MangaRepository(db_manager).get("100")
    assert manga is not None
    assert manga.status == "downloaded"

    audit_types = {
        event.event_type
        for event in AuditEventRepository(db_manager).list(page_size=100)
    }
    assert "manga.blacklisted" in audit_types
    assert "manga.unblacklisted" in audit_types
    tasks = OperationTaskRepository(db_manager).search(1, 20, task_type="blacklist")[0]
    assert len(tasks) == 2
    assert {task.source for task in tasks} == {"web"}
    assert {task.status for task in tasks} == {"succeeded"}


def test_batch_blacklist_and_unblacklist(db_manager) -> None:
    """批量拉黑/解除去重，并返回逐项与汇总结果。"""
    root = Path(db_manager.db_dir).parent
    _add_manga(db_manager, root, "100")
    _add_manga(db_manager, root, "101")
    client, _context = _make_client(db_manager)
    with client:
        setup_and_login(client)
        headers = csrf_headers(client)

        added = client.post(
            "/api/v1/mangas/blacklist:batch",
            json={"manga_ids": ["100", "101", "100"], "reason": "批量"},
            headers=headers,
        )
        repeated = client.post(
            "/api/v1/mangas/blacklist:batch",
            json={"manga_ids": ["100"]},
            headers=headers,
        )
        listed = client.get("/api/v1/mangas?blacklist_only=true")
        removed = client.request(
            "DELETE",
            "/api/v1/mangas/blacklist:batch",
            json={"manga_ids": ["100", "101", "100"]},
            headers=headers,
        )
        removed_again = client.request(
            "DELETE",
            "/api/v1/mangas/blacklist:batch",
            json={"manga_ids": ["100"]},
            headers=headers,
        )

    assert added.status_code == 200
    assert [item["manga_id"] for item in added.json()["items"]] == ["100", "101"]
    assert added.json()["changed_count"] == 2
    assert added.json()["unchanged_count"] == 0
    assert repeated.json()["changed_count"] == 0
    assert repeated.json()["unchanged_count"] == 1
    assert listed.json()["total"] == 2
    assert {item["id"] for item in listed.json()["items"]} == {"100", "101"}
    assert removed.status_code == 200
    assert [item["manga_id"] for item in removed.json()["items"]] == ["100", "101"]
    assert removed.json()["changed_count"] == 2
    assert removed_again.json()["changed_count"] == 0
    assert removed_again.json()["unchanged_count"] == 1


def test_blacklist_validation_and_missing_records(db_manager) -> None:
    """非法 ID、空列表、超长原因与不存在漫画均应明确响应。"""
    client, _context = _make_client(db_manager)
    with client:
        setup_and_login(client)
        headers = csrf_headers(client)

        invalid_single = client.post(
            "/api/v1/mangas/abc/blacklist", json={}, headers=headers
        )
        invalid_batch = client.post(
            "/api/v1/mangas/blacklist:batch",
            json={"manga_ids": ["100", "abc"]},
            headers=headers,
        )
        empty_batch = client.post(
            "/api/v1/mangas/blacklist:batch", json={"manga_ids": []}, headers=headers
        )
        long_reason = client.post(
            "/api/v1/mangas/100/blacklist",
            json={"reason": "a" * 256},
            headers=headers,
        )
        over_limit = client.post(
            "/api/v1/mangas/blacklist:batch",
            json={"manga_ids": [str(1000 + index) for index in range(101)]},
            headers=headers,
        )
        missing_metadata = client.post(
            "/api/v1/mangas/999/blacklist", json={}, headers=headers
        )
        missing_filtered = client.get("/api/v1/mangas?blacklist_only=true")

    assert invalid_single.status_code == 400
    assert invalid_single.json()["code"] == "INVALID_BLACKLIST_REQUEST"
    assert invalid_batch.status_code == 400
    assert empty_batch.status_code == 422
    assert long_reason.status_code == 422
    assert over_limit.status_code == 422
    # 黑名单允许尚未下载的漫画，但漫画库筛选只能展示存在元数据的记录。
    assert missing_metadata.status_code == 200
    assert missing_metadata.json()["status"] == "blacklisted"
    assert missing_filtered.json()["total"] == 0


def test_binding_mode_deletes_on_blacklist_and_lists_deleted(db_manager) -> None:
    """绑定模式下 Web 拉黑同步删除，黑名单筛选仍能展示已删除漫画。"""
    root = Path(db_manager.db_dir).parent
    pdf_path = _add_manga(db_manager, root, "100", "绑定删除")
    client, _context = _make_client(
        db_manager, config_dict={"BLACKLIST_DELETE_BINDING": True}
    )
    with client:
        setup_and_login(client)
        headers = csrf_headers(client)
        added = client.post("/api/v1/mangas/100/blacklist", json={}, headers=headers)
        filtered = client.get("/api/v1/mangas?blacklist_only=true")
        audit_types = {
            event.event_type
            for event in AuditEventRepository(db_manager).list(page_size=100)
        }

    assert added.json()["deleted"] is True
    assert pdf_path.exists() is False
    manga = MangaRepository(db_manager).get("100", include_deleted=True)
    assert manga is not None
    assert manga.status == "deleted"
    assert filtered.json()["total"] == 1
    assert filtered.json()["items"][0]["id"] == "100"
    assert filtered.json()["items"][0]["status"] == "deleted"
    assert filtered.json()["items"][0]["is_blacklisted"] is True
    assert "manga.deleted" in audit_types
    assert "manga.blacklisted" in audit_types


def test_blacklist_list_includes_record_without_manga(db_manager) -> None:
    """专用黑名单列表使用 LEFT JOIN，保留无漫画元数据的记录。"""
    MangaBlacklistRepository(db_manager).add("999", "未下载", None, "system", None)
    client, _context = _make_client(db_manager)
    with client:
        setup_and_login(client)
        listing = client.get("/api/v1/mangas/blacklist")

    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    assert listing.json()["items"][0]["manga_id"] == "999"
    assert listing.json()["items"][0]["title"] is None
