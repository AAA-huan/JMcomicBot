"""操作任务应用服务，统一任务状态、事件和审计写入。"""

from dataclasses import asdict
from typing import Any, Dict, List, Optional

from src.database.models import OperationTask
from src.database.repositories import (
    AuditEventRepository,
    OperationTaskRepository,
    TaskEventRepository,
)
from src.service.events import NULL_EVENT_PUBLISHER, EventPublisher
from src.service.operation_context import OperationContext
from src.service.results import TaskResult

# 审计事件名按 task_type 映射到第 2.11 节规定的领域前缀。
# task_event 过程事件保持 {task_type}.xxx 命名，不在此映射。
_AUDIT_EVENT_NAMES: Dict[str, Dict[str, str]] = {
    "download": {
        "requested": "download.requested",
        "succeeded": "download.completed",
        "failed": "download.failed",
    },
    "delete": {
        "requested": "manga.delete_requested",
        "succeeded": "manga.deleted",
        "failed": "manga.delete_failed",
    },
    "backup": {
        "requested": "database.backup_requested",
        "succeeded": "database.backup_created",
        "failed": "database.backup_failed",
    },
    "scan": {
        "requested": "library.scan_requested",
        "succeeded": "library.scan_completed",
        "failed": "library.scan_failed",
    },
    "repair": {
        "requested": "library.repair_requested",
        "succeeded": "library.repair_completed",
        "failed": "library.repair_failed",
    },
    "verify": {
        "requested": "library.verify_requested",
        "succeeded": "library.verify_completed",
        "failed": "library.verify_failed",
    },
}


def _audit_event_name(task_type: str, phase: str) -> str:
    """按 task_type 和生命周期阶段返回第 2.11 节规定的审计事件名。"""
    try:
        return _AUDIT_EVENT_NAMES[task_type][phase]
    except KeyError as error:
        raise ValueError(
            f"未定义的审计事件名: task_type={task_type}, phase={phase}"
        ) from error


class OperationTaskService:
    """协调操作任务、过程事件和审计记录。"""

    def __init__(
        self,
        task_repo: OperationTaskRepository,
        event_repo: TaskEventRepository,
        audit_repo: AuditEventRepository,
        event_publisher: EventPublisher = NULL_EVENT_PUBLISHER,
    ) -> None:
        self.task_repo = task_repo
        self.event_repo = event_repo
        self.audit_repo = audit_repo
        self.event_publisher = event_publisher

    def _publish_task(self, task: TaskResult) -> TaskResult:
        """发布任务状态事件，供 WebSocket 推送。"""
        self.event_publisher.publish("task.updated", asdict(task))
        return task

    @staticmethod
    def _to_result(task: OperationTask) -> TaskResult:
        """复制公开字段，避免 ORM 实体越过应用服务边界。"""
        return TaskResult(
            id=task.id,
            task_type=task.task_type,
            source=task.source,
            status=task.status,
            stage=task.stage,
            progress=task.progress,
            manga_id=task.manga_id,
            summary=task.summary,
            error_code=task.error_code,
            error_message=task.error_message,
        )

    def create(
        self,
        task_type: str,
        context: OperationContext,
        manga_id: Optional[str] = None,
    ) -> TaskResult:
        """创建任务，并记录请求事件和审计。"""
        if task_type == "download" and manga_id is not None:
            active = self.task_repo.find_active_download(manga_id)
            if active is not None:
                return self._publish_task(self._to_result(active))
        task = self.task_repo.create(
            task_type,
            context.source,
            context.actor_user_id or "",
            manga_id,
        )
        self.event_repo.append(task.id, f"{task_type}.requested", "queued")
        self.audit_repo.record(
            event_type=_audit_event_name(task_type, "requested"),
            source=context.source,
            result="accepted",
            actor_user_id=context.actor_user_id,
            actor_group_id=context.actor_group_id,
            client_ip=context.client_ip,
            target_type="manga" if manga_id else task_type,
            target_id=manga_id or task.id,
        )
        return self._publish_task(self._to_result(task))

    def start(self, task_id: str, stage: str) -> TaskResult:
        """将排队任务切换为运行中。"""
        task = self.task_repo.update_state(task_id, "running", stage)
        self.event_repo.append(task_id, f"{task.task_type}.started", stage)
        return self._publish_task(self._to_result(task))

    def progress(
        self,
        task_id: str,
        stage: str,
        progress: Optional[int],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TaskResult:
        """更新运行进度并追加事件。"""
        task = self.task_repo.update_state(task_id, "running", stage, progress)
        self.event_repo.append(
            task_id,
            f"{task.task_type}.progress",
            stage,
            progress=progress,
            metadata=metadata,
        )
        return self._publish_task(self._to_result(task))

    def succeed(
        self,
        task_id: str,
        metadata: Optional[Dict[str, Any]] = None,
        context: Optional[OperationContext] = None,
    ) -> TaskResult:
        """完成任务并记录成功审计。"""
        task = self.task_repo.update_state(task_id, "succeeded", "completed", 100)
        self.event_repo.append(
            task_id,
            f"{task.task_type}.completed",
            "completed",
            progress=100,
            metadata=metadata,
        )
        self.audit_repo.record(
            event_type=_audit_event_name(task.task_type, "succeeded"),
            source=task.source,
            result="succeeded",
            actor_user_id=(
                context.actor_user_id if context else task.requested_by or None
            ),
            actor_group_id=context.actor_group_id if context else None,
            client_ip=context.client_ip if context else None,
            target_type="manga" if task.manga_id else task.task_type,
            target_id=task.manga_id or task.id,
            metadata=metadata,
        )
        return self._publish_task(self._to_result(task))

    def fail(
        self,
        task_id: str,
        error_code: str,
        error_message: str,
        context: Optional[OperationContext] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TaskResult:
        """以脱敏错误摘要结束任务。"""
        task = self.task_repo.update_state(
            task_id,
            "failed",
            "failed",
            error_code=error_code,
            error_message=error_message,
        )
        self.event_repo.append(
            task_id, f"{task.task_type}.failed", "failed", metadata=metadata
        )
        self.audit_repo.record(
            event_type=_audit_event_name(task.task_type, "failed"),
            source=task.source,
            result="failed",
            actor_user_id=(
                context.actor_user_id if context else task.requested_by or None
            ),
            actor_group_id=context.actor_group_id if context else None,
            client_ip=context.client_ip if context else None,
            target_type="manga" if task.manga_id else task.task_type,
            target_id=task.manga_id or task.id,
            error_code=error_code,
        )
        return self._publish_task(self._to_result(task))

    def cancel(self, task_id: str) -> TaskResult:
        """取消尚未开始的任务。"""
        task = self.task_repo.update_state(task_id, "cancelled", "cancelled")
        self.event_repo.append(task_id, f"{task.task_type}.cancelled", "cancelled")
        return self._publish_task(self._to_result(task))

    def requeue(self, task_id: str, reason: str = "") -> TaskResult:
        """将失败/中断的下载任务重新入队（复用原任务记录）。

        仓储层校验状态转换与同漫画活动任务冲突；服务层追加 download.requeued
        事件并发布 task.updated，事件元数据保留原状态与重试原因。审计由调用方
        （DownloadQueueService.retry_tasks、启动恢复流程）记录。
        """
        current = self.task_repo.get(task_id)
        previous_status = current.status if current is not None else ""
        task = self.task_repo.requeue(task_id)
        metadata: Dict[str, Any] = {}
        if previous_status:
            metadata["previous_status"] = previous_status
        if reason:
            metadata["reason"] = reason
        self.event_repo.append(
            task_id,
            f"{task.task_type}.requeued",
            "queued",
            metadata=metadata or None,
        )
        return self._publish_task(self._to_result(task))

    def get(self, task_id: str) -> Optional[TaskResult]:
        """按任务 ID 返回任务快照，不存在时返回 None。"""
        task = self.task_repo.get(task_id)
        return self._to_result(task) if task is not None else None

    def find_active_download(self, manga_id: str) -> Optional[TaskResult]:
        """查找同漫画尚未结束的下载任务。"""
        task = self.task_repo.find_active_download(manga_id)
        return self._to_result(task) if task is not None else None

    def list_active_downloads(self) -> List[TaskResult]:
        """列出全部尚未结束的下载任务（queued/running）。"""
        return [
            self._to_result(task) for task in self.task_repo.list_active_downloads()
        ]

    def recover_interrupted(self) -> List[TaskResult]:
        """启动时中断全部遗留运行任务，返回被中断的下载任务列表。

        每个被中断任务都会追加 <task_type>.interrupted 事件并发布 task.updated；
        下载任务额外写入 download.interrupted 审计。非下载任务为同步执行，只保留
        中断记录，不参与下载队列恢复。
        """
        interrupted_tasks = self.task_repo.interrupt_running()
        download_results: List[TaskResult] = []
        for task in interrupted_tasks:
            result = self._to_result(task)
            self.event_repo.append(
                task.id,
                f"{task.task_type}.interrupted",
                "interrupted",
                metadata={
                    "previous_status": "running",
                    "reason": "startup_recovery",
                },
            )
            if task.task_type == "download":
                self.audit_repo.record(
                    event_type="download.interrupted",
                    source=task.source,
                    result="interrupted",
                    actor_user_id=task.requested_by or None,
                    target_type="manga" if task.manga_id else task.task_type,
                    target_id=task.manga_id or task.id,
                    metadata={"reason": "startup_recovery"},
                )
                download_results.append(result)
            self._publish_task(result)
        return download_results
