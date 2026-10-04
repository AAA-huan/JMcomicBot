"""增强扫描：真实 PDF 页树、在线详情与本地信息隔离、重复文件和预览。"""

from pathlib import Path
from types import SimpleNamespace

from jmcomic import JmAlbumDetail, JmPhotoDetail, JmcomicException
from pypdf import PdfWriter

from src.database.repositories import MangaRepository
from src.utils.manga_scanner import (
    enrich_metadata_from_jmcomic,
    scan_download_dir,
    sync_scanned_to_db,
)


def write_pdf(path: Path, pages: int) -> None:
    """生成合法小型 PDF，避免用假头部代替页树验证。"""
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=100, height=100)
    writer.write(path)


def album() -> JmAlbumDetail:
    return JmAlbumDetail(
        album_id="100",
        scramble_id="0",
        name="在线标题",
        episode_list=[("100", "1", "第一章"), ("101", "2", "第二章")],
        page_count=8,
        pub_date="2026-01-01",
        update_date="0",
        likes="1",
        views="2",
        comment_count=0,
        works=[],
        actors=[],
        authors=["作者甲", "作者乙"],
        tags=["标签"],
        description="漫画简介",
    )


def option(client):
    return SimpleNamespace(new_jm_client=lambda: client)


def test_online_enrichment_keeps_local_page_and_chapter_counts(db_manager, tmp_path):
    root = tmp_path / "downloads"
    root.mkdir()
    write_pdf(root / "100-旧标题(1章).pdf", 3)
    repo = MangaRepository(db_manager, str(root))
    entries = scan_download_dir(str(root))
    calls = []
    client = SimpleNamespace(
        get_album_detail=lambda manga_id: album(),
        get_photo_detail=lambda *args, **kwargs: calls.append(args),
    )
    assert enrich_metadata_from_jmcomic(entries, option(client)) == 1
    assert calls == []
    result = sync_scanned_to_db(repo, entries, read_pages=True)
    manga = repo.get("100")
    assert manga.page_count == 3
    assert manga.chapter_count == 1
    assert manga.remote_metadata["page_count"] == 8
    assert manga.remote_metadata["chapter_count"] == 2
    assert manga.remote_metadata["update_date"] is None
    assert manga.title == "在线标题"
    assert manga.author == "作者甲,作者乙"
    assert manga.description == "漫画简介"
    assert manga.files[0].page_count == 3
    assert result.enrich_succeeded == 1
    assert result.details[0]["warnings"]
    sync_scanned_to_db(repo, scan_download_dir(str(root)))
    assert repo.get("100").title == "在线标题"


def test_enriched_preview_does_not_write(db_manager, tmp_path):
    write_pdf(tmp_path / "100.pdf", 5)
    repo = MangaRepository(db_manager, str(tmp_path))
    entries = scan_download_dir(str(tmp_path))
    enrich_metadata_from_jmcomic(
        entries, option(SimpleNamespace(get_album_detail=lambda _: album()))
    )
    result = sync_scanned_to_db(repo, entries, dry_run=True, read_pages=True)
    assert repo.get("100") is None
    changes = {item["field"]: item["new"] for item in result.details[0]["changes"]}
    assert changes["page_count"] == 5
    assert changes["remote.page_count"] == 8
    assert result.new_count == 1


def test_detail_failures_and_chapter_check_are_explicit(db_manager, tmp_path):
    write_pdf(tmp_path / "100.pdf", 3)
    write_pdf(tmp_path / "200.pdf", 3)
    entries = scan_download_dir(str(tmp_path))

    def get_album(manga_id):
        if manga_id == "200":
            raise JmcomicException("站点拒绝请求", {})
        return album()

    calls = []

    def get_photo(photo_id, **kwargs):
        calls.append(kwargs)
        return JmPhotoDetail(
            photo_id=photo_id,
            name="章节",
            series_id="100",
            sort=1,
            page_arr=["1.jpg", "2.jpg"],
        )

    enrich_metadata_from_jmcomic(
        entries,
        option(SimpleNamespace(get_album_detail=get_album, get_photo_detail=get_photo)),
        check_chapters=True,
    )
    repo = MangaRepository(db_manager, str(tmp_path))
    result = sync_scanned_to_db(repo, entries)
    assert result.enrich_succeeded == 1
    assert result.enrich_failed == 1
    assert "站点拒绝请求" in result.details[1]["error"]
    assert repo.get("100").remote_metadata["chapter_page_count"] == 4
    assert all(
        call == {"fetch_album": False, "fetch_scramble_id": False} for call in calls
    )
    assert any("不一致" in warning for warning in result.details[0]["warnings"])


def test_duplicates_skip_unknown_and_keep_registered_file(db_manager, tmp_path):
    first = tmp_path / "100-A.pdf"
    second = tmp_path / "100-B.pdf"
    write_pdf(first, 3)
    write_pdf(second, 5)
    repo = MangaRepository(db_manager, str(tmp_path))
    entries = scan_download_dir(str(tmp_path))
    result = sync_scanned_to_db(repo, entries, read_pages=True)
    assert result.skipped_count == 1
    assert result.duplicate_count == 1
    assert repo.get("100") is None
    repo.upsert("100", "A", "", 1, 3)
    registered = repo.add_file("100", str(first), page_count=3)
    result = sync_scanned_to_db(repo, entries, read_pages=True)
    assert result.skipped_count == 0
    assert repo.get("100").page_count == 3
    assert repo.get_file(registered.id).relative_path == first.name


def test_corrupt_pdf_does_not_invent_page_count(db_manager, tmp_path):
    (tmp_path / "100.pdf").write_bytes(b"broken PDF")
    repo = MangaRepository(db_manager, str(tmp_path))
    result = sync_scanned_to_db(repo, scan_download_dir(str(tmp_path)), read_pages=True)
    assert result.page_read_failed == 1
    assert repo.get("100") is None
    assert result.skipped_count == 1
    assert result.details[0]["warnings"]


def test_repeated_scan_is_unchanged_and_preserves_file_hash(db_manager, tmp_path):
    pdf = tmp_path / "100-title(1章).pdf"
    write_pdf(pdf, 3)
    repo = MangaRepository(db_manager, str(tmp_path))
    entries = scan_download_dir(str(tmp_path))
    sync_scanned_to_db(repo, entries, read_pages=True)
    stored = repo.list_files("100")[0]
    repo.add_file("100", str(pdf), page_count=3, sha256="a" * 64)
    result = sync_scanned_to_db(repo, entries, read_pages=True)
    assert result.unchanged_count == 1
    assert result.updated_count == 0
    assert repo.get_file(stored.id).sha256 == "a" * 64


def test_partial_chapter_failure_does_not_claim_complete_total(db_manager, tmp_path):
    """章节请求部分失败时，成功详情保留，但不生成虚假的完整章页数。"""
    write_pdf(tmp_path / "100.pdf", 3)
    entries = scan_download_dir(str(tmp_path))

    def get_photo(photo_id, **_kwargs):
        if photo_id == "100":
            raise JmcomicException("章节不存在", {})
        return JmPhotoDetail(
            photo_id=photo_id, name="章节", series_id="100", sort=2, page_arr=["1.jpg"]
        )

    client = SimpleNamespace(
        get_album_detail=lambda _: album(), get_photo_detail=get_photo
    )
    enrich_metadata_from_jmcomic(entries, option(client), check_chapters=True)
    repo = MangaRepository(db_manager, str(tmp_path))
    result = sync_scanned_to_db(repo, entries)
    assert result.chapter_errors == 1
    assert result.enrich_succeeded == 1
    assert "chapter_page_count" not in repo.get("100").remote_metadata
    assert any("章节不存在" in message for message in result.details[0]["warnings"])
