"""漫画元数据仓储的测试"""

from datetime import datetime

import pytest
from sqlalchemy import text, update

from src.database.models import Manga, MangaFile
from src.database.repositories.manga_repository import MangaRepository


class TestManga:
    """漫画元数据仓储测试类"""

    def test_upsert_and_get(self, manga_repo: MangaRepository) -> None:
        manga = manga_repo.upsert(
            manga_id="11",
            title="标题",
            author="作者",
            chapter_count=3,
            page_count=100,
        )
        assert manga.id == "11"
        assert manga.title == "标题"

        loaded = manga_repo.get("11")
        assert loaded is not None
        assert loaded.title == "标题"

    def test_upsert_existing(self, manga_repo: MangaRepository) -> None:
        manga_repo.upsert(
            manga_id="12",
            title="旧标题",
            author="作者",
            chapter_count=1,
            page_count=10,
        )
        manga_repo.upsert(
            manga_id="12",
            title="新标题",
            author="作者",
            chapter_count=2,
            page_count=20,
        )
        assert manga_repo.count() == 1
        loaded = manga_repo.get("12")
        assert loaded is not None
        assert loaded.title == "新标题"

    def test_upsert_refresh_downloaded_at_for_real_redownload(
        self, manga_repo: MangaRepository
    ) -> None:
        """真实重下刷新下载时间，首次入库时间保持不变。"""
        manga_repo.upsert("17", "旧标题", "作者", 1, 10)
        original = manga_repo.get("17")
        assert original is not None
        old_downloaded_at = datetime(2020, 1, 1)
        old_created_at = original.created_at
        with manga_repo._get_session() as session:
            session.execute(
                update(Manga)
                .where(Manga.id == "17")
                .values(downloaded_at=old_downloaded_at)
            )
            session.commit()

        manga_repo.upsert("17", "新标题", "作者", 2, 20, refresh_downloaded_at=True)

        loaded = manga_repo.get("17")
        assert loaded is not None
        assert loaded.downloaded_at != old_downloaded_at
        assert loaded.created_at == old_created_at

    def test_upsert_default_does_not_refresh_downloaded_at(
        self, manga_repo: MangaRepository
    ) -> None:
        """扫描目录等默认同步不误刷已下载漫画的下载时间。"""
        manga_repo.upsert("18", "标题", "作者", 1, 10)
        old_downloaded_at = datetime(2020, 1, 1)
        with manga_repo._get_session() as session:
            session.execute(
                update(Manga)
                .where(Manga.id == "18")
                .values(downloaded_at=old_downloaded_at)
            )
            session.commit()

        manga_repo.upsert("18", "新标题", "作者", 2, 20)

        loaded = manga_repo.get("18")
        assert loaded is not None
        assert loaded.downloaded_at == old_downloaded_at

    def test_upsert_favorited_to_downloaded_still_refreshes_downloaded_at(
        self, manga_repo: MangaRepository
    ) -> None:
        """收藏转下载仍按真实下载完成时间刷新，保持原有兼容行为。"""
        manga_repo.upsert("19", "收藏标题", "", 0, 0, status="favorited")
        original = manga_repo.get("19")
        assert original is not None
        old_downloaded_at = datetime(2020, 1, 1)
        with manga_repo._get_session() as session:
            session.execute(
                update(Manga)
                .where(Manga.id == "19")
                .values(downloaded_at=old_downloaded_at)
            )
            session.commit()

        manga_repo.upsert("19", "下载标题", "作者", 2, 20)

        loaded = manga_repo.get("19")
        assert loaded is not None
        assert loaded.downloaded_at != old_downloaded_at

    def test_favorited_manga_completed_download_updates_metadata(
        self, manga_repo: MangaRepository
    ) -> None:
        """下载完成后应把 favorited 转为 downloaded 并补全元数据。"""
        manga_repo.upsert(
            "15",
            "收藏标题",
            "",
            0,
            0,
            status="favorited",
        )
        manga_repo.upsert("16", "另一本收藏", "", 0, 0, status="favorited")
        assert [manga.id for manga in manga_repo.list_with_expected_files()] == []

        manga_repo.upsert("15", "下载标题", "作者", 2, 30)

        loaded = manga_repo.get("15")
        assert loaded is not None
        assert (loaded.status, loaded.title, loaded.author) == (
            "downloaded",
            "下载标题",
            "作者",
        )
        assert (loaded.chapter_count, loaded.page_count) == (2, 30)
        assert [manga.id for manga in manga_repo.list_with_expected_files()] == ["15"]

    def test_count(self, manga_repo: MangaRepository) -> None:
        assert manga_repo.count() == 0
        manga_repo.upsert(
            manga_id="13", title="A", author="", chapter_count=1, page_count=1
        )
        manga_repo.upsert(
            manga_id="14", title="B", author="", chapter_count=1, page_count=1
        )
        assert manga_repo.count() == 2

    def test_total_file_size_bytes(self, manga_repo: MangaRepository, tmp_path) -> None:
        """总大小累加 ready 文件，missing 不计入，空库返回 0。"""
        assert manga_repo.total_file_size_bytes() == 0
        manga_repo.upsert(
            manga_id="30", title="A", author="", chapter_count=1, page_count=1
        )
        manga_repo.upsert(
            manga_id="31", title="B", author="", chapter_count=1, page_count=1
        )
        pdf_a = tmp_path / "30-a.pdf"
        pdf_a.write_bytes(b"%PDF-1.4 aaaa")
        pdf_b = tmp_path / "31-b.pdf"
        pdf_b.write_bytes(b"%PDF-1.4 bbbbbbb")
        manga_repo.add_file("30", str(pdf_a), page_count=1)
        manga_repo.add_file("31", str(pdf_b), page_count=1)
        assert (
            manga_repo.total_file_size_bytes()
            == pdf_a.stat().st_size + pdf_b.stat().st_size
        )

    def test_total_file_size_excludes_missing(
        self, manga_repo: MangaRepository, tmp_path
    ) -> None:
        """missing 状态文件不计入总大小。"""
        from src.database.models import MangaFile
        from sqlalchemy import update

        manga_repo.upsert(
            manga_id="32", title="C", author="", chapter_count=1, page_count=1
        )
        pdf = tmp_path / "32-c.pdf"
        pdf.write_bytes(b"%PDF-1.4 cccccccccc")
        manga_repo.add_file("32", str(pdf), page_count=1)
        # 手动标记为 missing 模拟文件丢失
        with manga_repo._get_session() as session:
            session.execute(
                update(MangaFile)
                .where(MangaFile.manga_id == "32")
                .values(status="missing")
            )
            session.commit()
        assert manga_repo.total_file_size_bytes() == 0

    def test_search_filters_by_tag(self, manga_repo: MangaRepository, tag_repo) -> None:
        """标签过滤只返回命中标签的漫画，不匹配的记录被排除。"""
        manga_repo.upsert(
            manga_id="21", title="带标签", author="", chapter_count=1, page_count=1
        )
        manga_repo.upsert(
            manga_id="22", title="无标签", author="", chapter_count=1, page_count=1
        )
        tag_repo.add("恋爱", "21")

        matched, total = manga_repo.search(
            page=1, page_size=20, search=None, status=None, tag="恋爱", sort="id_asc"
        )

        assert total == 1
        assert [manga.id for manga in matched] == ["21"]

    def test_add_and_list_files(self, manga_repo: MangaRepository, tmp_path) -> None:
        pdf = tmp_path / "11-标题(3章).pdf"
        pdf.write_bytes(b"%PDF")
        manga_repo.upsert(
            manga_id="11",
            title="标题",
            author="",
            chapter_count=3,
            page_count=100,
        )
        manga_repo.add_file("11", str(pdf), page_count=7)

        files = manga_repo.list_files("11")
        assert len(files) == 1
        assert files[0].relative_path == pdf.name
        assert files[0].display_name == pdf.name
        assert files[0].file_type == "pdf"
        assert files[0].mime_type == "application/pdf"
        assert files[0].file_size_bytes == pdf.stat().st_size
        assert files[0].page_count == 7
        assert files[0].status == "ready"

    def test_is_downloaded_requires_ready_file_on_disk(
        self, manga_repo: MangaRepository, tmp_path
    ) -> None:
        """仅下载完成且 PDF 文件实际存在时判定为已下载。"""
        pdf = tmp_path / "31.pdf"
        pdf.write_bytes(b"%PDF")
        manga_repo.upsert("31", "标题", "", 1, 10, status="downloaded")
        manga_repo.add_file("31", str(pdf))

        assert manga_repo.is_downloaded("31") is True

        pdf.unlink()
        assert manga_repo.is_downloaded("31") is False

    def test_is_downloaded_rejects_favorited_and_missing_file_status(
        self, manga_repo: MangaRepository, tmp_path
    ) -> None:
        """收藏态、本体丢失态即使残留文件记录也允许重新下载。"""
        favorited_file = tmp_path / "32.pdf"
        favorited_file.write_bytes(b"%PDF")
        manga_repo.upsert("32", "收藏", "", 0, 0, status="favorited")
        manga_repo.add_file("32", str(favorited_file))

        missing_file = tmp_path / "33.pdf"
        missing_file.write_bytes(b"%PDF")
        manga_repo.upsert("33", "丢失", "", 1, 10, status="missing_file")
        manga_repo.add_file("33", str(missing_file))

        assert manga_repo.is_downloaded("32") is False
        assert manga_repo.is_downloaded("33") is False

    def test_are_downloaded_batches_and_defaults_to_false(
        self, manga_repo: MangaRepository, tmp_path
    ) -> None:
        """批量查询去重保序，缺失记录与非 ready 文件均返回 False。"""
        ready_pdf = tmp_path / "34.pdf"
        ready_pdf.write_bytes(b"%PDF")
        manga_repo.upsert("34", "可读", "", 1, 10, status="downloaded")
        manga_repo.add_file("34", str(ready_pdf))

        corrupted_pdf = tmp_path / "35.pdf"
        corrupted_pdf.write_bytes(b"%PDF")
        manga_repo.upsert("35", "损坏", "", 1, 10, status="downloaded")
        corrupted_file = manga_repo.add_file("35", str(corrupted_pdf))
        manga_repo.update_file_status(corrupted_file.id, "corrupted")

        states = manga_repo.are_downloaded(["34", "35", "36"])

        assert states == {"34": True, "35": False, "36": False}
        assert manga_repo.are_downloaded([]) == {}

    def test_get_all(self, manga_repo: MangaRepository) -> None:
        manga_repo.upsert(
            manga_id="15", title="A", author="", chapter_count=1, page_count=1
        )
        result = manga_repo.get_all()
        assert len(result) == 1
        assert isinstance(result[0], Manga)

    def test_add_file_rejects_path_outside_download_root(
        self, db_manager, tmp_path
    ) -> None:
        repository = MangaRepository(
            db_manager, download_root=str(tmp_path / "downloads")
        )
        repository.upsert(
            manga_id="23", title="A", author="", chapter_count=1, page_count=1
        )
        outside_file = tmp_path / "outside.pdf"
        outside_file.write_bytes(b"%PDF")

        with pytest.raises(ValueError, match="下载根目录内"):
            repository.add_file("23", str(outside_file))

    def test_add_file_rejects_missing_file(
        self, manga_repo: MangaRepository, tmp_path
    ) -> None:
        manga_repo.upsert(
            manga_id="231",
            title="A",
            author="",
            chapter_count=1,
            page_count=1,
        )

        with pytest.raises(FileNotFoundError, match="PDF文件不存在"):
            manga_repo.add_file("231", str(tmp_path / "missing.pdf"))

    def test_add_file_refreshes_existing_metadata(
        self, manga_repo: MangaRepository, tmp_path
    ) -> None:
        pdf = tmp_path / "24-标题(1章).pdf"
        pdf.write_bytes(b"old")
        manga_repo.upsert(
            manga_id="24", title="标题", author="", chapter_count=1, page_count=1
        )
        manga_repo.add_file("24", str(pdf), page_count=3, sha256="old-hash")

        pdf.write_bytes(b"new-content")
        refreshed = manga_repo.add_file("24", str(pdf), page_count=4)

        assert refreshed.file_size_bytes == len(b"new-content")
        assert refreshed.page_count == 4
        assert refreshed.sha256 is None
        assert refreshed.last_verified_at is None
        assert refreshed.status == "ready"

    def test_add_file_without_page_count_preserves_existing_value(
        self, manga_repo: MangaRepository, tmp_path
    ) -> None:
        """扫描等无法获取页数的流程不应清空已有文件页数。"""
        pdf = tmp_path / "241-标题(1章).pdf"
        pdf.write_bytes(b"%PDF")
        manga_repo.upsert(
            manga_id="241", title="标题", author="", chapter_count=1, page_count=8
        )
        manga_repo.add_file("241", str(pdf), page_count=8)

        refreshed = manga_repo.add_file("241", str(pdf))

        assert refreshed.page_count == 8

    def test_add_file_replaces_existing_manga_pdf(
        self, manga_repo: MangaRepository, tmp_path
    ) -> None:
        first_pdf = tmp_path / "27-old.pdf"
        second_pdf = tmp_path / "27-new.pdf"
        first_pdf.write_bytes(b"old")
        second_pdf.write_bytes(b"new")
        manga_repo.upsert(
            manga_id="27", title="标题", author="", chapter_count=1, page_count=1
        )

        first_record = manga_repo.add_file("27", str(first_pdf))
        second_record = manga_repo.add_file("27", str(second_pdf))

        assert second_record.id == first_record.id
        assert manga_repo.list_files("27")[0].relative_path == second_pdf.name

    def test_add_file_rejects_path_owned_by_another_manga(
        self, manga_repo: MangaRepository, tmp_path
    ) -> None:
        pdf = tmp_path / "shared.pdf"
        pdf.write_bytes(b"%PDF")
        for manga_id in ("271", "272"):
            manga_repo.upsert(
                manga_id=manga_id,
                title="标题",
                author="",
                chapter_count=1,
                page_count=1,
            )
        manga_repo.add_file("271", str(pdf))

        with pytest.raises(ValueError, match="已属于漫画 271"):
            manga_repo.add_file("272", str(pdf))

    def test_upsert_rejects_unknown_status(self, manga_repo: MangaRepository) -> None:
        with pytest.raises(ValueError, match="不支持的漫画状态"):
            manga_repo.upsert(
                manga_id="25",
                title="标题",
                author="",
                chapter_count=1,
                page_count=1,
                status="unknown",
            )

    def test_update_file_status_validates_state(
        self, manga_repo: MangaRepository, tmp_path
    ) -> None:
        pdf = tmp_path / "26-标题(1章).pdf"
        pdf.write_bytes(b"%PDF")
        manga_repo.upsert(
            manga_id="26", title="标题", author="", chapter_count=1, page_count=1
        )
        manga_file = manga_repo.add_file("26", str(pdf))

        assert manga_repo.update_file_status(manga_file.id, "missing") is True
        assert manga_repo.update_file_status(99999, "ready") is False
        with pytest.raises(ValueError, match="不支持的文件状态"):
            manga_repo.update_file_status(manga_file.id, "unknown")

    def test_mark_manga_deleting_updates_file_status(
        self, manga_repo: MangaRepository, tmp_path
    ) -> None:
        pdf = tmp_path / "29-标题(1章).pdf"
        pdf.write_bytes(b"%PDF")
        manga_repo.upsert(
            manga_id="29", title="标题", author="", chapter_count=1, page_count=1
        )
        manga_repo.add_file("29", str(pdf))

        assert manga_repo.mark_manga_deleting("29") is True
        assert manga_repo.mark_manga_deleting("missing-id") is False

        files = manga_repo.list_files("29")
        assert len(files) == 1
        assert files[0].status == "deleting"

    def test_resolve_file_path_rejects_path_escape(self, db_manager, tmp_path) -> None:
        download_root = tmp_path / "downloads"
        download_root.mkdir()
        pdf = download_root / "26.pdf"
        pdf.write_bytes(b"%PDF")
        repository = MangaRepository(db_manager, download_root=str(download_root))
        repository.upsert(
            manga_id="27", title="标题", author="", chapter_count=1, page_count=1
        )
        manga_file = repository.add_file("27", str(pdf))

        assert repository.resolve_file_path(manga_file.id, str(download_root)) == pdf

        with db_manager.get_session() as session:
            session.execute(
                text(
                    "UPDATE manga_file SET relative_path = '../outside.pdf' WHERE id = :id"
                ),
                {"id": manga_file.id},
            )
            session.commit()
        with pytest.raises(ValueError, match="超出下载根目录"):
            repository.resolve_file_path(manga_file.id, str(download_root))

    def test_delete(self, manga_repo: MangaRepository) -> None:
        manga_repo.upsert(
            manga_id="16", title="A", author="", chapter_count=1, page_count=1
        )
        assert manga_repo.delete("16") is True
        assert manga_repo.get("16") is None
        assert manga_repo.delete("16") is False

    def test_delete_files(self, manga_repo: MangaRepository, tmp_path) -> None:
        pdf = tmp_path / "17-标题(1章).pdf"
        pdf.write_bytes(b"%PDF")
        manga_repo.upsert(
            manga_id="17",
            title="标题",
            author="",
            chapter_count=1,
            page_count=1,
        )
        manga_repo.add_file("17", str(pdf))
        assert manga_repo.delete_files("17") == 1
        assert manga_repo.list_files("17") == []

    def test_find_by_author(self, manga_repo: MangaRepository) -> None:
        manga_repo.upsert(
            manga_id="20",
            title="A",
            author="しにま",
            chapter_count=1,
            page_count=1,
        )
        manga_repo.upsert(
            manga_id="21",
            title="B",
            author="しにま,佐々木篠",
            chapter_count=1,
            page_count=1,
        )
        manga_repo.upsert(
            manga_id="22",
            title="C",
            author="某人",
            chapter_count=1,
            page_count=1,
        )

        # 模糊匹配命中包含该作者的漫画（含多作者逗号分隔）
        result = manga_repo.find_by_author("しにま")
        assert {m.id for m in result} == {"20", "21"}

        # 单作者精确命中
        result = manga_repo.find_by_author("某人")
        assert {m.id for m in result} == {"22"}

        # 无匹配时返回空列表
        result = manga_repo.find_by_author("不存在作者")
        assert result == []
