"""文件封面与页面图片接口：认证、内容类型、缓存头与 404 边界。"""

from io import BytesIO
from pathlib import Path

from PIL import Image
from pypdf import PdfWriter
from starlette.testclient import TestClient

import img2pdf

from src.database.repositories import MangaRepository
from tests.test_web.support import (
    build_web_context,
    create_test_client,
    setup_and_login,
)


def _make_client(db_manager) -> tuple[TestClient, Path]:
    """构造测试客户端与临时下载根目录。"""
    root = Path(db_manager.db_dir).parent
    context = build_web_context(db_manager, root)
    return create_test_client(context.dependencies), root


def _write_images(root: Path) -> list[str]:
    """在下载目录生成两张不同格式的测试原图。"""
    jpeg_path = root / "001.jpg"
    png_path = root / "002.png"
    Image.new("RGB", (1000, 1320), "red").save(jpeg_path, "JPEG", quality=90)
    Image.new("RGB", (800, 1200), "blue").save(png_path, "PNG")
    return [str(jpeg_path), str(png_path)]


def _add_manga_with_pdf(
    db_manager, root: Path, page_count: int = 2
) -> tuple[int, Path]:
    """写入图片型 PDF 文件记录，返回文件 ID 与路径。"""
    pdf_path = root / "100-测试漫画(1章).pdf"
    pdf_path.write_bytes(img2pdf.convert(_write_images(root)))
    manga_repo = MangaRepository(db_manager, download_root=str(root))
    manga_repo.upsert("100", "测试漫画", "作者", 1, page_count)
    manga_file = manga_repo.add_file("100", str(pdf_path), page_count=page_count)
    return manga_file.id, pdf_path


def test_cover_requires_login(db_manager) -> None:
    """封面与页图接口都需要登录会话。"""
    client, root = _make_client(db_manager)
    file_id, _pdf_path = _add_manga_with_pdf(db_manager, root)

    with client:
        cover = client.get(f"/api/v1/files/{file_id}/cover")
        page = client.get(f"/api/v1/files/{file_id}/page/1")

    assert cover.status_code == 401
    assert page.status_code == 401
    assert cover.json()["code"] == "AUTH_REQUIRED"


def test_cover_returns_scaled_jpeg_with_cache_headers(db_manager) -> None:
    """封面返回 480 宽 JPEG，并允许浏览器长期缓存。"""
    client, root = _make_client(db_manager)
    file_id, _pdf_path = _add_manga_with_pdf(db_manager, root)

    with client:
        setup_and_login(client)
        response = client.get(f"/api/v1/files/{file_id}/cover")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert response.headers["x-content-type-options"] == "nosniff"
    with Image.open(BytesIO(response.content)) as cover:
        assert cover.width == 480
        assert cover.format == "JPEG"


def test_page_returns_original_bytes_and_content_type(db_manager) -> None:
    """页图返回原图，Content-Type 跟随 JPEG/PNG 实际格式。"""
    client, root = _make_client(db_manager)
    file_id, pdf_path = _add_manga_with_pdf(db_manager, root)

    with client:
        setup_and_login(client)
        first = client.get(f"/api/v1/files/{file_id}/page/1")
        second = client.get(f"/api/v1/files/{file_id}/page/2")

    assert first.status_code == 200
    assert first.headers["content-type"] == "image/jpeg"
    assert first.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert first.content.startswith(b"\xff\xd8\xff")
    assert second.status_code == 200
    assert second.headers["content-type"] == "image/png"
    assert second.content.startswith(b"\x89PNG\r\n\x1a\n")
    original = pdf_path.read_bytes()
    assert first.content != second.content
    assert original.startswith(b"%PDF")


def test_page_out_of_range_and_unknown_file_return_404(db_manager) -> None:
    """页码 0/3 与非存在文件记录均返回 404，不泄露内部路径。"""
    client, root = _make_client(db_manager)
    file_id, _pdf_path = _add_manga_with_pdf(db_manager, root)

    with client:
        setup_and_login(client)
        zero = client.get(f"/api/v1/files/{file_id}/page/0")
        beyond = client.get(f"/api/v1/files/{file_id}/page/3")
        unknown = client.get("/api/v1/files/999999/page/1")

    assert zero.status_code == 404
    assert zero.json()["code"] == "PAGE_IMAGE_NOT_FOUND"
    assert beyond.status_code == 404
    assert beyond.json()["code"] == "PAGE_IMAGE_NOT_FOUND"
    assert unknown.status_code == 404
    assert unknown.json()["code"] == "FILE_NOT_FOUND"
    assert str(root) not in beyond.text


def test_non_image_pdf_returns_404_for_cover_and_page(db_manager) -> None:
    """空白/矢量 PDF 不属于图片型，封面与页图均返回 404。"""
    client, root = _make_client(db_manager)
    pdf_path = root / "100-矢量.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    with pdf_path.open("wb") as stream:
        writer.write(stream)
    manga_repo = MangaRepository(db_manager, download_root=str(root))
    manga_repo.upsert("101", "矢量漫画", "作者", 1, 1)
    manga_file = manga_repo.add_file("101", str(pdf_path), page_count=1)

    with client:
        setup_and_login(client)
        cover = client.get(f"/api/v1/files/{manga_file.id}/cover")
        page = client.get(f"/api/v1/files/{manga_file.id}/page/1")

    assert cover.status_code == 404
    assert cover.json()["code"] == "COVER_NOT_AVAILABLE"
    assert page.status_code == 404
    assert page.json()["code"] == "PAGE_IMAGE_NOT_FOUND"
