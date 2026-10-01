"""漫画 PDF 下载接口：认证、响应头与路径安全测试。"""

from pathlib import Path

from starlette.testclient import TestClient

from src.database.models import MangaFile
from src.database.repositories import MangaRepository
from tests.test_web.support import (
    build_web_context,
    create_test_client,
    setup_and_login,
)


def _make_client(db_manager) -> tuple[TestClient, Path]:
    """构造测试客户端与临时下载根目录。"""
    root = Path(db_manager.db_dir).parent
    context = build_web_context(db_manager, root, root / "backups")
    return create_test_client(context.dependencies), root


def _add_manga_with_pdf(
    db_manager, root: Path, manga_id: str = "100"
) -> tuple[int, Path]:
    """写入漫画记录与 PDF 文件，返回文件记录 ID 与文件路径。"""
    pdf_path = root / f"{manga_id}-测试漫画(1章).pdf"
    pdf_path.write_bytes(b"%PDF-1.4 test content")
    manga_repo = MangaRepository(db_manager, download_root=str(root))
    manga_repo.upsert(manga_id, "测试漫画", "作者", 1, 10)
    manga_file = manga_repo.add_file(manga_id, str(pdf_path))
    return manga_file.id, pdf_path


def _set_relative_path(db_manager, file_id: int, relative_path: str) -> None:
    """模拟数据库记录被篡改或修复流程更新相对路径。"""
    with db_manager.get_session() as session:
        record = session.get(MangaFile, file_id)
        assert record is not None
        record.relative_path = relative_path
        session.commit()


def test_file_download_requires_login(db_manager) -> None:
    """未登录访问文件下载必须返回 401。"""
    client, root = _make_client(db_manager)
    file_id, _pdf_path = _add_manga_with_pdf(db_manager, root)

    with client:
        response = client.get(f"/api/v1/files/{file_id}/content")

    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_REQUIRED"


def test_file_download_returns_pdf_with_safe_headers(db_manager) -> None:
    """下载已登记文件应返回 PDF 附件且禁止嗅探。"""
    client, root = _make_client(db_manager)
    file_id, _pdf_path = _add_manga_with_pdf(db_manager, root)

    with client:
        setup_and_login(client)
        response = client.get(f"/api/v1/files/{file_id}/content")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    disposition = response.headers["content-disposition"]
    assert "attachment" in disposition
    assert ".pdf" in disposition
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.content == b"%PDF-1.4 test content"


def test_file_download_rejects_unknown_and_missing_file(db_manager) -> None:
    """不存在的文件记录与磁盘缺失文件都返回 404，不泄露内部路径。"""
    client, root = _make_client(db_manager)
    file_id, pdf_path = _add_manga_with_pdf(db_manager, root)

    with client:
        setup_and_login(client)
        unknown = client.get("/api/v1/files/999999/content")
        pdf_path.unlink()
        missing = client.get(f"/api/v1/files/{file_id}/content")

    assert unknown.status_code == 404
    assert unknown.json()["code"] == "FILE_NOT_FOUND"
    assert missing.status_code == 404
    assert missing.json()["code"] == "FILE_MISSING"
    assert str(root) not in missing.text


def test_file_download_rejects_path_escape_symlink_and_non_pdf(db_manager) -> None:
    """越界相对路径、符号链接逃逸与非 PDF 扩展名都必须被拒绝。"""
    client, root = _make_client(db_manager)
    file_id, _pdf_path = _add_manga_with_pdf(db_manager, root)

    outside = root.parent / "outside.pdf"
    outside.write_bytes(b"%PDF-1.4 outside")

    with client:
        setup_and_login(client)

        # 越界相对路径
        _set_relative_path(db_manager, file_id, "../outside.pdf")
        escape = client.get(f"/api/v1/files/{file_id}/content")
        assert escape.status_code == 500
        assert escape.json()["code"] == "FILE_PATH_INVALID"

        # 下载目录内的符号链接指向目录之外
        link = root / "link.pdf"
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(outside)
        _set_relative_path(db_manager, file_id, "link.pdf")
        symlink = client.get(f"/api/v1/files/{file_id}/content")
        assert symlink.status_code == 500
        assert symlink.json()["code"] == "FILE_PATH_INVALID"

        # 非 PDF 扩展名
        text_file = root / "note.txt"
        text_file.write_text("not pdf", encoding="utf-8")
        _set_relative_path(db_manager, file_id, "note.txt")
        non_pdf = client.get(f"/api/v1/files/{file_id}/content")
        assert non_pdf.status_code == 415
        assert non_pdf.json()["code"] == "FILE_TYPE_INVALID"

    # 错误响应不得出现绝对路径
    assert str(root) not in escape.text
    assert str(root) not in non_pdf.text
