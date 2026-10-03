"""漫画应用服务，统一执行元数据修改与删除流程。"""

from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

import os

from src.database.repositories import (
    AuditEventRepository,
    FavoriteRepository,
    MangaRepository,
    MangaTagRepository,
)
from src.logging.logger_config import logger

from .contracts import TaskService
from .operation_context import OperationContext
from .results import MangaDeleteOutcome, MangaDeleteResult

# 元数据修改白名单与长度限制，避免越权字段与超长内容写库
_VALID_METADATA_FIELDS = {"title", "author", "tags"}
_MAX_TITLE_LENGTH = 255
_MAX_AUTHOR_LENGTH = 255
_MAX_TAG_COUNT = 50
_MAX_TAG_LENGTH = 64

ADMIN_FAVORITE_DELETE_MESSAGE = "不能删除：该漫画已被管理员收藏，请管理员先取消收藏"

# 删除任务的失败原因对用户展示的简短说明，不包含绝对路径或异常细节
_DELETE_ERROR_MESSAGES = {
    "admin_favorite": ADMIN_FAVORITE_DELETE_MESSAGE,
    "download_conflict": "漫画正在下载中，无法删除",
    "send_conflict": "漫画文件正在发送中，无法删除",
    "delete_directory_missing": "下载目录不存在",
    "file_not_found": "未找到漫画 PDF 文件",
    "delete_failed": "删除漫画失败",
}


class MangaFileDownloadError(Exception):
    """漫画文件不可下载；error_code 供接口层映射为稳定错误码。"""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message


class MangaService:
    """漫画元数据与删除的应用服务，QQ 命令与 Web API 共用。"""

    def __init__(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        manga_repository: MangaRepository,
        tag_repository: MangaTagRepository,
        audit_repository: AuditEventRepository,
        operation_task_service: TaskService,
        download_root: str,
        download_conflict_checker: Callable[[str], bool],
        send_conflict_checker: Callable[[str], bool],
        favorite_repository: Optional[FavoriteRepository] = None,
    ) -> None:
        self.favorite_repository = (
            favorite_repository
            if favorite_repository is not None
            else FavoriteRepository(manga_repository.db_manager)
        )
        self.manga_repository = manga_repository
        self.tag_repository = tag_repository
        self.audit_repository = audit_repository
        self.operation_task_service = operation_task_service
        self.download_root = download_root
        self.download_conflict_checker = download_conflict_checker
        self.send_conflict_checker = send_conflict_checker

    def resolve_file_for_download(self, file_id: int) -> tuple[Path, str]:
        """解析可下载的 PDF 文件路径与建议文件名。

        校验记录存在、相对路径已登记、解析后仍位于下载根目录内、扩展名为
        .pdf 且是普通文件；路径只来自数据库记录，不接受客户端指定。

        Raises:
            MangaFileDownloadError: 记录不存在、路径越界、非 PDF 或文件缺失。
        """
        manga_file = self.manga_repository.get_file(file_id)
        if manga_file is None or not manga_file.relative_path:
            raise MangaFileDownloadError("FILE_NOT_FOUND", "未找到指定文件")
        candidate = self._resolve_pdf_path(manga_file.relative_path)
        if not candidate.is_file():
            raise MangaFileDownloadError("FILE_MISSING", "文件不存在")
        return candidate, manga_file.display_name or candidate.name

    def _resolve_pdf_path(self, relative_path: str) -> Path:
        """统一校验登记路径；允许缺失文件供删除流程清理遗留记录。"""
        root = Path(self.download_root).resolve()
        if not relative_path or Path(relative_path).is_absolute():
            raise MangaFileDownloadError("FILE_PATH_INVALID", "文件路径非法")
        candidate = (root / relative_path).resolve()
        if not candidate.is_relative_to(root):
            raise MangaFileDownloadError("FILE_PATH_INVALID", "文件路径非法")
        if candidate.suffix.lower() != ".pdf":
            raise MangaFileDownloadError("FILE_TYPE_INVALID", "只允许下载 PDF 文件")
        if candidate.exists() and not candidate.is_file():
            raise MangaFileDownloadError("FILE_TYPE_INVALID", "只允许操作 PDF 文件")
        return candidate

    def patch_metadata(
        self,
        manga_id: str,
        fields: Dict[str, object],
        context: Optional[OperationContext] = None,
    ) -> bool:
        """按白名单修改漫画元数据并写审计；漫画不存在时返回 False。

        Args:
            manga_id: 漫画 ID
            fields: 待修改字段，只允许 title/author/tags
            context: 操作来源上下文，缺省按系统来源记录

        Returns:
            bool: 是否找到并更新了漫画记录

        Raises:
            ValueError: 字段不在白名单、类型或取值非法时
        """
        if not fields:
            raise ValueError("至少提供一个要修改的字段")
        unknown_fields = set(fields) - _VALID_METADATA_FIELDS
        if unknown_fields:
            raise ValueError(f"不允许修改的字段: {sorted(unknown_fields)}")

        title: Optional[str] = None
        author: Optional[str] = None
        tags: Optional[List[str]] = None
        if "title" in fields:
            title = self._normalize_text(fields["title"], "标题", _MAX_TITLE_LENGTH)
            if not title:
                raise ValueError("标题不能为空")
        if "author" in fields:
            author = self._normalize_text(fields["author"], "作者", _MAX_AUTHOR_LENGTH)
        if "tags" in fields:
            tags = self._normalize_tags(fields["tags"])

        if not self.manga_repository.update_metadata(
            manga_id, title=title, author=author
        ):
            return False
        if tags is not None:
            self.tag_repository.replace_for_manga(manga_id, tags)

        operation_context = context or OperationContext.system()
        self.audit_repository.record(
            event_type="manga.metadata_updated",
            source=operation_context.source,
            result="succeeded",
            actor_user_id=operation_context.actor_user_id,
            actor_group_id=operation_context.actor_group_id,
            client_ip=operation_context.client_ip,
            target_type="manga",
            target_id=manga_id,
            metadata={"changed_fields": sorted(fields)},
        )
        return True

    def delete(
        self,
        manga_ids: Sequence[str],
        context: Optional[OperationContext] = None,
    ) -> MangaDeleteResult:
        """统一执行单个或批量删除，返回每个漫画的结构化结果。

        删除流程：管理员收藏保护检查 → 冲突检查（下载/发送）→ 标记 deleting → 删除磁盘 PDF →
        级联清理漫画、文件与标签记录。全部成功任务才 succeed，
        任一失败则任务失败并保留成功/失败计数。
        """
        if not manga_ids:
            raise ValueError("请至少提供一个漫画 ID")
        operation_context = context or OperationContext.system()
        single_target = manga_ids[0] if len(manga_ids) == 1 else None
        task = self.operation_task_service.create(
            "delete", operation_context, manga_id=single_target
        )
        self.operation_task_service.start(task.id, "deleting")

        outcomes = tuple(self._delete_one(manga_id) for manga_id in manga_ids)
        result = MangaDeleteResult(task_id=task.id, outcomes=outcomes)
        if result.all_succeeded:
            self.operation_task_service.succeed(
                task.id,
                metadata={"file_count": result.deleted_file_count},
                context=operation_context,
            )
        elif single_target is not None:
            outcome = outcomes[0]
            error_code = outcome.error_code or "delete_failed"
            self.operation_task_service.fail(
                task.id,
                error_code,
                _DELETE_ERROR_MESSAGES.get(error_code, "删除漫画失败"),
                context=operation_context,
            )
        else:
            self.operation_task_service.fail(
                task.id,
                "batch_delete_partial_failure",
                f"{result.failed_count} 个漫画删除失败",
                context=operation_context,
                metadata={
                    "succeeded_count": result.succeeded_count,
                    "failed_count": result.failed_count,
                },
            )
        return result

    def _delete_one(self, manga_id: str) -> MangaDeleteOutcome:
        """删除单个漫画，冲突与预期失败返回结构化结果而不抛出。"""
        if self.favorite_repository.has_admin_favorite(manga_id):
            logger.warning(f"漫画 {manga_id} {ADMIN_FAVORITE_DELETE_MESSAGE}")
            return MangaDeleteOutcome(manga_id, False, "admin_favorite", 0)
        if self.download_conflict_checker(manga_id):
            logger.warning(f"漫画 {manga_id} 正在下载中，跳过删除")
            return MangaDeleteOutcome(manga_id, False, "download_conflict", 0)
        if self.send_conflict_checker(manga_id):
            logger.warning(f"漫画 {manga_id} 的文件正在发送中，跳过删除")
            return MangaDeleteOutcome(manga_id, False, "send_conflict", 0)
        if not os.path.isdir(self.download_root):
            logger.error(f"下载目录不存在，无法删除漫画 {manga_id}")
            return MangaDeleteOutcome(manga_id, False, "delete_directory_missing", 0)

        manga = self.manga_repository.get(manga_id)
        if manga is None:
            logger.warning(f"未找到漫画 {manga_id} 的数据库记录，跳过删除")
            return MangaDeleteOutcome(manga_id, False, "file_not_found", 0)

        try:
            # 删除目标只取数据库登记路径；缺失文件仅清理记录，不猜测其他文件。
            pdf_paths = [
                self._resolve_pdf_path(manga_file.relative_path)
                for manga_file in manga.files
            ]
            # 先标记 deleting 再删磁盘文件，便于并发方识别正在删除的文件
            self.manga_repository.mark_manga_deleting(manga_id)
            deleted_count = 0
            for pdf_path in pdf_paths:
                if pdf_path.exists():
                    self._remove_pdf(str(pdf_path))
                    deleted_count += 1
            # 保留已删除漫画元数据供 WebUI 查询，关联文件、标签、收藏和进度一并清理
            self.manga_repository.mark_manga_deleted(manga_id)
            return MangaDeleteOutcome(manga_id, True, None, deleted_count)
        except Exception as error:  # pylint: disable=broad-exception-caught
            logger.error(f"删除漫画 {manga_id} 失败: {error}")
            return MangaDeleteOutcome(
                manga_id, False, "delete_failed", 0, type(error).__name__
            )

    def _remove_pdf(self, pdf_path: str) -> None:
        """删除下载目录内的单个 PDF 文件，路径越界时明确报错。"""
        try:
            Path(pdf_path).resolve().relative_to(Path(self.download_root).resolve())
        except ValueError as error:
            raise ValueError("待删除的 PDF 文件不在下载根目录内") from error
        os.remove(pdf_path)
        logger.info(f"成功删除漫画PDF文件: {pdf_path}")

    @staticmethod
    def _normalize_text(value: object, label: str, max_length: int) -> str:
        """校验并清理单行文本字段。"""
        if not isinstance(value, str):
            raise ValueError(f"{label}必须是字符串")
        normalized = value.strip()
        if len(normalized) > max_length:
            raise ValueError(f"{label}长度不能超过 {max_length} 个字符")
        return normalized

    @staticmethod
    def _normalize_tags(value: object) -> List[str]:
        """校验并清理标签列表，按首次出现顺序去重。"""
        if not isinstance(value, (list, tuple)):
            raise ValueError("标签必须是字符串列表")
        normalized_tags: List[str] = []
        seen: set[str] = set()
        for item in value:
            if not isinstance(item, str):
                raise ValueError("标签必须是字符串列表")
            tag = item.strip()
            if not tag:
                continue
            if len(tag) > _MAX_TAG_LENGTH:
                raise ValueError(f"标签长度不能超过 {_MAX_TAG_LENGTH} 个字符")
            normalized_name = " ".join(tag.split()).casefold()
            if normalized_name in seen:
                continue
            seen.add(normalized_name)
            normalized_tags.append(tag)
        if len(normalized_tags) > _MAX_TAG_COUNT:
            raise ValueError(f"标签数量不能超过 {_MAX_TAG_COUNT} 个")
        return normalized_tags
