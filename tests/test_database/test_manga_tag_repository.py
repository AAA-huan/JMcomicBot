"""漫画标签仓储的测试"""

from src.database.repositories.manga_repository import MangaRepository
from src.database.repositories.manga_tag_repository import MangaTagRepository


class TestMangaTag:
    """漫画标签仓储测试类"""

    def test_add_and_get_by_tag(self, tag_repo: MangaTagRepository) -> None:
        tag_repo.add("萌系", "100", "100-萌漫画(1章).pdf")
        tag_repo.add("萌系", "101", "101-甜漫画(2章).pdf")

        records = tag_repo.get_by_tag("萌系")
        assert len(records) == 2
        assert {r.manga_id for r in records} == {"100", "101"}
        assert records[0].pdf_name.endswith(".pdf")
        assert all(record.tag_id is not None for record in records)

    def test_add_idempotent(self, tag_repo: MangaTagRepository) -> None:
        tag_repo.add("萌系", "100", "100-萌漫画(1章).pdf")
        tag_repo.add("萌系", "100", "100-萌漫画(1章).pdf")

        assert len(tag_repo.get_by_tag("萌系")) == 1

    def test_list_all_tags(self, tag_repo: MangaTagRepository) -> None:
        tag_repo.add("萌系", "100", "100-萌漫画(1章).pdf")
        tag_repo.add("热血", "200", "200-热血漫画(1章).pdf")

        assert tag_repo.list_all_tags() == sorted(["萌系", "热血"])

    def test_delete_by_manga_id(self, tag_repo: MangaTagRepository) -> None:
        tag_repo.add("萌系", "100", "100-a.pdf")
        tag_repo.add("热血", "100", "100-a.pdf")
        tag_repo.add("萌系", "200", "200-b.pdf")

        assert tag_repo.delete_by_manga_id("100") == 2
        assert len(tag_repo.get_by_tag("萌系")) == 1
        assert len(tag_repo.get_by_tag("热血")) == 0

    def test_get_manga_ids_by_tags_intersection(
        self, tag_repo: MangaTagRepository
    ) -> None:
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
        assert added == 3
        assert len(tag_repo.get_by_tag("萌系")) == 1
        assert len(tag_repo.get_by_tag("纯爱")) == 1
        assert len(tag_repo.get_by_tag("热血")) == 1

        # 幂等：再次回填不再新增
        assert tag_repo.sync_from_manga() == 0

        # PDF名取自漫画文件记录的 basename
        record = tag_repo.get_by_tag("萌系")[0]
        assert record.pdf_name == "110-萌漫画(1章).pdf"
