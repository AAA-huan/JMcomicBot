"""数据导出/导入接口：认证、CSRF、校验与重启对接测试。"""

from io import BytesIO
from pathlib import Path
import sqlite3
from zipfile import ZipFile

from starlette.testclient import TestClient

from src.database.repositories import MangaRepository
from tests.test_web.support import (
    create_client_for,
    csrf_headers,
    setup_and_login,
)


def _export_zip(client: TestClient) -> bytes:
    """通过接口导出数据包并返回原始字节。"""
    response = client.post(
        "/api/v1/maintenance/data-export", headers=csrf_headers(client)
    )
    assert response.status_code == 200
    return response.content


def test_data_export_requires_login_and_returns_zip(db_manager) -> None:
    """未登录拒绝导出；登录后返回 zip 附件并写导出审计。"""
    client, _context = create_client_for(db_manager)
    with client:
        # 先带上自建 CSRF 对，验证未登录时由认证依赖返回 401
        unauthorized = client.post(
            "/api/v1/maintenance/data-export",
            headers={
                "Cookie": "jmbot_csrf=csrf-check",
                "X-CSRF-Token": "csrf-check",
            },
        )
        setup_and_login(client)
        response = client.post(
            "/api/v1/maintenance/data-export", headers=csrf_headers(client)
        )

    assert unauthorized.status_code == 401
    assert unauthorized.json()["code"] == "AUTH_REQUIRED"
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "attachment" in response.headers["content-disposition"]
    assert "data-export-" in response.headers["content-disposition"]
    assert response.headers["x-content-type-options"] == "nosniff"
    with ZipFile(BytesIO(response.content)) as archive:
        assert "export.json" in archive.namelist()
        assert len(archive.namelist()) == 2


def test_data_import_validate_and_apply_flow(db_manager, tmp_path) -> None:
    """上传校验返回预览，确认后替换整库并在响应后触发重启。"""
    mangas = MangaRepository(db_manager, str(tmp_path / "downloads"))
    mangas.upsert("100", "导出时漫画", "作者", 1, 10)
    client, context = create_client_for(db_manager)

    with client:
        setup_and_login(client)
        headers = csrf_headers(client)
        export_bytes = _export_zip(client)

        files = {"file": ("data.zip", export_bytes, "application/zip")}
        preview = client.post(
            "/api/v1/maintenance/data-import/validate",
            files=files,
            headers=headers,
        )
        assert preview.status_code == 200
        assert (
            preview.json()["schema_revision"]
            == "0030_add_reading_setting_prefetch_pages"
        )
        assert preview.json()["table_counts"]["manga"] == 1
        assert preview.json()["path_warnings"] == []

        mangas.upsert("200", "导入前新增", "作者", 1, 10)
        applied = client.post(
            "/api/v1/maintenance/data-import?confirm=1",
            files=files,
            headers=headers,
        )

    assert applied.status_code == 202
    assert applied.json() == {"restart": True}
    assert len(context.restart_calls) == 1
    reloaded = MangaRepository(db_manager, str(tmp_path / "downloads"))
    assert reloaded.get("100").title == "导出时漫画"
    assert reloaded.get("200") is None

    backup_path = next(Path(db_manager.db_dir).glob("main.db.pre-import-*.bak"))
    connection = sqlite3.connect(backup_path)
    try:
        event_types = {
            row[0] for row in connection.execute("SELECT event_type FROM audit_event")
        }
    finally:
        connection.close()
    assert "data.imported" in event_types


def test_data_import_requires_confirm_and_csrf(db_manager, tmp_path) -> None:
    """缺少确认参数或 CSRF 头时拒绝执行替换。"""
    mangas = MangaRepository(db_manager, str(tmp_path / "downloads"))
    mangas.upsert("100", "原始漫画", "作者", 1, 10)
    client, context = create_client_for(db_manager)

    with client:
        setup_and_login(client)
        headers = csrf_headers(client)
        export_bytes = _export_zip(client)
        files = {"file": ("data.zip", export_bytes, "application/zip")}
        no_confirm = client.post(
            "/api/v1/maintenance/data-import",
            files=files,
            headers=headers,
        )
        no_csrf = client.post(
            "/api/v1/maintenance/data-import?confirm=1",
            files=files,
        )

    assert no_confirm.status_code == 400
    assert no_confirm.json()["code"] == "DATA_IMPORT_CONFIRM_REQUIRED"
    assert no_csrf.status_code == 403
    assert no_csrf.json()["code"] == "CSRF_FAILED"
    assert context.restart_calls == []
    assert mangas.get("100") is not None


def test_data_import_validate_reports_invalid_package(db_manager) -> None:
    """结构错误的 zip 返回 400 DATA_IMPORT_INVALID，不触发重启。"""
    client, context = create_client_for(db_manager)
    with client:
        setup_and_login(client)
        response = client.post(
            "/api/v1/maintenance/data-import/validate",
            files={"file": ("data.zip", b"not a zip", "application/zip")},
            headers=csrf_headers(client),
        )

    assert response.status_code == 400
    assert response.json()["code"] == "DATA_IMPORT_INVALID"
    assert context.restart_calls == []
