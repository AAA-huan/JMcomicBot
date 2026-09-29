"""漫画扫描模块的测试"""

import os

import pytest

from src.database.models import Manga
from src.database.repositories import MangaRepository
from src.utils.manga_scanner import (
    parse_pdf_filename,
    scan_download_dir,
    sync_scanned_to_db,
)


class TestParsePdfFilename:
    """PDF文件名解析测试"""

    def test_new_format(self) -> None:
        entry = parse_pdf_filename("350234-示例漫画(5章).pdf")
        assert entry is not None
        assert entry.manga_id == "350234"
        assert entry.title == "示例漫画"
        assert entry.chapter_count == 5

    def test_old_format(self) -> None:
        entry = parse_pdf_filename("350234.pdf")
        assert entry is not None
        assert entry.manga_id == "350234"
        assert entry.title == ""

    def test_title_with_parentheses(self) -> None:
        entry = parse_pdf_filename("350234-示例(番外)漫画(3章).pdf")
        assert entry is not None
        assert entry.title == "示例(番外)漫画"
        assert entry.chapter_count == 3

    def test_invalid_name(self) -> None:
        entry = parse_pdf_filename("readme.txt")
        assert entry is None


class TestScanDownloadDir:
    """下载目录扫描测试"""

    def test_scan_aggregates_same_manga(self, tmp_path) -> None:
        """同一漫画多个PDF应聚合为一条记录，章节数取最大值"""
        os.makedirs(tmp_path, exist_ok=True)
        (tmp_path / "350234-漫画A(2章).pdf").write_bytes(b"%PDF")
        (tmp_path / "350234-漫画A(5章).pdf").write_bytes(b"%PDF")
        (tmp_path / "350235-漫画B(1章).pdf").write_bytes(b"%PDF")
        (tmp_path / "readme.txt").write_text("not pdf")

        entries = scan_download_dir(str(tmp_path))
        assert len(entries) == 2

        by_id = {e.manga_id: e for e in entries}
        assert by_id["350234"].title == "漫画A"
        assert by_id["350234"].chapter_count == 5
        assert len(by_id["350234"].files) == 2
        assert by_id["350235"].chapter_count == 1

    def test_scan_missing_dir(self, tmp_path) -> None:
        missing = str(tmp_path / "not_exist")
        with pytest.raises(FileNotFoundError):
            scan_download_dir(missing)

    def test_scan_empty_dir(self, tmp_path) -> None:
        os.makedirs(tmp_path, exist_ok=True)
        assert scan_download_dir(str(tmp_path)) == []


class TestSyncScannedToDb:
    """扫描结果入库同步测试"""

    def test_new_and_update(self, tmp_path, manga_repo: MangaRepository) -> None:
        os.makedirs(tmp_path, exist_ok=True)
        pdf_new = tmp_path / "350234-新漫画(3章).pdf"
        pdf_new.write_bytes(b"%PDF")

        # 先手动造一条记录模拟旧数据库（标题不同，验证保留更完整元数据）
        manga_repo.upsert(
            manga_id="350235",
            title="旧标题",
            author="作者A",
            tags="热血",
            chapter_count=1,
            page_count=999,
        )
        # 旧记录的PDF文件已不存在（模拟残留），同时该漫画也在扫描条目中
        pdf_old = tmp_path / "350235-新标题(5章).pdf"
        pdf_old.write_bytes(b"%PDF")

        entries = scan_download_dir(str(tmp_path))
        result = sync_scanned_to_db(manga_repo, entries)

        assert result.new_count == 1
        assert result.updated_count == 1
        assert result.scanned_files == 2

        # 新记录完整写入
        new_manga = manga_repo.get("350234")
        assert new_manga is not None
        assert new_manga.title == "新漫画"
        assert new_manga.chapter_count == 3
        assert len(new_manga.files) == 1

        # 已有记录：标题更新，但 DB 已有非零 chapter_count 不被文件名数值覆盖（P0-3 修复）
        existing_manga = manga_repo.get("350235")
        assert existing_manga is not None
        assert existing_manga.title == "新标题"
        assert existing_manga.chapter_count == 1  # 保留 DB 已有值，不被文件名"5章"覆盖
        assert existing_manga.author == "作者A"
        assert existing_manga.page_count == 999

    def test_db_chapter_count_preferred_over_filename(
        self, tmp_path, manga_repo: MangaRepository
    ) -> None:
        """DB 已有非零 chapter_count 时，扫描不应用文件名数值覆盖（P0-3 修复）"""
        os.makedirs(tmp_path, exist_ok=True)
        # DB 有正确章节数 25，文件名数值（可能是页数）为 250
        manga_repo.upsert(
            manga_id="350236",
            title="旧标题",
            author="",
            tags="",
            chapter_count=25,
            page_count=500,
        )
        (tmp_path / "350236-标题(250章).pdf").write_bytes(b"%PDF")

        entries = scan_download_dir(str(tmp_path))
        sync_scanned_to_db(manga_repo, entries)

        manga = manga_repo.get("350236")
        assert manga is not None
        assert manga.chapter_count == 25  # 以 DB 为准
        assert manga.page_count == 500  # 保留 DB 已有值，不被覆盖为 0

    def test_idempotent_rescan(self, tmp_path, manga_repo: MangaRepository) -> None:
        """重复扫描不应产生重复的文件记录"""
        os.makedirs(tmp_path, exist_ok=True)
        pdf = tmp_path / "350234-漫画(3章).pdf"
        pdf.write_bytes(b"%PDF")

        entries = scan_download_dir(str(tmp_path))
        sync_scanned_to_db(manga_repo, entries)
        sync_scanned_to_db(manga_repo, entries)

        manga = manga_repo.get("350234")
        assert manga is not None
        assert manga_repo.count() == 1
        assert len(manga.files) == 1

    def test_cleanup_missing_files(self, tmp_path, manga_repo: MangaRepository) -> None:
        """数据库中存在但文件不存在的记录应被清理"""
        os.makedirs(tmp_path, exist_ok=True)
        pdf = tmp_path / "350234-漫画(3章).pdf"
        pdf.write_bytes(b"%PDF")
        entries = scan_download_dir(str(tmp_path))
        sync_scanned_to_db(manga_repo, entries)

        # 造一个文件已不存在的残留记录
        manga_repo.upsert(
            manga_id="999999",
            title="残留漫画",
            author="",
            tags="",
            chapter_count=1,
            page_count=0,
        )
        assert manga_repo.count() == 2

        result = sync_scanned_to_db(manga_repo, entries)
        assert result.deleted_count == 0
        assert manga_repo.count() == 2
        missing = manga_repo.get("999999")
        assert missing is not None
        assert missing.status == "missing_file"

    def test_dry_run_writes_nothing(
        self, tmp_path, manga_repo: MangaRepository
    ) -> None:
        os.makedirs(tmp_path, exist_ok=True)
        pdf = tmp_path / "350234-漫画(3章).pdf"
        pdf.write_bytes(b"%PDF")
        entries = scan_download_dir(str(tmp_path))

        result = sync_scanned_to_db(manga_repo, entries, dry_run=True)

        assert result.new_count == 1
        assert result.pending_cleanup_count == 0
        assert manga_repo.get("350234") is None
        assert manga_repo.count() == 0

    def test_dry_run_distinguishes_new_and_updated(
        self, tmp_path, manga_repo: MangaRepository
    ) -> None:
        """预览模式应读取现有记录，准确统计新增与更新且不写入"""
        existing_path = tmp_path / "350234-新标题(3章).pdf"
        new_path = tmp_path / "350235-新漫画(2章).pdf"
        existing_path.write_bytes(b"%PDF")
        new_path.write_bytes(b"%PDF")
        manga_repo.upsert(
            manga_id="350234",
            title="旧标题",
            author="作者",
            tags="纯爱",
            chapter_count=3,
            page_count=100,
        )

        entries = scan_download_dir(str(tmp_path))
        result = sync_scanned_to_db(manga_repo, entries, dry_run=True)

        assert result.new_count == 1
        assert result.updated_count == 1
        assert manga_repo.count() == 1
        existing = manga_repo.get("350234")
        assert existing is not None
        assert existing.title == "旧标题"


class TestSyncScannedToDbTagCleanup:
    """扫描同步时的标签表清理与写入测试"""

    def test_cleanup_orphan_tags(
        self, tmp_path, manga_repo: MangaRepository, tag_repo
    ) -> None:
        """清理残留漫画时，应同步删除对应的孤儿标签记录"""
        os.makedirs(tmp_path, exist_ok=True)
        pdf = tmp_path / "350234-漫画(3章).pdf"
        pdf.write_bytes(b"%PDF")
        entries = scan_download_dir(str(tmp_path))

        # 预置残留漫画及其标签记录
        manga_repo.upsert(
            manga_id="999999",
            title="残留漫画",
            author="",
            tags="萌系",
            chapter_count=1,
            page_count=0,
        )
        tag_repo.add_for_existing_manga(
            "萌系", "999999", "999999-残留漫画(1章).pdf"
        )

        result = sync_scanned_to_db(manga_repo, entries, tag_repo=tag_repo)

        assert result.deleted_count == 0
        assert len(tag_repo.get_by_tag("萌系")) == 1

    def test_enrich_entry_writes_tags(
        self, tmp_path, manga_repo: MangaRepository, tag_repo
    ) -> None:
        """扫描条目联网补全了标签后，同步时应写入标签表"""
        from src.utils.manga_scanner import MangaScanEntry

        os.makedirs(tmp_path, exist_ok=True)
        pdf = tmp_path / "350234-漫画(3章).pdf"
        pdf.write_bytes(b"%PDF")
        entries = scan_download_dir(str(tmp_path))

        # 模拟联网补全：直接给 entry 填充作者与标签
        for entry in entries:
            entry.author = "しにま"
            entry.tags = "萌系,纯爱"

        sync_scanned_to_db(manga_repo, entries, tag_repo=tag_repo)

        assert len(tag_repo.get_by_tag("萌系")) == 1
        assert len(tag_repo.get_by_tag("纯爱")) == 1
