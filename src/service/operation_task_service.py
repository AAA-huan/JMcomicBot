"""操作任务应用服务，统一任务状态、事件和审计写入。"""

from typing import Any, Dict, Optional

from src.database.models import OperationTask
from src.database.repositories import (
    AuditEventRepository,
    OperationTaskRepository,
    TaskEventRepository,
)
from src.service.operation_context import OperationContext
from src.service.results import TaskResult


class OperationTaskService:
    """协调操作任务、过程事件和审计记录。"""

    def __init__(
        self,
        task_repo: OperationTaskRepository,
        event_repo: TaskEventRepository,
        audit_repo: AuditEventRepository,
    ) -> None:
        self.task_repo = task_repo
        self.event_repo = event_repo
        self.audit_repo = audit_repo

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
                return self._to_result(active)
        task = self.task_repo.create(
            task_type,
            context.source,
            context.actor_user_id or "",
            manga_id,
        )
        self.event_repo.append(task.id, f"{task_type}.requested", "queued")
        self.audit_repo.record(
            event_type=f"{task_type}.requested",
            source=context.source,
            result="accepted",
            actor_user_id=context.actor_user_id,
            actor_group_id=context.actor_group_id,
            client_ip=context.client_ip,
            target_type="manga" if manga_id else task_type,
            target_id=manga_id or task.id,
        )
        return self._to_result(task)

    def start(self, task_id: str, stage: str) -> TaskResult:
        """将排队任务切换为运行中。"""
        task = self.task_repo.update_state(task_id, "running", stage)
        self.event_repo.append(task_id, f"{task.task_type}.started", stage)
        return self._to_result(task)

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
        return self._to_result(task)

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
            event_type=f"{task.task_type}.completed",
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
        return self._to_result(task)

    def fail(
        self,
        task_id: str,
        error_code: str,
        error_message: str,
        context: Optional[OperationContext] = None,
    ) -> TaskResult:
        """以脱敏错误摘要结束任务。"""
        task = self.task_repo.update_state(
            task_id,
            "failed",
            "failed",
            error_code=error_code,
            error_message=error_message,
        )
        self.event_repo.append(task_id, f"{task.task_type}.failed", "failed")
        self.audit_repo.record(
            event_type=f"{task.task_type}.failed",
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
        return self._to_result(task)

    def cancel(self, task_id: str) -> TaskResult:
        """取消尚未开始的任务。"""
        task = self.task_repo.update_state(task_id, "cancelled", "cancelled")
        self.event_repo.append(task_id, f"{task.task_type}.cancelled", "cancelled")
        return self._to_result(task)

    def recover_interrupted(self) -> int:
        """启动时中断全部遗留运行任务。"""
        return self.task_repo.interrupt_running()
