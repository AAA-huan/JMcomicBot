"""文件校验应用服务，检查 PDF 路径安全、存在性、大小、修改时间与 SHA-256。"""

from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Sequence

from src.database.models import MangaFile, utc_now
from src.database.repositories import MangaRepository, ScanRecordRepository
from src.logging.logger_config import logger
from src.service.contracts import TaskService
from src.service.operation_context import OperationContext
from src.service.results import VerifyResult
from src.utils.file_hash import sha256_of
from src.utils.manga_scanner import DOWNLOAD_PATH_LABEL

_VERIFIABLE_STATUSES = {"ready", "missing", "corrupted", "invalid_path"}


def _utc_mtime(timestamp: float) -> datetime:
    """将文件系统 mtime 转换为 UTC 无时区时间，与数据库时间语义一致。"""
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).replace(tzinfo=None)


class VerifyService:
    """逐文件校验服务，任务事件与审计由 OperationTaskService 统一记录。

    文件读取与哈希在数据库事务外完成，每个文件写入使用独立短事务。
    校验不重算 page_count，页码保持下载时来源。
    """

    def __init__(
        self,
        manga_repo: MangaRepository,
        scan_record_repo: ScanRecordRepository,
        operation_task_service: TaskService,
        download_root: str,
    ) -> None:
        self.manga_repo = manga_repo
        self.scan_record_repo = scan_record_repo
        self.operation_task_service = operation_task_service
        self.download_root = Path(download_root).resolve()

    def verify(
        self,
        manga_ids: Optional[Sequence[str]] = None,
        context: Optional[OperationContext] = None,
    ) -> VerifyResult:
        """校验指定漫画的文件（默认全部），并写入任务、统计与审计。

        Args:
            manga_ids: 限定校验的漫画ID列表，None 表示全部
            context: 操作来源上下文，缺省为系统任务

        Returns:
            VerifyResult: 校验结果汇总
        """
        if not self.download_root.is_dir():
            raise FileNotFoundError(f"下载根目录不存在: {self.download_root}")
        operation_context = context or OperationContext.system()
        task = self.operation_task_service.create("verify", operation_context)
        self.operation_task_service.start(task.id, "verifying")
        try:
            files = self._collect_files(manga_ids)
            total = len(files)
            counts = {
                "ready": 0,
                "missing": 0,
                "corrupted": 0,
                "invalid_path": 0,
                "error": 0,
            }
            for index, manga_file in enumerate(files, start=1):
                counts[self._verify_one(manga_file)] += 1
                if total:
                    self.operation_task_service.progress(
                        task.id,
                        "verifying",
                        int(index * 100 / total),
                        metadata={"file_count": index},
                    )
            self.scan_record_repo.create(
                task_id=task.id,
                task_type="verify",
                path_label=DOWNLOAD_PATH_LABEL,
                file_count=total,
                missing_count=counts["missing"],
                corrupted_count=counts["corrupted"],
                error_count=counts["error"],
            )
            self.operation_task_service.succeed(
                task.id,
                metadata={
                    "file_count": total,
                    "missing_count": counts["missing"],
                    "corrupted_count": counts["corrupted"],
                    "failed_count": counts["error"],
                },
                context=operation_context,
            )
            return VerifyResult(
                task_id=task.id,
                file_count=total,
                ready_count=counts["ready"],
                missing_count=counts["missing"],
                corrupted_count=counts["corrupted"],
                invalid_path_count=counts["invalid_path"],
                error_count=counts["error"],
            )
        except Exception as error:
            self.operation_task_service.fail(
                task.id,
                "verify_failed",
                type(error).__name__,
                context=operation_context,
            )
            raise

    def _collect_files(self, manga_ids: Optional[Sequence[str]]) -> List[MangaFile]:
        """收集待校验文件；指定漫画不存在时明确报错。"""
        if manga_ids is None:
            return self.manga_repo.list_verifiable_files()
        files: List[MangaFile] = []
        for manga_id in manga_ids:
            if self.manga_repo.get(manga_id) is None:
                raise ValueError(f"漫画不存在: {manga_id}")
            files.extend(
                manga_file
                for manga_file in self.manga_repo.list_files(manga_id)
                if manga_file.status in _VERIFIABLE_STATUSES
            )
        return files

    def _verify_one(self, manga_file: MangaFile) -> str:
        """校验单个文件并返回结果分类：ready/missing/corrupted/invalid_path/error。"""
        state, resolved = self._classify_path(manga_file)
        if state == "invalid_path":
            self.manga_repo.update_file_status(manga_file.id, "invalid_path")
            return "invalid_path"
        if state == "missing":
            # 磁盘无文件：文件与漫画统一标记缺失，不删除数据库记录
            self.manga_repo.mark_manga_missing(manga_file.manga_id)
            return "missing"

        if resolved is None:
            raise RuntimeError(f"文件路径解析结果缺失: {manga_file.relative_path}")
        try:
            stat = resolved.stat()
            sha256 = sha256_of(resolved)
        except OSError as error:
            logger.warning(
                f"校验文件读取失败，已跳过并计入错误数: {manga_file.relative_path}: {error}"
            )
            return "error"

        # 大小或修改时间变化时清空旧摘要，按首次计算重新标记
        registered_sha = manga_file.sha256
        if stat.st_size != manga_file.file_size_bytes:
            registered_sha = None
        file_mtime = _utc_mtime(stat.st_mtime)
        if manga_file.file_mtime != file_mtime:
            registered_sha = None

        if registered_sha is not None and registered_sha != sha256:
            # 已有登记值且与磁盘不符：标记损坏，保留旧摘要便于诊断，不覆盖
            self.manga_repo.apply_file_verification(
                file_id=manga_file.id,
                status="corrupted",
                file_size_bytes=stat.st_size,
                file_mtime=file_mtime,
                sha256=manga_file.sha256,
                verified_at=None,
            )
            return "corrupted"

        self.manga_repo.apply_file_verification(
            file_id=manga_file.id,
            status="ready",
            file_size_bytes=stat.st_size,
            file_mtime=file_mtime,
            sha256=sha256,
            verified_at=utc_now(),
        )
        return "ready"

    def _classify_path(self, manga_file: MangaFile) -> tuple[str, Optional[Path]]:
        """判定文件路径安全性，返回 (状态, 解析路径)。

        状态为 valid / missing / invalid_path；只做文件系统检查，不访问数据库。
        """
        if not manga_file.relative_path:
            return "invalid_path", None
        resolved = (self.download_root / manga_file.relative_path).resolve()
        try:
            resolved.relative_to(self.download_root)
        except ValueError:
            return "invalid_path", None
        if resolved.suffix.lower() != ".pdf":
            return "invalid_path", None
        if not resolved.exists():
            return "missing", None
        if not resolved.is_file():
            return "invalid_path", None
        return "valid", resolved
