"""阶段三批次 B：阅读进度仓储、服务与级联删除测试。"""

from datetime import timedelta

from sqlalchemy.orm import Session
import pytest

from src.database.models import Manga, MangaFile, ReadingProgress, utc_now
from src.database.repositories import (
    MangaRepository,
    ReadingProgressRepository,
)
from src.service import ReadingProgressService


def _create_manga_file(
    session: Session, manga_id: str = "manga-1", suffix: str = "1"
) -> int:
    """创建测试用漫画与 PDF 记录，返回 PDF 文件ID。"""
    now = utc_now()
    session.add(
        Manga(
            id=manga_id,
            title=f"测试漫画{suffix}",
            author="",
            chapter_count=1,
            page_count=10,
            status="downloaded",
            downloaded_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    session.flush()
    manga_file = MangaFile(
        manga_id=manga_id,
        relative_path=f"测试漫画{suffix}.pdf",
        display_name=f"测试漫画{suffix}.pdf",
        file_type="pdf",
        mime_type="application/pdf",
        file_size_bytes=2048,
        page_count=10,
        status="ready",
        created_at=now,
        updated_at=now,
    )
    session.add(manga_file)
    session.flush()
    return manga_file.id


@pytest.fixture()
def progress_repo(db_manager) -> ReadingProgressRepository:
    return ReadingProgressRepository(db_manager)


@pytest.fixture()
def progress_service(progress_repo, manga_repo) -> ReadingProgressService:
    return ReadingProgressService(progress_repo, manga_repo)


def test_service_validates_page_range_and_computes_percent(
    db_manager, progress_service
) -> None:
    """服务应校验页码范围，percent 由页码计算且更新不产生重复行。"""
    with db_manager.get_session() as session:
        file_id = _create_manga_file(session)
        session.commit()

    progress = progress_service.update(file_id, 5, 10)
    assert progress.page_number == 5
    assert progress.page_count == 10
    assert progress.percent == 0.5

    # 同一 PDF 再次写入应更新原记录而不是新增
    updated = progress_service.update(file_id, 3, 10)
    assert updated.manga_file_id == file_id
    assert updated.percent == 0.3
    with db_manager.get_session() as session:
        assert len(session.query(ReadingProgress).all()) == 1

    with pytest.raises(ValueError, match="总页数"):
        progress_service.update(file_id, 1, 0)
    with pytest.raises(ValueError, match="页码"):
        progress_service.update(file_id, 0, 10)
    with pytest.raises(ValueError, match="页码"):
        progress_service.update(file_id, 11, 10)


def test_get_and_delete_for_file(db_manager, progress_repo, progress_service) -> None:
    """按文件查询与删除阅读进度应返回准确结果。"""
    with db_manager.get_session() as session:
        file_id = _create_manga_file(session)
        session.commit()

    assert progress_service.get(file_id) is None
    progress_service.update(file_id, 2, 10)
    stored = progress_service.get(file_id)
    assert stored is not None
    assert stored.page_number == 2

    assert progress_repo.delete_for_file(file_id) is True
    assert progress_service.get(file_id) is None
    assert progress_repo.delete_for_file(file_id) is False


def test_list_recent_orders_by_updated_at(db_manager, progress_repo) -> None:
    """最近阅读列表应按更新时间倒序并限制数量。"""
    now = utc_now()
    with db_manager.get_session() as session:
        first_id = _create_manga_file(session, "manga-1", "1")
        second_id = _create_manga_file(session, "manga-2", "2")
        third_id = _create_manga_file(session, "manga-3", "3")
        session.commit()

    progress_repo.upsert(first_id, 1, 10, 0.1, updated_at=now - timedelta(hours=2))
    progress_repo.upsert(second_id, 1, 10, 0.1, updated_at=now - timedelta(hours=1))
    progress_repo.upsert(third_id, 1, 10, 0.1, updated_at=now)

    recent = progress_repo.list_recent(limit=2)
    assert [item.manga_file_id for item in recent] == [third_id, second_id]

    with pytest.raises(ValueError, match="最近阅读数量"):
        progress_repo.list_recent(limit=0)


def test_manga_repository_delete_cascades_reading_progress(
    db_manager, manga_repo: MangaRepository, progress_service
) -> None:
    """删除漫画时阅读进度应随文件记录级联删除。"""
    with db_manager.get_session() as session:
        file_id = _create_manga_file(session)
        session.commit()

    progress_service.update(file_id, 4, 10)
    assert manga_repo.delete("manga-1") is True

    with db_manager.get_session() as session:
        assert session.get(MangaFile, file_id) is None
        assert session.get(ReadingProgress, file_id) is None
