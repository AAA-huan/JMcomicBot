"""自定义漫画文件夹应用服务，统一名称校验与审计记录。"""

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from src.database.models import MangaFolder
from src.database.repositories import FolderRepository
from src.database.repositories.audit_event_repository import AuditEventRepository
from src.service.operation_context import OperationContext

# 单次批量加入/移出的漫画数量上限，与批量删除保持一致
FOLDER_MEMBER_BATCH_LIMIT = 100
_MAX_FOLDER_NAME_LENGTH = 64
_MAX_MANGA_ID_LENGTH = 32


class FolderNameConflict(ValueError):
    """文件夹重名冲突，路由层映射为 409。"""


@dataclass(frozen=True)
class FolderItem:
    """可安全返回浏览器的文件夹摘要。"""

    id: int
    name: str
    sort_order: int
    manga_count: int
    created_at: datetime
    updated_at: datetime


class FolderService:
    """维护本地文件夹分组；删除文件夹只清理成员关系，不删除漫画。"""

    def __init__(
        self,
        folder_repository: FolderRepository,
        audit_repository: AuditEventRepository,
    ) -> None:
        self.folder_repository = folder_repository
        self.audit_repository = audit_repository

    def list_folders(self) -> List[FolderItem]:
        """查询全部文件夹与成员数。"""
        return [
            self._to_item(folder, count)
            for folder, count in self.folder_repository.list()
        ]

    def create_folder(
        self, name: str, context: Optional[OperationContext] = None
    ) -> FolderItem:
        """创建文件夹，重名时抛出 FolderNameConflict。"""
        normalized = self._normalize_name(name)
        if self.folder_repository.get_by_name(normalized) is not None:
            raise FolderNameConflict(f"文件夹名称已存在: {normalized}")
        folder = self.folder_repository.create(normalized)
        self._record_audit("folder.created", folder.id, context)
        return self._to_item(folder, 0)

    def rename_folder(
        self, folder_id: int, name: str, context: Optional[OperationContext] = None
    ) -> FolderItem:
        """重命名文件夹；名称与其他文件夹冲突时拒绝。"""
        normalized = self._normalize_name(name)
        self._require_folder(folder_id)
        conflict = self.folder_repository.get_by_name(normalized)
        if conflict is not None and conflict.id != folder_id:
            raise FolderNameConflict(f"文件夹名称已存在: {normalized}")
        folder = self.folder_repository.rename(folder_id, normalized)
        if folder is None:
            raise LookupError("未找到指定文件夹")
        self._record_audit("folder.renamed", folder_id, context)
        return self._to_item(folder, len(self.folder_repository.member_ids(folder_id)))

    def set_folder_order(
        self,
        folder_id: int,
        sort_order: int,
        context: Optional[OperationContext] = None,
    ) -> FolderItem:
        """更新文件夹排序值。"""
        self._require_folder(folder_id)
        folder = self.folder_repository.set_sort_order(folder_id, sort_order)
        if folder is None:
            raise LookupError("未找到指定文件夹")
        self._record_audit("folder.updated", folder_id, context)
        return self._to_item(folder, len(self.folder_repository.member_ids(folder_id)))

    def delete_folder(
        self, folder_id: int, context: Optional[OperationContext] = None
    ) -> None:
        """删除文件夹；成员关系随外键级联清理，漫画本体不受影响。"""
        if not self.folder_repository.delete(folder_id):
            raise LookupError("未找到指定文件夹")
        self._record_audit("folder.deleted", folder_id, context)

    def add_mangas(
        self,
        folder_id: int,
        manga_ids: List[str],
        context: Optional[OperationContext] = None,
    ) -> dict:
        """批量加入文件夹，已在夹内的幂等跳过并计入 unchanged。"""
        self._require_folder(folder_id)
        normalized_ids = self._normalize_manga_ids(manga_ids)
        existing = self.folder_repository.existing_ids(normalized_ids)
        missing = [manga_id for manga_id in normalized_ids if manga_id not in existing]
        if missing:
            raise ValueError(f"漫画不存在或已删除: {', '.join(missing)}")
        already_in = self.folder_repository.members_in_folder(folder_id, normalized_ids)
        to_add = [manga_id for manga_id in normalized_ids if manga_id not in already_in]
        added_count = self.folder_repository.add_members(folder_id, to_add)
        if added_count > 0:
            self._record_members_audit(folder_id, "added", added_count, context)
        return {"added": to_add, "unchanged_count": len(already_in)}

    def remove_mangas(
        self,
        folder_id: int,
        manga_ids: List[str],
        context: Optional[OperationContext] = None,
    ) -> dict:
        """批量移出文件夹，不在夹内的幂等忽略。"""
        self._require_folder(folder_id)
        normalized_ids = self._normalize_manga_ids(manga_ids)
        removed_count = self.folder_repository.remove_members(folder_id, normalized_ids)
        if removed_count > 0:
            self._record_members_audit(folder_id, "removed", removed_count, context)
        return {"removed_count": removed_count}

    def folders_for_manga(self, manga_id: str) -> List[int]:
        """查询漫画所在的全部文件夹 ID，供详情页菜单回显。"""
        return self.folder_repository.folders_for_manga(manga_id)

    def _require_folder(self, folder_id: int) -> MangaFolder:
        """确认文件夹存在，否则抛出 LookupError 由路由层映射为 404。"""
        folder = self.folder_repository.get(folder_id)
        if folder is None:
            raise LookupError("未找到指定文件夹")
        return folder

    def _record_audit(
        self,
        event_type: str,
        folder_id: int,
        context: Optional[OperationContext],
        metadata: Optional[dict] = None,
    ) -> None:
        """写文件夹审计事件，归属来自服务端认证上下文。"""
        actor = context or OperationContext.system()
        self.audit_repository.record(
            event_type=event_type,
            source=actor.source,
            result="succeeded",
            actor_user_id=actor.actor_user_id,
            actor_group_id=actor.actor_group_id,
            client_ip=actor.client_ip,
            target_type="folder",
            target_id=str(folder_id),
            metadata=metadata,
        )

    def _record_members_audit(
        self,
        folder_id: int,
        action: str,
        manga_count: int,
        context: Optional[OperationContext],
    ) -> None:
        """成员变更审计，仅在真实发生变化时记录数量。"""
        self._record_audit(
            "folder.members_changed",
            folder_id,
            context,
            metadata={"action": action, "manga_count": manga_count},
        )

    @staticmethod
    def _to_item(folder: MangaFolder, manga_count: int) -> FolderItem:
        return FolderItem(
            id=folder.id,
            name=folder.name,
            sort_order=folder.sort_order,
            manga_count=manga_count,
            created_at=folder.created_at,
            updated_at=folder.updated_at,
        )

    @staticmethod
    def _normalize_name(name: str) -> str:
        """清理文件夹名称，空值或超长直接拒绝。"""
        if not isinstance(name, str):
            raise ValueError("文件夹名称必须是字符串")
        normalized = name.strip()
        if not normalized:
            raise ValueError("文件夹名称不能为空")
        if len(normalized) > _MAX_FOLDER_NAME_LENGTH:
            raise ValueError(f"文件夹名称长度不能超过 {_MAX_FOLDER_NAME_LENGTH} 个字符")
        return normalized

    @staticmethod
    def _normalize_manga_ids(manga_ids: List[str]) -> List[str]:
        """校验数量并按首次出现顺序去重，与黑名单批处理规则一致。"""
        if not manga_ids:
            raise ValueError("请至少提供一个漫画 ID")
        normalized_ids: List[str] = []
        seen: set[str] = set()
        for manga_id in manga_ids:
            if not isinstance(manga_id, str):
                raise ValueError("漫画 ID 必须是字符串")
            normalized = manga_id.strip()
            if not normalized or not normalized.isdigit():
                raise ValueError(f"漫画 ID 必须是数字: {manga_id}")
            if len(normalized) > _MAX_MANGA_ID_LENGTH:
                raise ValueError(f"漫画 ID 长度不能超过 {_MAX_MANGA_ID_LENGTH} 位")
            if normalized in seen:
                continue
            seen.add(normalized)
            normalized_ids.append(normalized)
        if len(normalized_ids) > FOLDER_MEMBER_BATCH_LIMIT:
            raise ValueError(f"单次最多操作 {FOLDER_MEMBER_BATCH_LIMIT} 个漫画")
        return normalized_ids
