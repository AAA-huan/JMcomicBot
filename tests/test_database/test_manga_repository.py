"""漫画元数据仓储的测试"""

import pytest
from sqlalchemy import text

from src.database.repositories.manga_repository import MangaRepository
from src.database.models import Manga


class TestManga:
    """漫画元数据仓储测试类"""

    def test_upsert_and_get(self, manga_repo: MangaRepository) -> None:
        manga = manga_repo.upsert(
            manga_id="11",
            title="标题",
            author="作者",
            tags="热血,格斗",
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
            tags="",
            chapter_count=1,
            page_count=10,
        )
        manga_repo.upsert(
            manga_id="12",
            title="新标题",
            author="作者",
            tags="新标签",
            chapter_count=2,
            page_count=20,
        )
        assert manga_repo.count() == 1
        loaded = manga_repo.get("12")
        assert loaded is not None
        assert loaded.title == "新标题"

    def test_count(self, manga_repo: MangaRepository) -> None:
        assert manga_repo.count() == 0
        manga_repo.upsert(
            manga_id="13", title="A", author="", tags="", chapter_count=1, page_count=1
        )
        manga_repo.upsert(
            manga_id="14", title="B", author="", tags="", chapter_count=1, page_count=1
        )
        assert manga_repo.count() == 2

    def test_add_and_list_files(self, manga_repo: MangaRepository, tmp_path) -> None:
        pdf = tmp_path / "11-标题(3章).pdf"
        pdf.write_bytes(b"%PDF")
        manga_repo.upsert(
            manga_id="11",
            title="标题",
            author="",
            tags="",
            chapter_count=3,
            page_count=100,
        )
        manga_repo.add_file("11", str(pdf), 1.5, page_count=7)

        files = manga_repo.list_files("11")
        assert len(files) == 1
        assert files[0].file_path == str(pdf)
        assert files[0].file_size_mb == 1.5
        assert files[0].display_name == pdf.name
        assert files[0].file_type == "pdf"
        assert files[0].mime_type == "application/pdf"
        assert files[0].file_size_bytes == pdf.stat().st_size
        assert files[0].page_count == 7
        assert files[0].status == "ready"

    def test_get_all(self, manga_repo: MangaRepository) -> None:
        manga_repo.upsert(
            manga_id="15", title="A", author="", tags="", chapter_count=1, page_count=1
        )
        result = manga_repo.get_all()
        assert len(result) == 1
        assert isinstance(result[0], Manga)

    def test_add_file_rejects_path_outside_download_root(
        self, db_manager, tmp_path
    ) -> None:
        repository = MangaRepository(db_manager, download_root=str(tmp_path / "downloads"))
        repository.upsert(
            manga_id="23", title="A", author="", tags="", chapter_count=1, page_count=1
        )
        outside_file = tmp_path / "outside.pdf"
        outside_file.write_bytes(b"%PDF")

        with pytest.raises(ValueError, match="下载根目录内"):
            repository.add_file("23", str(outside_file), 0.1)

    def test_add_file_refreshes_existing_metadata(
        self, manga_repo: MangaRepository, tmp_path
    ) -> None:
        pdf = tmp_path / "24-标题(1章).pdf"
        pdf.write_bytes(b"old")
        manga_repo.upsert(
            manga_id="24", title="标题", author="", tags="", chapter_count=1, page_count=1
        )
        manga_repo.add_file("24", str(pdf), 0.1, page_count=3, sha256="old-hash")

        pdf.write_bytes(b"new-content")
        refreshed = manga_repo.add_file("24", str(pdf), 0.2, page_count=4)

        assert refreshed.file_size_bytes == len(b"new-content")
        assert refreshed.file_size_mb == 0.2
        assert refreshed.page_count == 4
        assert refreshed.sha256 is None
        assert refreshed.last_verified_at is None
        assert refreshed.status == "ready"

    def test_add_file_replaces_existing_manga_pdf(self, manga_repo: MangaRepository, tmp_path) -> None:
        first_pdf = tmp_path / "27-old.pdf"
        second_pdf = tmp_path / "27-new.pdf"
        first_pdf.write_bytes(b"old")
        second_pdf.write_bytes(b"new")
        manga_repo.upsert(
            manga_id="27", title="标题", author="", tags="", chapter_count=1, page_count=1
        )

        first_record = manga_repo.add_file("27", str(first_pdf), 0.1)
        second_record = manga_repo.add_file("27", str(second_pdf), 0.1)

        assert second_record.id == first_record.id
        assert manga_repo.list_files("27")[0].file_path == str(second_pdf)

    def test_upsert_rejects_unknown_status(self, manga_repo: MangaRepository) -> None:
        with pytest.raises(ValueError, match="不支持的漫画状态"):
            manga_repo.upsert(
                manga_id="25",
                title="标题",
                author="",
                tags="",
                chapter_count=1,
                page_count=1,
                status="unknown",
            )

    def test_update_file_status_validates_state(self, manga_repo: MangaRepository, tmp_path) -> None:
        pdf = tmp_path / "26-标题(1章).pdf"
        pdf.write_bytes(b"%PDF")
        manga_repo.upsert(
            manga_id="26", title="标题", author="", tags="", chapter_count=1, page_count=1
        )
        manga_file = manga_repo.add_file("26", str(pdf), 0.1)

        assert manga_repo.update_file_status(manga_file.id, "missing") is True
        assert manga_repo.update_file_status(99999, "ready") is False
        with pytest.raises(ValueError, match="不支持的文件状态"):
            manga_repo.update_file_status(manga_file.id, "unknown")

    def test_resolve_file_path_rejects_path_escape(self, db_manager, tmp_path) -> None:
        download_root = tmp_path / "downloads"
        download_root.mkdir()
        pdf = download_root / "26.pdf"
        pdf.write_bytes(b"%PDF")
        repository = MangaRepository(db_manager, download_root=str(download_root))
        repository.upsert(
            manga_id="27", title="标题", author="", tags="", chapter_count=1, page_count=1
        )
        manga_file = repository.add_file("27", str(pdf), 0.1)

        assert repository.resolve_file_path(manga_file.id, str(download_root)) == pdf

        with db_manager.get_session() as session:
            session.execute(
                text("UPDATE manga_file SET relative_path = '../outside.pdf' WHERE id = :id"),
                {"id": manga_file.id},
            )
            session.commit()
        with pytest.raises(ValueError, match="超出下载根目录"):
            repository.resolve_file_path(manga_file.id, str(download_root))

    def test_backfill_relative_paths_marks_unsafe_files(
        self, db_manager, tmp_path
    ) -> None:
        download_root = tmp_path / "downloads"
        download_root.mkdir()
        inside_file = download_root / "inside.pdf"
        inside_file.write_bytes(b"%PDF")
        outside_file = tmp_path / "outside.pdf"
        outside_file.write_bytes(b"%PDF")
        repository = MangaRepository(db_manager, download_root=str(tmp_path))
        for manga_id, file_path in (("28", inside_file), ("29", outside_file)):
            repository.upsert(
                manga_id=manga_id,
                title="标题",
                author="",
                tags="",
                chapter_count=1,
                page_count=1,
            )
            repository.add_file(manga_id, str(file_path), 0.1)

        with db_manager.get_session() as session:
            session.execute(
                text("UPDATE manga_file SET relative_path = NULL WHERE manga_id IN ('28', '29')")
            )
            session.commit()

        updated_count, invalid_count = repository.backfill_relative_paths(
            str(download_root)
        )
        assert (updated_count, invalid_count) == (1, 1)
        assert repository.list_files("28")[0].relative_path == "inside.pdf"
        assert repository.list_files("29")[0].status == "invalid_path"

    def test_delete(self, manga_repo: MangaRepository) -> None:
        manga_repo.upsert(
            manga_id="16", title="A", author="", tags="", chapter_count=1, page_count=1
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
            tags="",
            chapter_count=1,
            page_count=1,
        )
        manga_repo.add_file("17", str(pdf), 0.5)
        assert manga_repo.delete_files("17") == 1
        assert manga_repo.list_files("17") == []

    def test_find_by_author(self, manga_repo: MangaRepository) -> None:
        manga_repo.upsert(
            manga_id="20",
            title="A",
            author="しにま",
            tags="",
            chapter_count=1,
            page_count=1,
        )
        manga_repo.upsert(
            manga_id="21",
            title="B",
            author="しにま,佐々木篠",
            tags="",
            chapter_count=1,
            page_count=1,
        )
        manga_repo.upsert(
            manga_id="22",
            title="C",
            author="某人",
            tags="",
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
