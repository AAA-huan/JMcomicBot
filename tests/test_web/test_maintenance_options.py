"""维护参数和漫画删除后查询的集成测试。"""

from pathlib import Path

from src.database.repositories import MangaRepository, OperationTaskRepository
from tests.test_web.support import create_client_for, csrf_headers, setup_and_login


def test_scan_and_repair_preview_do_not_write(db_manager, monkeypatch):
    """预览不创建任务或写入漫画，联网补全选项传递到共享扫描服务。"""
    root = Path(db_manager.db_dir).parent
    (root / "100-扫描测试(1章).pdf").write_bytes(b"%PDF")
    mangas = MangaRepository(db_manager, str(root))
    mangas.upsert("200", "孤儿", "", 1, 0)
    calls = []

    def enrich(entries):
        calls.append([entry.manga_id for entry in entries])
        return len(entries)

    monkeypatch.setattr("src.service.scan_service.enrich_metadata_from_jmcomic", enrich)
    client, _context = create_client_for(db_manager)
    with client:
        setup_and_login(client)
        headers = csrf_headers(client)
        scan = client.post(
            "/api/v1/maintenance/scan",
            json={"dry_run": True, "enrich": True},
            headers=headers,
        )
        assert scan.status_code == 200
        assert scan.json()["dry_run"] is True
        assert scan.json()["task_id"] is None
        assert scan.json()["new_count"] == 1
        assert scan.json()["pending_cleanup_count"] == 1
        assert calls == [["100"]]
        repair = client.post(
            "/api/v1/maintenance/repair", json={"dry_run": True}, headers=headers
        )
        assert repair.status_code == 200
        assert repair.json()["orphan_manga_ids"] == ["200"]
    assert mangas.get("100") is None
    assert mangas.get("200").status == "downloaded"
    assert OperationTaskRepository(db_manager).list() == []


def test_verify_all_and_conflict_checks(db_manager):
    """全部校验可不指定 ID，也会拒绝活动下载中的登记文件。"""
    root = Path(db_manager.db_dir).parent
    mangas = MangaRepository(db_manager, str(root))
    for manga_id in ("100", "200"):
        mangas.upsert(manga_id, "校验测试", "", 1, 1)
        path = root / f"{manga_id}.pdf"
        path.write_bytes(b"%PDF")
        mangas.add_file(manga_id, str(path))
    client, _context = create_client_for(db_manager)
    with client:
        setup_and_login(client)
        headers = csrf_headers(client)
        result = client.post(
            "/api/v1/maintenance/verify", json={"manga_ids": None}, headers=headers
        )
        assert result.status_code == 200
        assert result.json()["ready_count"] == 2
        client.post(
            "/api/v1/tasks/downloads", json={"manga_ids": ["100"]}, headers=headers
        )
        assert (
            client.post(
                "/api/v1/maintenance/verify", json={}, headers=headers
            ).status_code
            == 409
        )


def test_deleted_filter_survives_maintenance_and_redownload(db_manager):
    """删除保留元数据，扫描修复不会改成缺失，重新下载可恢复。"""
    root = Path(db_manager.db_dir).parent
    mangas = MangaRepository(db_manager, str(root))
    mangas.upsert("100", "已删除漫画", "作者", 1, 10)
    file = root / "100-已删除漫画(1章).pdf"
    file.write_bytes(b"%PDF")
    mangas.add_file("100", str(file))
    client, _context = create_client_for(db_manager)
    with client:
        setup_and_login(client)
        headers = csrf_headers(client)
        assert client.delete("/api/v1/mangas/100", headers=headers).status_code == 200
        assert client.get("/api/v1/mangas").json()["total"] == 0
        assert mangas.count() == 0
        deleted = client.get("/api/v1/mangas?status=deleted").json()
        assert deleted["total"] == 1
        assert deleted["items"][0]["title"] == "已删除漫画"
        assert deleted["items"][0]["files"] == []
        assert client.get("/api/v1/mangas/100").json()["status"] == "deleted"
        assert (
            client.put("/api/v1/mangas/100/favorite", headers=headers).status_code
            == 404
        )
        # 非空目录扫描，确认不会把已删除记录重新标记为缺失。
        (root / "200-本地漫画(1章).pdf").write_bytes(b"%PDF")
        assert (
            client.post("/api/v1/maintenance/scan", headers=headers).status_code == 200
        )
        repair = client.post(
            "/api/v1/maintenance/repair", json={"dry_run": True}, headers=headers
        )
        assert "100" not in repair.json()["orphan_manga_ids"]
        assert (
            client.post("/api/v1/maintenance/repair", headers=headers).status_code
            == 200
        )
        assert client.get("/api/v1/mangas?status=deleted").json()["total"] == 1
        mangas.upsert("100", "重新下载漫画", "作者", 1, 10)
        file.write_bytes(b"%PDF")
        mangas.add_file("100", str(file))
        assert client.get("/api/v1/mangas?status=deleted").json()["total"] == 0
        assert client.get("/api/v1/mangas/100").json()["status"] == "downloaded"
