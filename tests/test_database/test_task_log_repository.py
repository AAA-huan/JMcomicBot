"""任务日志仓储的测试"""

from src.database.repositories.task_log_repository import TaskLogRepository


class TestTaskLog:
    """任务日志仓储测试类"""

    def test_add_and_get(self, task_log_repo: TaskLogRepository) -> None:
        log = task_log_repo.add(
            task_type="download",
            status="success",
            manga_id="11",
            user_id="u1",
            group_id="g1",
            private=False,
            message="下载完成",
        )
        assert log.id > 0
        assert log.task_type == "download"
        assert log.status == "success"

        loaded = task_log_repo.get(log.id)
        assert loaded is not None
        assert loaded.message == "下载完成"

    def test_list_filter(self, task_log_repo: TaskLogRepository) -> None:
        task_log_repo.add(task_type="download", status="success", manga_id="11")
        task_log_repo.add(task_type="send", status="success", manga_id="11")
        task_log_repo.add(task_type="delete", status="success", manga_id="12")

        assert len(task_log_repo.list(task_type="download")) == 1
        assert len(task_log_repo.list(manga_id="11")) == 2
        assert len(task_log_repo.list(user_id="u1")) == 0
        assert len(task_log_repo.list()) == 3

    def test_count(self, task_log_repo: TaskLogRepository) -> None:
        task_log_repo.add(task_type="download", status="success")
        task_log_repo.add(task_type="download", status="failed")
        task_log_repo.add(task_type="send", status="success")

        assert task_log_repo.count() == 3
        assert task_log_repo.count(task_type="download") == 2
        assert task_log_repo.count(status="success") == 2
