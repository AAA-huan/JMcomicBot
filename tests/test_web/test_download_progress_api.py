"""下载进度 REST 快照接口测试。"""

from pathlib import Path

from tests.test_web.support import (
    build_web_context,
    create_test_client,
    setup_and_login,
)


def test_download_progress_requires_login(db_manager) -> None:
    """未登录访问进度接口应返回 401。"""
    root = Path(db_manager.db_dir).parent
    context = build_web_context(db_manager, root, root / "backups")
    client = create_test_client(context.dependencies)

    with client:
        response = client.get("/api/v1/downloads/progress")

    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_REQUIRED"


def test_download_progress_returns_active_snapshot(db_manager) -> None:
    """登录后应返回当前下载快照；无任务时 active 为空。"""
    root = Path(db_manager.db_dir).parent
    context = build_web_context(db_manager, root, root / "backups")
    client = create_test_client(context.dependencies)
    tracker = context.dependencies.download_progress_tracker

    with client:
        setup_and_login(client)
        empty_response = client.get("/api/v1/downloads/progress")
        assert empty_response.status_code == 200
        assert empty_response.json() == {"active": None}

        tracker.begin("900001", "task-1")
        tracker.start("900001", 2)
        tracker.chapter_started("p1", 1)
        tracker.image_done("p1")
        tracker.chapter_finished("p1")
        tracker.finish(succeeded=False)

        response = client.get("/api/v1/downloads/progress")

    assert response.status_code == 200
    active = response.json()["active"]
    assert active["manga_id"] == "900001"
    assert active["task_id"] == "task-1"
    assert active["album_id"] == "900001"
    assert active["album_total"] == 2
    assert active["album_done"] == 1
    assert active["finished"] is True
    assert active["succeeded"] is False
    assert active["chapters"] == [
        {"photo_id": "p1", "done": 1, "total": 1, "finished": True}
    ]
    assert "T" in active["started_at"]
    assert "T" in active["updated_at"]
