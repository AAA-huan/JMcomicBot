"""漫画元数据仓储的测试"""

import pytest

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
        assert manga.tags == "热血,格斗"

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
        assert loaded.tags == "新标签"

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
        manga_repo.add_file("11", str(pdf), 1.5)

        files = manga_repo.list_files("11")
        assert len(files) == 1
        assert files[0].file_path == str(pdf)
        assert files[0].file_size_mb == 1.5
        assert files[0].display_name == pdf.name
        assert files[0].file_type == "pdf"
        assert files[0].mime_type == "application/pdf"
        assert files[0].file_size_bytes == pdf.stat().st_size
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
        manga_repo.add_file("24", str(pdf), 0.1)

        pdf.write_bytes(b"new-content")
        refreshed = manga_repo.add_file("24", str(pdf), 0.2)

        assert refreshed.file_size_bytes == len(b"new-content")
        assert refreshed.file_size_mb == 0.2
        assert refreshed.status == "ready"

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
