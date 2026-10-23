"""漫画数据库导出与导入应用服务。

导出使用 SQLite backup API 生成一致性整库快照，与 `export.json` 一起打包为
zip 供跨设备迁移；导入先校验结构与版本兼容性，确认后备份旧库、替换
`main.db`，由接口层触发异步重启。PDF 等文件资产不在本服务范围内。
"""

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from stat import S_IMODE
from typing import Dict, Iterator, List, Optional, Tuple
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile

import json
import os
import re
import shutil
import sqlite3
import tempfile

from src.database.database import DatabaseManager
from src.database.migrations import (
    backup_database,
    get_schema_revision,
    is_ancestor_revision,
)
from src.database.models import utc_now
from src.database.repositories import AuditEventRepository
from src.logging.logger_config import logger
from src.service.maintenance_lock import DATABASE_MAINTENANCE_LOCK
from src.service.operation_context import OperationContext
from src.service.results import DataExportResult, ImportPreview
from src.utils.file_hash import sha256_of

# 导出格式版本；字段或含义变更时必须升级，导入方拒绝未知版本
EXPORT_FORMAT_VERSION = 1

# 预览与一致性记录统计的业务表；旧版本不存在的表自动跳过
_COUNTED_TABLES: Tuple[str, ...] = (
    "manga",
    "manga_file",
    "manga_favorite",
    "reading_progress",
    "reading_setting",
    "manga_blacklist",
    "operation_task",
    "audit_event",
)

_SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")

ZipSource = bytes | Path


class DataImportError(Exception):
    """导入校验或执行失败，携带接口层可映射的稳定错误码。"""

    def __init__(self, error_code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.status_code = status_code


class DataMigrationService:  # pylint: disable=too-many-instance-attributes
    """生成数据导出包，并在校验通过后替换整库。"""

    def __init__(
        self,
        db_manager: DatabaseManager,
        audit_repository: AuditEventRepository,
        db_path_config: str,
        manga_download_path: str,
    ) -> None:
        self.db_manager = db_manager
        self.audit_repository = audit_repository
        self.db_path_config = db_path_config
        self.manga_download_path = manga_download_path

    def export_data(
        self,
        context: Optional[OperationContext] = None,
    ) -> DataExportResult:
        """生成包含整库备份与一致性记录的 zip，返回临时文件信息。"""
        operation_context = context or OperationContext.system()
        with DATABASE_MAINTENANCE_LOCK:
            exported_at = utc_now()
            schema_revision = get_schema_revision(self.db_manager.engine)
            export_dir = Path(tempfile.mkdtemp(prefix="jmbot-data-export-"))
            db_filename = f"main-{exported_at:%Y%m%d-%H%M%S}.db"
            db_path = export_dir / db_filename
            json_path = export_dir / "export.json"
            try:
                backup_database(self.db_manager.engine, str(db_path))
                db_sha256 = sha256_of(db_path)
                table_counts = self._read_table_counts(db_path)
                payload = {
                    "format_version": EXPORT_FORMAT_VERSION,
                    "schema_revision": schema_revision,
                    "exported_at": self._iso_utc(exported_at),
                    "db_filename": db_filename,
                    "db_sha256": db_sha256,
                    "table_counts": table_counts,
                    "export_env": {
                        "db_path": self.db_path_config,
                        "manga_download_path": self.manga_download_path,
                    },
                }
                json_path.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                zip_filename = (
                    f"data-export-{exported_at:%Y%m%d-%H%M%S}"
                    f"-schema{schema_revision}.zip"
                )
                zip_path = export_dir / zip_filename
                with ZipFile(zip_path, "w", ZIP_DEFLATED) as archive:
                    archive.write(db_path, arcname=db_filename)
                    archive.write(json_path, arcname="export.json")
                # zip 已包含全部内容，删除中间文件只保留待下载压缩包
                db_path.unlink()
                json_path.unlink()
                file_size_bytes = zip_path.stat().st_size
                self.audit_repository.record(
                    event_type="data.exported",
                    source=operation_context.source,
                    result="succeeded",
                    actor_user_id=operation_context.actor_user_id,
                    actor_group_id=operation_context.actor_group_id,
                    client_ip=operation_context.client_ip,
                    target_type="database",
                    target_id="main",
                    metadata={
                        "schema_revision": schema_revision,
                        "db_filename": db_filename,
                        "file_size_bytes": file_size_bytes,
                    },
                )
            except Exception:
                shutil.rmtree(export_dir, ignore_errors=True)
                raise
        return DataExportResult(
            path=zip_path,
            filename=zip_filename,
            file_size_bytes=file_size_bytes,
            schema_revision=schema_revision,
            exported_at=exported_at,
        )

    def validate_import(self, zip_source: ZipSource) -> ImportPreview:
        """校验 zip 结构、摘要、可读性与 schema 祖先链，不替换任何文件。"""
        with self._staged_import(zip_source) as (preview, _db_path):
            return preview

    def apply_import(
        self,
        zip_source: ZipSource,
        context: Optional[OperationContext] = None,
    ) -> None:
        """重新校验后替换整库；失败时自动恢复旧库并抛出 DataImportError。

        接口层负责在成功返回后触发异步重启，本方法只保证磁盘上的数据库
        已被替换且可供下一次启动读取。
        """
        operation_context = context or OperationContext.system()
        # 非阻塞加锁：并发导入直接拒绝，而不是排队等待替换数据库
        if not DATABASE_MAINTENANCE_LOCK.acquire(  # pylint: disable=consider-using-with
            blocking=False
        ):
            raise DataImportError(
                "DATA_IMPORT_CONFLICT",
                "已有备份、导出或导入操作正在进行，请稍后重试",
                409,
            )
        try:
            # 不信任上一次校验结果：文件可能在两次请求之间被替换
            with self._staged_import(zip_source) as (preview, staged_db):
                self._apply_staged(preview, staged_db, operation_context)
        finally:
            DATABASE_MAINTENANCE_LOCK.release()

    @contextmanager
    def _staged_import(
        self, zip_source: ZipSource
    ) -> Iterator[Tuple[ImportPreview, Path]]:
        """把上传内容解压到独立临时目录，校验后交给调用方使用。"""
        work_dir = Path(tempfile.mkdtemp(prefix="jmbot-data-import-"))
        try:
            if isinstance(zip_source, bytes):
                zip_path = work_dir / "upload.zip"
                zip_path.write_bytes(zip_source)
            else:
                zip_path = Path(zip_source)
            preview, db_path = self._extract_and_validate(zip_path, work_dir)
            yield preview, db_path
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    def _extract_and_validate(
        self, zip_path: Path, work_dir: Path
    ) -> Tuple[ImportPreview, Path]:
        """解压并完成全部只读校验，返回预览与实际数据库文件。"""
        db_path, json_bytes, db_filename = self._extract_zip(zip_path, work_dir)
        payload = self._parse_export_json(json_bytes)
        preview = self._validate_payload(payload, db_path, db_filename)
        return preview, db_path

    @staticmethod
    def _extract_zip(zip_path: Path, work_dir: Path) -> Tuple[Path, bytes, str]:
        """按固定结构提取 zip，拒绝多余文件、目录与路径穿越。"""
        try:
            with ZipFile(zip_path) as archive:
                entries = [info for info in archive.infolist() if not info.is_dir()]
                if len(entries) != 2:
                    raise DataImportError(
                        "DATA_IMPORT_INVALID",
                        "数据包结构不正确：必须恰好包含一个 .db 与 export.json",
                    )
                db_entries = [
                    info for info in entries if info.filename.lower().endswith(".db")
                ]
                json_entries = [
                    info for info in entries if info.filename == "export.json"
                ]
                if len(db_entries) != 1 or len(json_entries) != 1:
                    raise DataImportError(
                        "DATA_IMPORT_INVALID",
                        "数据包结构不正确：必须恰好包含一个 .db 与 export.json",
                    )
                db_entry = db_entries[0]
                # 只接受 zip 根目录内的文件，防止 ../ 或绝对路径逃逸
                if (
                    Path(db_entry.filename).name != db_entry.filename
                    or "\\" in db_entry.filename
                ):
                    raise DataImportError(
                        "DATA_IMPORT_INVALID", "数据包内数据库文件名非法"
                    )
                db_path = work_dir / db_entry.filename
                with (
                    archive.open(db_entry) as source,
                    db_path.open("wb") as destination,
                ):
                    shutil.copyfileobj(source, destination)
                json_bytes = archive.read(json_entries[0])
        except BadZipFile as error:
            raise DataImportError(
                "DATA_IMPORT_INVALID", "上传文件不是有效的 zip 数据包"
            ) from error
        return db_path, json_bytes, db_entry.filename

    @staticmethod
    def _parse_export_json(json_bytes: bytes) -> Dict[str, object]:
        """解析 export.json，非法 JSON 统一映射为校验失败。"""
        try:
            payload = json.loads(json_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise DataImportError(
                "DATA_IMPORT_INVALID", "export.json 不是有效的 UTF-8 JSON"
            ) from error
        if not isinstance(payload, dict):
            raise DataImportError("DATA_IMPORT_INVALID", "export.json 结构不正确")
        return payload

    def _validate_payload(
        self, payload: Dict[str, object], db_path: Path, db_filename: str
    ) -> ImportPreview:
        """校验字段、摘要、schema 兼容性与表行数一致性。"""
        format_version = payload.get("format_version")
        if (
            not isinstance(format_version, int)
            or isinstance(format_version, bool)
            or format_version != EXPORT_FORMAT_VERSION
        ):
            raise DataImportError(
                "DATA_IMPORT_INVALID",
                f"不支持的导出格式版本：{format_version}",
            )

        schema_revision = self._required_string(payload, "schema_revision")
        exported_at = self._required_string(payload, "exported_at")
        try:
            datetime.fromisoformat(exported_at.replace("Z", "+00:00"))
        except ValueError as error:
            raise DataImportError(
                "DATA_IMPORT_INVALID", "export.json 的导出时间格式不正确"
            ) from error

        declared_db_filename = self._required_string(payload, "db_filename")
        if declared_db_filename != db_filename:
            raise DataImportError(
                "DATA_IMPORT_INVALID", "export.json 中的数据库文件名与数据包不一致"
            )

        declared_sha256 = self._required_string(payload, "db_sha256")
        if not _SHA256_PATTERN.fullmatch(declared_sha256):
            raise DataImportError(
                "DATA_IMPORT_INVALID", "export.json 中的数据库校验和格式不正确"
            )
        actual_sha256 = sha256_of(db_path)
        if actual_sha256.lower() != declared_sha256.lower():
            raise DataImportError(
                "DATA_IMPORT_INVALID", "数据库文件校验和不一致，数据可能已损坏或被篡改"
            )

        declared_counts = self._parse_table_counts(payload)
        export_env = self._parse_export_env(payload)

        actual_revision, actual_counts = self._inspect_database(db_path)
        if actual_revision != schema_revision:
            raise DataImportError(
                "DATA_IMPORT_INVALID", "export.json 与数据库的 schema 版本不一致"
            )
        if not is_ancestor_revision(actual_revision):
            raise DataImportError(
                "DATA_IMPORT_INVALID", "数据来自不兼容的版本，当前不支持"
            )
        for table, declared_count in declared_counts.items():
            if table not in actual_counts:
                raise DataImportError(
                    "DATA_IMPORT_INVALID", f"导出记录包含数据库不存在的表：{table}"
                )
            if actual_counts[table] != declared_count:
                raise DataImportError(
                    "DATA_IMPORT_INVALID",
                    f"表 {table} 的行数与 export.json 不一致",
                )
        if "manga" not in actual_counts:
            raise DataImportError("DATA_IMPORT_INVALID", "数据库缺少漫画主表，无法导入")

        current_schema_revision = get_schema_revision(self.db_manager.engine)
        return ImportPreview(
            format_version=format_version,
            schema_revision=actual_revision,
            exported_at=exported_at,
            db_filename=db_filename,
            db_sha256=actual_sha256,
            table_counts=actual_counts,
            export_env=export_env,
            current_schema_revision=current_schema_revision,
            path_warnings=self._build_path_warnings(export_env),
        )

    @staticmethod
    def _required_string(payload: Dict[str, object], key: str) -> str:
        """读取必填字符串字段，缺失或类型错误时拒绝导入。"""
        value = payload.get(key)
        if not isinstance(value, str) or not value:
            raise DataImportError(
                "DATA_IMPORT_INVALID", f"export.json 缺少有效字段：{key}"
            )
        return value

    @staticmethod
    def _parse_table_counts(payload: Dict[str, object]) -> Dict[str, int]:
        """校验表行数字段，只接受当前业务表与合法非负整数。"""
        value = payload.get("table_counts")
        if not isinstance(value, dict):
            raise DataImportError(
                "DATA_IMPORT_INVALID", "export.json 缺少有效的表行数记录"
            )
        counts: Dict[str, int] = {}
        for table, count in value.items():
            if table not in _COUNTED_TABLES:
                raise DataImportError(
                    "DATA_IMPORT_INVALID", f"导出记录包含未知表：{table}"
                )
            if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                raise DataImportError("DATA_IMPORT_INVALID", f"表 {table} 的行数不合法")
            counts[table] = count
        return counts

    def _parse_export_env(self, payload: Dict[str, object]) -> Dict[str, str]:
        """校验导出环境路径字段，用于导入前提示配置差异。"""
        value = payload.get("export_env")
        if not isinstance(value, dict):
            raise DataImportError("DATA_IMPORT_INVALID", "export.json 缺少导出环境信息")
        environment: Dict[str, str] = {}
        for key in ("db_path", "manga_download_path"):
            item = value.get(key)
            if not isinstance(item, str):
                raise DataImportError(
                    "DATA_IMPORT_INVALID", f"export.json 缺少有效字段：export_env.{key}"
                )
            environment[key] = item
        return environment

    @staticmethod
    def _inspect_database(db_path: Path) -> Tuple[str, Dict[str, int]]:
        """以只读方式打开数据库，读取 schema revision 与表行数。"""
        uri = f"{db_path.resolve().as_uri()}?mode=ro"
        try:
            with sqlite3.connect(uri, uri=True) as connection:
                row = connection.execute(
                    "SELECT version_num FROM alembic_version"
                ).fetchone()
                if row is None or not row[0]:
                    raise DataImportError(
                        "DATA_IMPORT_INVALID", "数据库缺少 schema 版本记录"
                    )
                revision = str(row[0])
                table_names = {
                    str(item[0])
                    for item in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                counts: Dict[str, int] = {}
                for table in _COUNTED_TABLES:
                    if table not in table_names:
                        continue
                    count = connection.execute(
                        f'SELECT COUNT(*) FROM "{table}"'
                    ).fetchone()
                    counts[table] = int(count[0]) if count is not None else 0
        except sqlite3.Error as error:
            raise DataImportError(
                "DATA_IMPORT_INVALID", "数据库文件无法读取"
            ) from error
        return revision, counts

    @staticmethod
    def _read_table_counts(db_path: Path) -> Dict[str, int]:
        """从导出的数据库文件统计行数，保证与 export.json 一致。"""
        _revision, counts = DataMigrationService._inspect_database(db_path)
        return counts

    def _build_path_warnings(self, export_env: Dict[str, str]) -> Tuple[str, ...]:
        """比较导出与当前路径配置，生成不阻塞导入的提示。"""
        warnings: List[str] = []
        exported_download = export_env["manga_download_path"]
        if exported_download != self.manga_download_path:
            warnings.append(
                f"导出环境下载目录为 {exported_download}，当前为 "
                f"{self.manga_download_path}，请确保 PDF 已拷贝到当前目录或调整配置"
            )
        exported_db = export_env["db_path"]
        if exported_db != self.db_path_config:
            warnings.append(
                f"导出环境数据库目录为 {exported_db}，当前为 {self.db_path_config}，"
                "导入后的数据库将写入当前目录"
            )
        return tuple(warnings)

    def _apply_staged(
        self,
        preview: ImportPreview,
        staged_db: Path,
        context: OperationContext,
    ) -> None:
        """写审计、关闭连接、备份旧库并安装新库，异常时自动恢复。"""
        db_path = Path(self.db_manager.db_file)
        if not db_path.is_file():
            raise DataImportError(
                "DATA_IMPORT_FAILED", "当前数据库文件不存在，无法执行导入", 500
            )
        original_stat = db_path.stat()
        timestamp = f"{utc_now():%Y%m%d-%H%M%S}"
        backup_targets = [
            Path(f"{db_path}{suffix}.pre-import-{timestamp}.bak")
            for suffix in ("", "-wal", "-shm")
        ]
        if any(target.exists() for target in backup_targets):
            raise DataImportError(
                "DATA_IMPORT_CONFLICT",
                "同一秒的导入备份已存在，请稍后重试",
                409,
            )

        try:
            self.audit_repository.record(
                event_type="data.imported",
                source=context.source,
                result="accepted",
                actor_user_id=context.actor_user_id,
                actor_group_id=context.actor_group_id,
                client_ip=context.client_ip,
                target_type="database",
                target_id="main",
                metadata={
                    "schema_revision": preview.schema_revision,
                    "db_filename": preview.db_filename,
                },
            )
        except Exception as error:
            raise DataImportError(
                "DATA_IMPORT_FAILED", "写入导入审计失败，导入已取消", 500
            ) from error

        try:
            self.db_manager.close()
        except Exception as error:
            raise DataImportError(
                "DATA_IMPORT_FAILED", "关闭数据库连接失败，导入已取消", 500
            ) from error

        backups: Optional[Dict[Path, Path]] = None
        try:
            # 关闭连接后 WAL/SHM 可能已被 SQLite 自动清理，按最终状态生成备份
            backup_plan = self._plan_backup(db_path, timestamp)
            backups = self._copy_current_database(backup_plan)
            self._install_database(staged_db, db_path, original_stat, timestamp)
        except Exception as error:
            if backups is None:
                # 备份阶段失败时旧库尚未被改动，无需恢复
                raise DataImportError(
                    "DATA_IMPORT_FAILED",
                    f"导入失败，当前数据库未替换：{error}",
                    500,
                ) from error
            try:
                self._restore_database(backups, original_stat)
                self.db_manager.close()
            except Exception as restore_error:
                logger.error(f"数据导入失败且自动恢复旧数据库失败：{restore_error}")
                raise DataImportError(
                    "DATA_IMPORT_FAILED",
                    "导入失败且自动恢复旧数据库失败，请使用数据库目录下的 "
                    ".pre-import-*.bak 手动恢复",
                    500,
                ) from restore_error
            logger.error(f"数据导入失败，已自动恢复旧数据库：{error}")
            raise DataImportError(
                "DATA_IMPORT_FAILED",
                f"导入失败，已自动恢复旧数据库：{error}",
                500,
            ) from error

    @staticmethod
    def _plan_backup(db_path: Path, timestamp: str) -> List[Tuple[Path, Path]]:
        """列出需要备份的库文件及目标路径（含 WAL/SHM）。"""
        sources = [
            db_path,
            Path(f"{db_path}-wal"),
            Path(f"{db_path}-shm"),
        ]
        return [
            (source, Path(f"{source}.pre-import-{timestamp}.bak"))
            for source in sources
            if source.exists()
        ]

    @staticmethod
    def _copy_current_database(
        backup_plan: List[Tuple[Path, Path]],
    ) -> Dict[Path, Path]:
        """复制当前库及 WAL/SHM 到预导入备份文件。"""
        backups: Dict[Path, Path] = {}
        for source, target in backup_plan:
            shutil.copy2(source, target)
            backups[source] = target
        return backups

    def _install_database(
        self,
        staged_db: Path,
        db_path: Path,
        original_stat: os.stat_result,
        timestamp: str,
    ) -> None:
        """在同一目录准备新库并原子替换，删除不适用于新库的旧 WAL/SHM。"""
        temporary = db_path.with_name(f".{db_path.name}.import-{timestamp}.tmp")
        try:
            shutil.copyfile(staged_db, temporary)
            self._apply_permissions(temporary, original_stat)
            for suffix in ("-wal", "-shm"):
                Path(f"{db_path}{suffix}").unlink(missing_ok=True)
            os.replace(temporary, db_path)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    @staticmethod
    def _apply_permissions(target: Path, original_stat: os.stat_result) -> None:
        """让替换后的库文件保持原文件的属主与权限。"""
        if hasattr(os, "chown"):
            os.chown(target, original_stat.st_uid, original_stat.st_gid)
        os.chmod(target, S_IMODE(original_stat.st_mode))

    def _restore_database(
        self, backups: Dict[Path, Path], original_stat: os.stat_result
    ) -> None:
        """用预导入备份覆盖当前库，用于替换过程中的自动回滚。"""
        for source in backups:
            source.unlink(missing_ok=True)
        for source, target in backups.items():
            shutil.copy2(target, source)
            self._apply_permissions(source, original_stat)

    @staticmethod
    def _iso_utc(value: datetime) -> str:
        """把 UTC 时间序列化为带 Z 后缀的 ISO 8601 字符串。"""
        return value.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
