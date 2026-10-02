"""阅读进度 API：读写、默认视图、页码校验与页数补齐测试。"""

from pathlib import Path

from starlette.testclient import TestClient

from src.database.repositories import MangaRepository
from tests.test_web.support import (
    build_web_context,
    create_test_client,
    csrf_headers,
    setup_and_login,
)


def _make_client(db_manager) -> tuple[TestClient, Path]:
    """构造测试客户端与临时下载根目录。"""
    root = Path(db_manager.db_dir).parent
    context = build_web_context(db_manager, root, root / "backups")
    return create_test_client(context.dependencies), root


def _add_manga_with_pdf(db_manager, root: Path, page_count: int = 10) -> int:
    """写入漫画记录与 PDF 文件，返回文件记录 ID。"""
    pdf_path = root / "100-测试漫画(1章).pdf"
    pdf_path.write_bytes(b"%PDF-1.4 progress test content")
    manga_repo = MangaRepository(db_manager, download_root=str(root))
    manga_repo.upsert("100", "测试漫画", "作者", 1, page_count)
    manga_file = manga_repo.add_file("100", str(pdf_path), page_count=page_count)
    return manga_file.id


def test_progress_requires_login_and_csrf(db_manager) -> None:
    """读取进度需登录；写入进度同时需要 CSRF 与登录。"""
    client, root = _make_client(db_manager)
    file_id = _add_manga_with_pdf(db_manager, root)

    with client:
        get_response = client.get(f"/api/v1/files/{file_id}/progress")
        # 缺少 CSRF Cookie/头：中间件先拒绝
        missing_csrf = client.put(
            f"/api/v1/files/{file_id}/progress",
            json={"page_number": 2, "page_count": 10},
        )
        # CSRF 通过但未登录：认证依赖返回 401
        client.cookies.set("jmbot_csrf", "csrf-token")
        unauthorized = client.put(
            f"/api/v1/files/{file_id}/progress",
            json={"page_number": 2, "page_count": 10},
            headers={"X-CSRF-Token": "csrf-token"},
        )

    assert get_response.status_code == 401
    assert get_response.json()["code"] == "AUTH_REQUIRED"
    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["code"] == "CSRF_FAILED"
    assert unauthorized.status_code == 401
    assert unauthorized.json()["code"] == "AUTH_REQUIRED"


def test_progress_unknown_file_returns_404(db_manager) -> None:
    """文件记录不存在时 GET 与 PUT 都返回 404，且不泄露内部路径。"""
    client, root = _make_client(db_manager)

    with client:
        setup_and_login(client)
        get_response = client.get("/api/v1/files/999999/progress")
        put_response = client.put(
            "/api/v1/files/999999/progress",
            json={"page_number": 1, "page_count": 10},
            headers=csrf_headers(client),
        )

    assert get_response.status_code == 404
    assert get_response.json()["code"] == "FILE_NOT_FOUND"
    assert put_response.status_code == 404
    assert put_response.json()["code"] == "FILE_NOT_FOUND"
    assert str(root) not in get_response.text
    assert str(root) not in put_response.text


def test_progress_default_view_without_record(db_manager) -> None:
    """无进度记录时返回默认视图：第 1 页、文件页数、0%、无更新时间。"""
    client, root = _make_client(db_manager)
    file_id = _add_manga_with_pdf(db_manager, root, page_count=12)

    with client:
        setup_and_login(client)
        response = client.get(f"/api/v1/files/{file_id}/progress")

    assert response.status_code == 200
    assert response.json() == {
        "file_id": file_id,
        "page_number": 1,
        "page_count": 12,
        "percent": 0.0,
        "updated_at": None,
    }


def test_progress_put_then_get_roundtrip(db_manager) -> None:
    """写入后读取应返回相同进度，percent 由页码计算。"""
    client, root = _make_client(db_manager)
    file_id = _add_manga_with_pdf(db_manager, root, page_count=8)

    with client:
        setup_and_login(client)
        put_response = client.put(
            f"/api/v1/files/{file_id}/progress",
            json={"page_number": 3, "page_count": 8},
            headers=csrf_headers(client),
        )
        get_response = client.get(f"/api/v1/files/{file_id}/progress")

    assert put_response.status_code == 200
    payload = put_response.json()
    assert payload["file_id"] == file_id
    assert payload["page_number"] == 3
    assert payload["page_count"] == 8
    assert payload["percent"] == 0.375
    assert payload["updated_at"] is not None
    assert get_response.json() == payload


def test_progress_validation_errors(db_manager) -> None:
    """总页数或页码越界必须返回 400 中文错误，不做静默修正。"""
    client, root = _make_client(db_manager)
    file_id = _add_manga_with_pdf(db_manager, root, page_count=10)

    with client:
        setup_and_login(client)
        headers = csrf_headers(client)
        zero_count = client.put(
            f"/api/v1/files/{file_id}/progress",
            json={"page_number": 1, "page_count": 0},
            headers=headers,
        )
        zero_page = client.put(
            f"/api/v1/files/{file_id}/progress",
            json={"page_number": 0, "page_count": 10},
            headers=headers,
        )
        overflow = client.put(
            f"/api/v1/files/{file_id}/progress",
            json={"page_number": 11, "page_count": 10},
            headers=headers,
        )

    for response in (zero_count, zero_page, overflow):
        assert response.status_code == 400
        assert response.json()["code"] == "INVALID_PROGRESS"
        assert response.json()["message"]


def test_progress_fills_zero_page_count(db_manager) -> None:
    """文件页数为 0 时应由 PDF.js 上报值补齐。"""
    client, root = _make_client(db_manager)
    file_id = _add_manga_with_pdf(db_manager, root, page_count=0)

    with client:
        setup_and_login(client)
        response = client.put(
            f"/api/v1/files/{file_id}/progress",
            json={"page_number": 5, "page_count": 12},
            headers=csrf_headers(client),
        )

    assert response.status_code == 200
    manga_repo = MangaRepository(db_manager, download_root=str(root))
    stored = manga_repo.get_file(file_id)
    assert stored is not None
    assert stored.page_count == 12


def test_progress_does_not_overwrite_existing_page_count(db_manager) -> None:
    """文件已有可信页数时上报不同页数不得覆盖。"""
    client, root = _make_client(db_manager)
    file_id = _add_manga_with_pdf(db_manager, root, page_count=10)

    with client:
        setup_and_login(client)
        client.put(
            f"/api/v1/files/{file_id}/progress",
            json={"page_number": 5, "page_count": 12},
            headers=csrf_headers(client),
        )

    manga_repo = MangaRepository(db_manager, download_root=str(root))
    stored = manga_repo.get_file(file_id)
    assert stored is not None
    assert stored.page_count == 10


def test_progress_update_is_idempotent(db_manager) -> None:
    """重复提交相同页码应成功且刷新更新时间，不产生重复记录。"""
    client, root = _make_client(db_manager)
    file_id = _add_manga_with_pdf(db_manager, root, page_count=10)

    with client:
        setup_and_login(client)
        headers = csrf_headers(client)
        first = client.put(
            f"/api/v1/files/{file_id}/progress",
            json={"page_number": 4, "page_count": 10},
            headers=headers,
        )
        second = client.put(
            f"/api/v1/files/{file_id}/progress",
            json={"page_number": 4, "page_count": 10},
            headers=headers,
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["page_number"] == 4
    assert second.json()["percent"] == 0.4
    # updated_at 为 ISO 8601 字符串，允许持平或前进
    assert second.json()["updated_at"] >= first.json()["updated_at"]


def test_progress_percent_boundaries(db_manager) -> None:
    """首尾页 percent 应为 1/N 与 1.0。"""
    client, root = _make_client(db_manager)
    file_id = _add_manga_with_pdf(db_manager, root, page_count=8)

    with client:
        setup_and_login(client)
        headers = csrf_headers(client)
        first_page = client.put(
            f"/api/v1/files/{file_id}/progress",
            json={"page_number": 1, "page_count": 8},
            headers=headers,
        )
        last_page = client.put(
            f"/api/v1/files/{file_id}/progress",
            json={"page_number": 8, "page_count": 8},
            headers=headers,
        )

    assert first_page.json()["percent"] == 0.125
    assert last_page.json()["percent"] == 1.0
