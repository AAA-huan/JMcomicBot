"""漫画黑名单应用服务，QQ 命令与 Web API 共用。"""

from math import ceil
from typing import Callable, List, Optional, Tuple

from src.database.repositories import (
    AuditEventRepository,
    MangaBlacklistRepository,
    MangaRepository,
)
from src.logging.logger_config import logger
from src.service.contracts import TaskService
from src.service.manga_service import MangaService
from src.service.operation_context import OperationContext
from src.service.query_service import PageResult
from src.service.results import (
    BlacklistBatchResult,
    BlacklistOutcome,
    MangaBlacklistItem,
)

# 单次批量拉黑/解除的漫画数量上限，与下载请求保持一致
BLACKLIST_BATCH_LIMIT = 100
_MAX_REASON_LENGTH = 255
_MAX_MANGA_ID_LENGTH = 32


class MangaBlacklistService:
    """维护漫画黑名单，并统一写入任务与审计记录。"""

    def __init__(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        blacklist_repository: MangaBlacklistRepository,
        manga_repository: MangaRepository,
        audit_repository: AuditEventRepository,
        task_service: TaskService,
        manga_service_provider: Callable[[], MangaService],
        delete_binding: bool = False,
    ) -> None:
        self.blacklist_repository = blacklist_repository
        self.manga_repository = manga_repository
        self.audit_repository = audit_repository
        self.task_service = task_service
        self.manga_service_provider = manga_service_provider
        self.delete_binding = delete_binding

    def add(
        self,
        manga_id: str,
        reason: Optional[str] = None,
        context: Optional[OperationContext] = None,
        *,
        cascade_delete: bool = True,
    ) -> BlacklistOutcome:
        """拉黑漫画；已存在时幂等返回，不重复创建任务。

        Args:
            manga_id: 漫画 ID
            reason: 可选拉黑原因
            context: 操作来源上下文，缺省按系统来源记录
            cascade_delete: 是否允许绑定模式下触发删除；删除流程内部调用时置 False
        """
        normalized_id = self._normalize_manga_id(manga_id)
        normalized_reason = self._normalize_reason(reason)
        operation_context = context or OperationContext.system()

        if self.blacklist_repository.exists(normalized_id):
            return BlacklistOutcome(
                manga_id=normalized_id,
                changed=False,
                status="already_blacklisted",
            )

        task = self.task_service.create(
            "blacklist", operation_context, manga_id=normalized_id
        )
        self.task_service.start(task.id, "blacklisting")
        try:
            added = self.blacklist_repository.add(
                normalized_id,
                normalized_reason,
                operation_context.actor_user_id,
                operation_context.source,
                task.id,
            )
        except Exception as error:  # pylint: disable=broad-exception-caught
            logger.error(f"写入漫画黑名单失败: {normalized_id}: {error}")
            self.task_service.fail(
                task.id,
                "blacklist_failed",
                "写入漫画黑名单失败",
                context=operation_context,
            )
            raise

        if not added:
            # 并发请求已先写入同一条记录：当前任务按完成处理，但不重复审计变更
            self.task_service.succeed(
                task.id,
                context=operation_context,
                stage="done",
            )
            return BlacklistOutcome(
                manga_id=normalized_id,
                changed=False,
                status="already_blacklisted",
                task_id=task.id,
            )

        metadata, deleted, delete_error_code = self._cascade_delete(
            normalized_id, operation_context, cascade_delete
        )
        self.task_service.succeed(
            task.id,
            metadata=metadata or None,
            context=operation_context,
            stage="done",
        )
        return BlacklistOutcome(
            manga_id=normalized_id,
            changed=True,
            status="blacklisted",
            task_id=task.id,
            deleted=deleted,
            delete_error_code=delete_error_code,
        )

    def remove(
        self,
        manga_id: str,
        context: Optional[OperationContext] = None,
    ) -> BlacklistOutcome:
        """解除拉黑；不在黑名单时幂等返回，不创建任务。"""
        normalized_id = self._normalize_manga_id(manga_id)
        operation_context = context or OperationContext.system()
        if not self.blacklist_repository.exists(normalized_id):
            return BlacklistOutcome(
                manga_id=normalized_id,
                changed=False,
                status="not_blacklisted",
            )

        task = self.task_service.create(
            "blacklist", operation_context, manga_id=normalized_id
        )
        self.task_service.start(task.id, "unblacklisting")
        try:
            removed = self.blacklist_repository.remove(normalized_id)
        except Exception as error:  # pylint: disable=broad-exception-caught
            logger.error(f"解除漫画黑名单失败: {normalized_id}: {error}")
            self.task_service.fail(
                task.id,
                "unblacklist_failed",
                "解除漫画黑名单失败",
                context=operation_context,
            )
            raise

        if not removed:
            self.task_service.succeed(
                task.id,
                context=operation_context,
                stage="done",
            )
            return BlacklistOutcome(
                manga_id=normalized_id,
                changed=False,
                status="not_blacklisted",
                task_id=task.id,
            )

        # 解除拉黑与拉黑共用 task_type，完成审计必须显式区分为 unblacklisted
        self.task_service.succeed(
            task.id,
            context=operation_context,
            audit_event_type="manga.unblacklisted",
            stage="done",
        )
        return BlacklistOutcome(
            manga_id=normalized_id,
            changed=True,
            status="unblacklisted",
            task_id=task.id,
        )

    def add_batch(
        self,
        manga_ids: List[str],
        reason: Optional[str] = None,
        context: Optional[OperationContext] = None,
    ) -> BlacklistBatchResult:
        """批量拉黑，内部逐条复用单条任务与审计流程。"""
        normalized_ids = self._normalize_manga_ids(manga_ids)
        normalized_reason = self._normalize_reason(reason)
        operation_context = context or OperationContext.system()
        outcomes = tuple(
            self.add(
                manga_id,
                normalized_reason,
                operation_context,
                cascade_delete=True,
            )
            for manga_id in normalized_ids
        )
        return BlacklistBatchResult(outcomes=outcomes)

    def remove_batch(
        self,
        manga_ids: List[str],
        context: Optional[OperationContext] = None,
    ) -> BlacklistBatchResult:
        """批量解除拉黑，内部逐条复用单条任务与审计流程。"""
        normalized_ids = self._normalize_manga_ids(manga_ids)
        operation_context = context or OperationContext.system()
        outcomes = tuple(
            self.remove(manga_id, operation_context) for manga_id in normalized_ids
        )
        return BlacklistBatchResult(outcomes=outcomes)

    def is_blacklisted(self, manga_id: str) -> bool:
        """判断漫画是否在黑名单中，供下载入口拦截。"""
        return self.blacklist_repository.exists(manga_id)

    def list_blacklisted(
        self,
        page: int,
        page_size: int,
        search: Optional[str] = None,
    ) -> PageResult[MangaBlacklistItem]:
        """分页查询黑名单，LEFT JOIN 漫画表补充可选标题。"""
        rows, total = self.blacklist_repository.search(page, page_size, search)
        return PageResult(
            items=tuple(
                MangaBlacklistItem(
                    manga_id=record.manga_id,
                    title=title,
                    reason=record.reason,
                    requested_by=record.requested_by,
                    source=record.source,
                    blacklisted_at=record.blacklisted_at,
                    operation_task_id=record.operation_task_id,
                )
                for record, title in rows
            ),
            page=page,
            page_size=page_size,
            total=total,
            pages=ceil(total / page_size),
        )

    def _cascade_delete(
        self,
        manga_id: str,
        context: OperationContext,
        cascade_delete: bool,
    ) -> Tuple[dict, bool, Optional[str]]:
        """绑定模式下执行删除，返回任务元数据与删除结果。"""
        if not cascade_delete or not self.delete_binding:
            return {}, False, None

        manga = self.manga_repository.get(manga_id, include_deleted=True)
        if manga is None or manga.status == "deleted":
            reason = "manga_not_found" if manga is None else "already_deleted"
            self.audit_repository.record(
                event_type="manga.delete_skipped",
                source=context.source,
                result="skipped",
                actor_user_id=context.actor_user_id,
                actor_group_id=context.actor_group_id,
                client_ip=context.client_ip,
                target_type="manga",
                target_id=manga_id,
                metadata={"reason": reason},
            )
            return (
                {"delete_skipped": True, "delete_error_code": reason},
                False,
                reason,
            )

        delete_result = self.manga_service_provider().delete([manga_id], context)
        outcome = delete_result.outcomes[0]
        metadata = {
            "delete_succeeded": outcome.succeeded,
            "delete_task_id": delete_result.task_id,
        }
        if outcome.succeeded:
            logger.info(f"绑定模式下已同步删除漫画: {manga_id}")
            return metadata, True, None
        metadata["delete_error_code"] = outcome.error_code or "delete_failed"
        logger.warning(
            f"绑定模式下删除漫画失败: {manga_id}, "
            f"原因: {outcome.error_code or 'delete_failed'}"
        )
        return metadata, False, outcome.error_code or "delete_failed"

    @staticmethod
    def _normalize_manga_id(manga_id: str) -> str:
        """校验漫画 ID 为纯数字且不超过数据库字段长度。"""
        if not isinstance(manga_id, str):
            raise ValueError("漫画 ID 必须是字符串")
        normalized = manga_id.strip()
        if not normalized:
            raise ValueError("漫画 ID 不能为空")
        if not normalized.isdigit():
            raise ValueError(f"漫画 ID 必须是数字: {manga_id}")
        if len(normalized) > _MAX_MANGA_ID_LENGTH:
            raise ValueError(f"漫画 ID 长度不能超过 {_MAX_MANGA_ID_LENGTH} 位")
        return normalized

    @classmethod
    def _normalize_manga_ids(cls, manga_ids: List[str]) -> List[str]:
        """校验数量并按首次出现顺序去重。"""
        if not manga_ids:
            raise ValueError("请至少提供一个漫画 ID")
        normalized_ids: List[str] = []
        seen: set[str] = set()
        for manga_id in manga_ids:
            normalized = cls._normalize_manga_id(manga_id)
            if normalized in seen:
                continue
            seen.add(normalized)
            normalized_ids.append(normalized)
        if len(normalized_ids) > BLACKLIST_BATCH_LIMIT:
            raise ValueError(f"单次最多操作 {BLACKLIST_BATCH_LIMIT} 个漫画黑名单")
        return normalized_ids

    @staticmethod
    def _normalize_reason(reason: Optional[str]) -> Optional[str]:
        """清理可选拉黑原因，空字符串按未填写处理。"""
        if reason is None:
            return None
        if not isinstance(reason, str):
            raise ValueError("拉黑原因必须是字符串")
        normalized = reason.strip()
        if not normalized:
            return None
        if len(normalized) > _MAX_REASON_LENGTH:
            raise ValueError(f"拉黑原因长度不能超过 {_MAX_REASON_LENGTH} 个字符")
        return normalized
