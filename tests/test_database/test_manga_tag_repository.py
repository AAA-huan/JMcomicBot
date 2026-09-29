"""漫画标签仓储的测试"""

import pytest

from src.database.repositories.manga_repository import MangaRepository
from src.database.repositories.manga_tag_repository import MangaTagRepository


class TestMangaTag:
    """漫画标签仓储测试类"""

    @staticmethod
    def _create_mangas(manga_repo: MangaRepository, *manga_ids: str) -> None:
        for manga_id in manga_ids:
            manga_repo.upsert(
                manga_id=manga_id,
                title="",
                author="",
                tags="",
                chapter_count=0,
                page_count=0,
            )

    def test_add_and_get_by_tag(
        self, tag_repo: MangaTagRepository, manga_repo: MangaRepository
    ) -> None:
        self._create_mangas(manga_repo, "100", "101")
        tag_repo.add("萌系", "100", "100-萌漫画(1章).pdf")
        tag_repo.add("萌系", "101", "101-甜漫画(2章).pdf")

        records = tag_repo.get_by_tag("萌系")
        assert len(records) == 2
        assert {r.manga_id for r in records} == {"100", "101"}
        assert all(record.tag_id is not None for record in records)

    def test_add_idempotent(
        self, tag_repo: MangaTagRepository, manga_repo: MangaRepository
    ) -> None:
        self._create_mangas(manga_repo, "100")
        tag_repo.add("萌系", "100", "100-萌漫画(1章).pdf")
        tag_repo.add("萌系", "100", "100-萌漫画(1章).pdf")

        assert len(tag_repo.get_by_tag("萌系")) == 1

    def test_tag_query_uses_normalized_name(
        self, tag_repo: MangaTagRepository, manga_repo: MangaRepository
    ) -> None:
        self._create_mangas(manga_repo, "100")
        tag_repo.add(" 萌系 ", "100", "100-a.pdf")

        assert len(tag_repo.get_by_tag("萌系")) == 1
        assert tag_repo.list_all_tags() == ["萌系"]

    def test_strict_add_requires_existing_manga(
        self, tag_repo: MangaTagRepository
    ) -> None:
        with pytest.raises(ValueError, match="漫画记录不存在"):
            tag_repo.add_for_existing_manga("萌系", "404", "404.pdf")

    def test_list_all_tags(
        self, tag_repo: MangaTagRepository, manga_repo: MangaRepository
    ) -> None:
        self._create_mangas(manga_repo, "100", "200")
        tag_repo.add("萌系", "100", "100-萌漫画(1章).pdf")
        tag_repo.add("热血", "200", "200-热血漫画(1章).pdf")

        assert tag_repo.list_all_tags() == sorted(["萌系", "热血"])

    def test_delete_by_manga_id(
        self, tag_repo: MangaTagRepository, manga_repo: MangaRepository
    ) -> None:
        self._create_mangas(manga_repo, "100", "200")
        tag_repo.add("萌系", "100", "100-a.pdf")
        tag_repo.add("热血", "100", "100-a.pdf")
        tag_repo.add("萌系", "200", "200-b.pdf")

        assert tag_repo.delete_by_manga_id("100") == 2
        assert len(tag_repo.get_by_tag("萌系")) == 1
        assert len(tag_repo.get_by_tag("热血")) == 0

    def test_get_manga_ids_by_tags_intersection(
        self, tag_repo: MangaTagRepository, manga_repo: MangaRepository
    ) -> None:
        self._create_mangas(manga_repo, "100", "200", "300")
        tag_repo.add("萌系", "100", "100-a.pdf")
        tag_repo.add("纯爱", "100", "100-a.pdf")
        tag_repo.add("萌系", "200", "200-b.pdf")
        tag_repo.add("纯爱", "300", "300-c.pdf")

        # 同时命中"萌系"和"纯爱"的只有 100
        assert tag_repo.get_manga_ids_by_tags(["萌系", "纯爱"]) == {"100"}
        assert tag_repo.get_manga_ids_by_tags(["萌系"]) == {"100", "200"}
        assert tag_repo.get_manga_ids_by_tags([]) == set()

    def test_sync_from_manga(
        self, tag_repo: MangaTagRepository, manga_repo: MangaRepository
    ) -> None:
        import os

        manga_repo.upsert(
            manga_id="110",
            title="萌漫画",
            author="",
            tags="萌系,纯爱",
            chapter_count=1,
            page_count=10,
        )
        manga_repo.add_file(
            manga_id="110",
            file_path=os.path.join("/tmp", "110-萌漫画(1章).pdf"),
            file_size_mb=5.0,
        )
        manga_repo.upsert(
            manga_id="111",
            title="热血漫画",
            author="",
            tags="热血",
            chapter_count=1,
            page_count=10,
        )

        added = tag_repo.sync_from_manga()
        assert added == 0
        assert tag_repo.list_all_tags() == []

        # 幂等：再次回填不再新增
        assert tag_repo.sync_from_manga() == 0
