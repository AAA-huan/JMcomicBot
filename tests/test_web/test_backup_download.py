"""备份下载接口：认证、响应头、路径与文件安全测试。"""

from pathlib import Path

from starlette.testclient import TestClient

from tests.test_web.support import (
    build_web_context,
    create_test_client,
    csrf_headers,
    setup_and_login,
)


def _make_client(db_manager):
    """构造备份下载测试客户端与上下文。"""
    root = Path(db_manager.db_dir).parent
    context = build_web_context(db_manager, root, root / "backups")
    return create_test_client(context.dependencies), context


def _create_backup(client: TestClient) -> dict:
    """通过真实接口创建一致性备份。"""
    response = client.post("/api/v1/maintenance/backups", headers=csrf_headers(client))
    assert response.status_code == 201
    return response.json()


def test_backup_download_requires_login(db_manager) -> None:
    """未登录访问备份下载必须返回 401。"""
    client, _context = _make_client(db_manager)
    with client:
        response = client.get("/api/v1/maintenance/backups/1/download")

    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_REQUIRED"


def test_backup_download_returns_file_with_safe_headers(db_manager) -> None:
    """下载已登记备份应返回附件、禁止嗅探且内容为 SQLite 文件。"""
    client, _context = _make_client(db_manager)
    with client:
        setup_and_login(client)
        created = _create_backup(client)
        response = client.get(
            f"/api/v1/maintenance/backups/{created['backup_id']}/download"
        )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/octet-stream"
    assert "attachment" in response.headers["content-disposition"]
    assert created["filename"] in response.headers["content-disposition"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.content.startswith(b"SQLite format 3\x00")


def test_backup_download_rejects_unknown_and_not_ready(db_manager) -> None:
    """不存在的记录与不可下载状态统一返回 404，不泄露内部原因。"""
    client, context = _make_client(db_manager)
    repo = context.dependencies.database_maintenance_service.backup_repo
    failed = repo.create(
        filename="failed.db", relative_path="failed.db", schema_version="0002"
    )
    repo.mark_failed(failed.id)

    with client:
        setup_and_login(client)
        missing = client.get("/api/v1/maintenance/backups/999999/download")
        not_ready = client.get(f"/api/v1/maintenance/backups/{failed.id}/download")

    assert missing.status_code == 404
    assert missing.json()["code"] == "BACKUP_NOT_FOUND"
    assert not_ready.status_code == 404
    assert not_ready.json()["code"] == "BACKUP_NOT_FOUND"


def test_backup_download_rejects_path_escape_and_missing_file(db_manager) -> None:
    """越界相对路径、符号链接逃逸与文件丢失都必须被拒绝且不泄露路径。"""
    client, context = _make_client(db_manager)
    root = Path(db_manager.db_dir).parent
    service = context.dependencies.database_maintenance_service
    repo = service.backup_repo

    # 模拟数据库记录被篡改为越界相对路径
    outside = root / "outside.db"
    outside.write_bytes(b"SQLite format 3\x00")
    escape = repo.create(
        filename="escape.db", relative_path="../outside.db", schema_version="0002"
    )
    repo.mark_ready(escape.id, file_size_bytes=outside.stat().st_size, sha256="x")

    # 备份目录内的符号链接指向目录之外
    backup_dir = service.backup_dir
    backup_dir.mkdir(parents=True, exist_ok=True)
    link = backup_dir / "link.db"
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(outside)
    symlink = repo.create(
        filename="link.db", relative_path="link.db", schema_version="0002"
    )
    repo.mark_ready(symlink.id, file_size_bytes=1, sha256="x")

    # 记录存在但文件已丢失
    missing = repo.create(
        filename="missing.db", relative_path="missing.db", schema_version="0002"
    )
    repo.mark_ready(missing.id, file_size_bytes=1, sha256="x")

    with client:
        setup_and_login(client)
        escape_response = client.get(
            f"/api/v1/maintenance/backups/{escape.id}/download"
        )
        symlink_response = client.get(
            f"/api/v1/maintenance/backups/{symlink.id}/download"
        )
        missing_response = client.get(
            f"/api/v1/maintenance/backups/{missing.id}/download"
        )

    assert escape_response.status_code == 500
    assert escape_response.json()["code"] == "BACKUP_PATH_INVALID"
    assert symlink_response.status_code == 500
    assert symlink_response.json()["code"] == "BACKUP_PATH_INVALID"
    assert missing_response.status_code == 404
    assert missing_response.json()["code"] == "BACKUP_FILE_MISSING"
    # 错误响应不得出现绝对路径
    assert str(root) not in escape_response.text
    assert str(root) not in missing_response.text
