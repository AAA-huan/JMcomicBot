"""收藏与 QQ 关联接口的认证、CSRF、幂等和分页集成测试。"""

from pathlib import Path

from src.database.repositories import (
    AuditEventRepository,
    FavoriteRepository,
    MangaRepository,
)
from tests.test_web.support import create_client_for, csrf_headers, setup_and_login


def test_favorites_filter_pagination_isolation_and_audit(db_manager):
    """收藏筛选先于分页，QQ 收藏不混入 WebUI 账户。"""
    mangas = MangaRepository(db_manager)
    for manga_id in ["100", "200", "300"]:
        mangas.upsert(manga_id, "漫画" + manga_id, "作者", 1, 1)
    favorites = FavoriteRepository(db_manager)
    favorites.set_favorite("qq", "12345", "300", True)
    client, _ = create_client_for(db_manager)
    with client:
        assert client.get("/api/v1/mangas?favorite_only=true").status_code == 401
        setup_and_login(client)
        headers = csrf_headers(client)
        assert client.put("/api/v1/mangas/100/favorite").status_code == 403
        for manga_id in ["100", "200"]:
            path = f"/api/v1/mangas/{manga_id}/favorite"
            assert client.put(path, headers=headers).json()["changed"]
            assert not client.put(path, headers=headers).json()["changed"]
        first = client.get(
            "/api/v1/mangas?favorite_only=true&page_size=1&sort=id_asc"
        ).json()
        second = client.get(
            "/api/v1/mangas?favorite_only=true&page_size=1&page=2&sort=id_asc"
        ).json()
        assert first["total"] == first["pages"] == 2
        assert first["items"][0]["id"] == "100"
        assert first["items"][0]["is_favorite"]
        assert second["items"][0]["id"] == "200"
        assert client.get("/api/v1/mangas/100").json()["is_favorite"]
        assert not client.get("/api/v1/mangas/300").json()["is_favorite"]
        assert (
            client.get("/api/v1/mangas?favorite_only=true&search=300").json()["total"]
            == 0
        )
        assert client.get("/api/v1/mangas?favorite_only=notbool").status_code == 422
        assert (
            client.put("/api/v1/mangas/404/favorite", headers=headers).status_code
            == 404
        )
        assert (
            client.delete("/api/v1/mangas/404/favorite", headers=headers).status_code
            == 404
        )
        assert client.delete("/api/v1/mangas/100/favorite", headers=headers).json()[
            "changed"
        ]
        assert not client.delete("/api/v1/mangas/100/favorite", headers=headers).json()[
            "changed"
        ]
        assert client.get("/api/v1/mangas?favorite_only=true").json()["total"] == 1
    assert favorites.get("qq", "12345", "300") is not None
    audit = [
        event
        for event in AuditEventRepository(db_manager).list()
        if event.event_type == "favorite.changed"
    ]
    assert len(audit) == 3
    assert all(event.source == "web" for event in audit)


def test_admin_qq_login_csrf_invalid_values_and_binding(db_manager):
    """关联仅能通过认证 WebUI，重复请求不重复授权或审计。"""
    client, context = create_client_for(db_manager)
    with client:
        path = "/api/v1/permissions/admin-qq"
        assert client.get(path).status_code == 401
        assert client.put(path, json={"qq_id": "12345"}).status_code == 403
        setup_and_login(client)
        headers = csrf_headers(client)
        assert client.get(path).json() == {"qq_id": None}
        assert client.put(path, json={"qq_id": "12345"}).status_code == 403
        for invalid in ["0", "00123", "123 45", "abc", "１２３"]:
            assert (
                client.put(path, json={"qq_id": invalid}, headers=headers).status_code
                == 400
            )
        assert (
            client.put(path, json={"qq_id": None}, headers=headers).status_code == 422
        )
        assert client.put(path, json={"qq_id": "12345"}, headers=headers).json()[
            "changed"
        ]
        assert not client.put(path, json={"qq_id": "12345"}, headers=headers).json()[
            "changed"
        ]
        manager = context.dependencies.permission_service.permission_manager
        assert manager.is_admin("12345")
        assert manager.check_delete_permission("12345")
        # 更换关联不改变管理员收藏。
        MangaRepository(db_manager).upsert("100", "漫画", "", 1, 1)
        client.put("/api/v1/mangas/100/favorite", headers=headers)
        assert client.put(path, json={"qq_id": "67890"}, headers=headers).json()[
            "changed"
        ]
        assert not manager.is_admin("12345")
        assert manager.is_admin("67890")
        assert client.get("/api/v1/mangas/100").json()["is_favorite"]
        manager.add_to_scope("global_blacklist", "99999")
        assert (
            client.put(path, json={"qq_id": "99999"}, headers=headers).status_code
            == 400
        )
        assert client.get(path).json()["qq_id"] == "67890"
        assert client.delete(path).status_code == 403
        assert client.delete(path, headers=headers).json()["changed"]
        assert not client.delete(path, headers=headers).json()["changed"]
        assert not manager.is_admin("67890")
        assert client.get("/api/v1/auth/me").status_code == 200
    audit = [
        event
        for event in AuditEventRepository(db_manager).list()
        if event.event_type == "admin.qq.changed"
    ]
    assert len(audit) == 3


def test_delete_admin_favorite_requires_web_admin_to_unfavorite(db_manager):
    """单个和批量删除不可直接绕过保护，只有管理员取消收藏后才可删除。"""
    root = Path(db_manager.db_dir).parent
    mangas = MangaRepository(db_manager, str(root))
    for manga_id in ["100", "200"]:
        pdf = root / f"{manga_id}.pdf"
        pdf.write_bytes(b"%PDF")
        mangas.upsert(manga_id, "漫画", "", 1, 1)
        mangas.add_file(manga_id, str(pdf))
    client, _context = create_client_for(db_manager)
    with client:
        setup_and_login(client)
        headers = csrf_headers(client)
        client.put("/api/v1/mangas/100/favorite", headers=headers)
        rejected = client.delete("/api/v1/mangas/100", headers=headers)
        assert rejected.status_code == 409
        assert rejected.json()["code"] == "MANGA_ADMIN_FAVORITE"
        assert "不能删除" in rejected.json()["message"]
        result = client.post(
            "/api/v1/mangas/batch-delete",
            json={"manga_ids": ["100", "200"]},
            headers=headers,
        ).json()
        assert result["failed_count"] == result["succeeded_count"] == 1
        assert result["items"][0]["error_code"] == "admin_favorite"
        assert "不能删除" in result["items"][0]["error_message"]
        assert (root / "100.pdf").exists()
        assert client.get("/api/v1/mangas/100").json()["is_favorite"]
        client.delete("/api/v1/mangas/100/favorite", headers=headers)
        assert client.delete("/api/v1/mangas/100", headers=headers).status_code == 200
        assert not (root / "100.pdf").exists()
