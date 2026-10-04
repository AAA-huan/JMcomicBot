"""漫画扫描模块，负责扫描下载目录内的漫画PDF并将元数据同步到数据库

该模块供 scripts/scan_mangas.py 脚本使用，扫描已下载漫画的 PDF 文件，
解析文件名中的漫画ID与标题，并将元数据与文件记录写入 SQLite 数据库。
同时支持清理数据库中存在但文件已不存在的残留记录。
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import os
import re

from src.database.models import ScanRecord
from src.database.repositories import MangaRepository, ScanRecordRepository
from src.logging.logger_config import logger

from .manga_enrichment import enrich_entries

# PDF 文件名正则：
# - 新格式「漫画ID-标题(章节数章).pdf」
# - 兼容格式「漫画ID-标题.pdf」（早期版本没有章节数后缀）
# - 旧格式「漫画ID.pdf」
# 扩展名大小写不敏感；标题原样保留。
_NEW_FORMAT_PATTERN = re.compile(r"^(\d+)-(.+?)\((\d+)章\)\.pdf$", re.IGNORECASE)
_ID_TITLE_FORMAT_PATTERN = re.compile(r"^(\d+)-(.+)\.pdf$", re.IGNORECASE)
_OLD_FORMAT_PATTERN = re.compile(r"^(\d+)\.pdf$", re.IGNORECASE)

# 扫描来源的路径标识：scan_record.path_label 只保存配置名称，绝不保存绝对路径
DOWNLOAD_PATH_LABEL = "MANGA_DOWNLOAD_PATH"


@dataclass
class MangaScanEntry:  # pylint: disable=too-many-instance-attributes
    """扫描到的单个漫画条目"""

    manga_id: str
    title: str
    chapter_count: int = 0
    author: str = ""
    tags: str = ""
    files: List[str] = field(default_factory=list)
    remote_metadata: Optional[Dict[str, Any]] = None
    enrich_error: Optional[str] = None
    chapter_errors: int = 0
    warnings: List[str] = field(default_factory=list)

    def add_file(self, file_path: str) -> None:
        """添加该漫画的一个PDF文件记录

        Args:
            file_path: PDF文件绝对路径
        """
        self.files.append(file_path)


@dataclass
class ScanResult:  # pylint: disable=too-many-instance-attributes
    """扫描与同步结果统计"""

    scanned_files: int = 0
    manga_count: int = 0
    new_count: int = 0
    updated_count: int = 0
    pending_cleanup_count: int = 0
    marked_missing_count: int = 0
    unchanged_count: int = 0
    skipped_count: int = 0
    duplicate_count: int = 0
    enrich_succeeded: int = 0
    enrich_failed: int = 0
    chapter_errors: int = 0
    page_read_failed: int = 0
    details: List[Dict[str, Any]] = field(default_factory=list)


def parse_pdf_filename(filename: str) -> Optional[MangaScanEntry]:
    """
    解析下载目录中的PDF文件名，提取漫画信息

    Args:
        filename: PDF文件名

    Returns:
        Optional[MangaScanEntry]: 解析成功返回条目，无法解析返回 None
    """
    base_name = os.path.basename(filename)

    new_match = _NEW_FORMAT_PATTERN.match(base_name)
    if new_match:
        manga_id, title, chapter_count = (
            new_match.group(1),
            new_match.group(2),
            int(new_match.group(3)),
        )
        return MangaScanEntry(
            manga_id=manga_id, title=title, chapter_count=chapter_count
        )

    id_title_match = _ID_TITLE_FORMAT_PATTERN.match(base_name)
    if id_title_match:
        # 早期命名没有「(N章)」后缀，章节数留 0 由数据库既有值或后续校验补全
        return MangaScanEntry(
            manga_id=id_title_match.group(1), title=id_title_match.group(2)
        )

    old_match = _OLD_FORMAT_PATTERN.match(base_name)
    if old_match:
        return MangaScanEntry(manga_id=old_match.group(1), title="")

    logger.warning(f"无法解析的PDF文件名，跳过: {filename}")
    return None


def scan_download_dir(download_path: str) -> List[MangaScanEntry]:
    """
    扫描下载目录内的漫画PDF文件并聚合为漫画条目列表

    仅扫描下载目录顶层的 *.pdf 文件（最终PDF都在顶层），
    同一漫画ID的多个PDF文件（旧版可能拆分章节）会聚合为一条记录。

    Args:
        download_path: 下载目录路径

    Returns:
        List[MangaScanEntry]: 扫描到的漫画条目列表

    Raises:
        FileNotFoundError: 当下载目录不存在时
    """
    if not os.path.isdir(download_path):
        raise FileNotFoundError(f"下载目录不存在: {download_path}")

    manga_map: Dict[str, MangaScanEntry] = {}
    scanned_files_count = 0

    for file_name in sorted(os.listdir(download_path)):
        if not file_name.lower().endswith(".pdf"):
            continue

        file_path = os.path.join(download_path, file_name)
        if not os.path.isfile(file_path):
            continue

        scanned_files_count += 1
        entry = parse_pdf_filename(file_name)
        if entry is None:
            continue

        if entry.manga_id in manga_map:
            existing = manga_map[entry.manga_id]
            # 同ID聚合：章节数取所有文件中的最大值
            existing.chapter_count = max(existing.chapter_count, entry.chapter_count)
            if not existing.title and entry.title:
                existing.title = entry.title
        else:
            manga_map[entry.manga_id] = entry

        manga_map[entry.manga_id].add_file(file_path)

    entries = list(manga_map.values())
    entries.sort(key=lambda e: int(e.manga_id))

    if scanned_files_count == 0:
        logger.info("扫描完成：下载目录内没有PDF文件")
    else:
        logger.info(
            f"扫描完成：共发现{scanned_files_count}个PDF文件，聚合为{len(entries)}个漫画"
        )

    return entries


def sync_scanned_to_db(  # pylint: disable=too-many-locals, too-many-branches
    repo: MangaRepository,
    entries: List[MangaScanEntry],
    dry_run: bool = False,
    tag_repo: Optional[Any] = None,
    read_pages: bool = False,
) -> ScanResult:
    """
    将扫描到的漫画条目同步到数据库

    保留本地已下载信息，联网补全保存独立快照；可选解析最终 PDF 实际页数。
    对数据库中存在但文件已不存在的残留记录标记为缺失，不直接删除。

    Args:
        repo: 漫画元数据仓储
        entries: 扫描到的漫画条目列表
        dry_run: 是否仅预览不写入数据库
        tag_repo: 漫画标签仓储，用于添加在线标签
        read_pages: 读取最终 PDF 的实际页数，不渲染图片

    Returns:
        ScanResult: 同步结果统计
    """
    result = ScanResult()
    result.manga_count = len(entries)
    result.scanned_files = _count_scan_files(entries)

    disk_ids: Set[str] = set()
    for entry in entries:
        disk_ids.add(entry.manga_id)
        existing = repo.get(entry.manga_id)
        result.enrich_succeeded += int(entry.remote_metadata is not None)
        result.enrich_failed += int(entry.enrich_error is not None)
        result.chapter_errors += entry.chapter_errors
        result.duplicate_count += int(len(entry.files) > 1)
        detail: Dict[str, Any] = {
            "manga_id": entry.manga_id,
            "file": None,
            "changes": [],
            "warnings": list(entry.warnings),
            "error": entry.enrich_error,
        }
        result.details.append(detail)
        selected = _select_scan_file(repo, entry, detail["warnings"])
        if selected is None:
            result.skipped_count += 1
            continue
        detail["file"] = Path(selected).name
        # 常规重扫不能用旧文件名覆盖已补全或手动修订的在线标题。
        if entry.remote_metadata is None and existing and existing.remote_metadata:
            title = existing.title
        else:
            title = entry.title if entry.title else (existing.title if existing else "")
        author = entry.author if entry.author else (existing.author if existing else "")
        # 历史文件名数字可能受旧页数 bug 污染，已有本地章节数不由文件名覆盖。
        # 在线章节数独立存储，不能把站点新增章节认作本地已下载章节。
        chapter_count = (
            existing.chapter_count
            if existing and existing.chapter_count
            else entry.chapter_count
        )
        page_count = existing.page_count if existing else 0
        actual_pages = None
        if read_pages:
            try:
                actual_pages = _read_pdf_pages(selected)
            except (OSError, ValueError) as error:
                result.page_read_failed += 1
                detail["error"] = f"PDF 页数读取失败: {error}"
                detail["warnings"].append("本漫画未写入，请修复文件后重扫")
                result.skipped_count += 1
                continue
            else:
                page_count = actual_pages
        fields = {
            "title": title,
            "author": author,
            "chapter_count": chapter_count,
            "page_count": page_count,
            "status": "downloaded",
        }
        old_fields = (
            {
                "title": existing.title,
                "author": existing.author,
                "chapter_count": existing.chapter_count,
                "page_count": existing.page_count,
                "status": existing.status,
            }
            if existing
            else {}
        )
        for key, value in fields.items():
            if old_fields.get(key) != value:
                source = (
                    "本地 PDF"
                    if key == "page_count" and actual_pages is not None
                    else (
                        "站点详情"
                        if key in ("title", "author") and entry.remote_metadata
                        else "本地文件/既有记录"
                    )
                )
                detail["changes"].append(
                    {
                        "field": key,
                        "old": old_fields.get(key),
                        "new": value,
                        "source": source,
                    }
                )
        if entry.remote_metadata is not None:
            previous = (
                existing.remote_metadata
                if existing and existing.remote_metadata
                else {}
            )
            for key, value in entry.remote_metadata.items():
                if key != "fetched_at" and previous.get(key) != value:
                    detail["changes"].append(
                        {
                            "field": f"remote.{key}",
                            "old": previous.get(key),
                            "new": value,
                            "source": "站点详情",
                        }
                    )
            remote_pages = entry.remote_metadata["page_count"]
            if remote_pages is not None and page_count and remote_pages != page_count:
                detail["warnings"].append(
                    f"站点页数 {remote_pages} 与本地页数 {page_count} 不同，未覆盖本地信息"
                )
            if entry.remote_metadata["chapter_count"] != chapter_count:
                detail["warnings"].append(
                    f"站点章节数 {entry.remote_metadata['chapter_count']} "
                    f"与本地记录 {chapter_count} 不同，本地章节数未覆盖"
                )
        file_changed = _file_changed(repo, entry.manga_id, selected, actual_pages)
        if existing is None:
            result.new_count += 1
        elif detail["changes"] or file_changed:
            result.updated_count += 1
        else:
            result.unchanged_count += 1
        if dry_run:
            continue
        if existing is None or detail["changes"] or file_changed:
            repo.upsert(manga_id=entry.manga_id, **fields)
        if entry.remote_metadata is not None:
            repo.update_scan_metadata(entry.manga_id, entry.remote_metadata)
        if file_changed:
            repo.add_file(entry.manga_id, selected, page_count=actual_pages)
        # 保留用户自建标签，仅添加在线标签，不静默删除既有标签。
        if tag_repo is not None and entry.tags:
            for tag in entry.tags.split(","):
                if tag.strip():
                    tag_repo.add_for_existing_manga(tag.strip(), entry.manga_id)

    # 清理数据库中文件已不存在的残留记录
    if not dry_run:
        db_ids = {manga.id for manga in repo.get_all()}
        orphan_ids = db_ids - disk_ids
        for manga_id in sorted(orphan_ids):
            logger.info(f"标记缺失文件: 漫画ID {manga_id} 的PDF文件已不存在")
            repo.mark_manga_missing(manga_id)
        result.marked_missing_count = len(orphan_ids)
    else:
        result.pending_cleanup_count = _count_pending_cleanup(repo, disk_ids)

    for detail in result.details:
        for change in detail["changes"]:
            change["label"] = _scan_field_label(change["field"])
    return result


def _count_scan_files(entries: List[MangaScanEntry]) -> int:
    """统计全部漫画条目的PDF文件总数"""
    return sum(len(entry.files) for entry in entries)


def record_scan_result(
    scan_record_repo: ScanRecordRepository, task_id: str, result: ScanResult
) -> ScanRecord:
    """将扫描结果统计写入 scan_record，path_label 只保存配置名称。"""
    return scan_record_repo.create(
        task_id=task_id,
        task_type="scan",
        path_label=DOWNLOAD_PATH_LABEL,
        file_count=result.scanned_files,
        new_count=result.new_count,
        updated_count=result.updated_count,
        missing_count=result.marked_missing_count,
        error_count=result.enrich_failed
        + result.chapter_errors
        + result.page_read_failed
        + result.skipped_count,
    )


def _count_pending_cleanup(repo: MangaRepository, disk_ids: Set[str]) -> int:
    """统计数据库中存在但不在磁盘文件集合中的残留记录数量"""
    db_ids = {manga.id for manga in repo.get_all()}
    return len(db_ids - disk_ids)


def enrich_metadata_from_jmcomic(
    entries: List[MangaScanEntry],
    option: Optional[Any] = None,
    only_missing: bool = True,
    check_chapters: bool = False,
) -> int:
    """通过详情接口补齐站点快照；不下载图片，不修改本地页数或章节数。"""
    return enrich_entries(entries, option, only_missing, check_chapters)


def _select_scan_file(
    repo: MangaRepository, entry: MangaScanEntry, warnings: List[str]
) -> Optional[str]:
    """重复文件优先保留已登记候选；无法确定最终 PDF 时明确跳过。"""
    if len(entry.files) == 1:
        return entry.files[0]
    files = repo.list_files(entry.manga_id)
    if repo.download_root is not None and files:
        registered = (repo.download_root / files[0].relative_path).resolve()
        for candidate in entry.files:
            if Path(candidate).resolve() == registered:
                warnings.append(
                    "发现重复 PDF，保留已登记文件；候选："
                    + "、".join(Path(path).name for path in entry.files)
                )
                return candidate
    warnings.append(
        "发现多个 PDF，无法确定最终文件，本漫画跳过；请整理后重扫："
        + "、".join(Path(path).name for path in entry.files)
    )
    return None


def _read_pdf_pages(path: str) -> int:
    """使用标准 PDF 解析器读取页树，不渲染图片；失败不写入页数。"""
    from pypdf import PdfReader  # pylint: disable=import-outside-toplevel
    from pypdf.errors import PyPdfError  # pylint: disable=import-outside-toplevel

    try:
        with open(path, "rb") as stream:
            reader = PdfReader(stream, strict=True)
            if reader.is_encrypted:
                raise ValueError("PDF 已加密，无法确定实际页数")
            count = len(reader.pages)
    except PyPdfError as error:
        raise ValueError(str(error)) from error
    if count <= 0:
        raise ValueError("PDF 没有页面")
    return count


def _file_changed(
    repo: MangaRepository, manga_id: str, path: str, pages: Optional[int]
) -> bool:
    """预览文件登记的变化，避免将未变化的漫画计为更新。"""
    files = repo.list_files(manga_id)
    if not files or repo.download_root is None:
        return True
    registered = files[0]
    return (
        (repo.download_root / registered.relative_path).resolve()
        != Path(path).resolve()
        or registered.file_size_bytes != Path(path).stat().st_size
        or registered.status != "ready"
        or (pages is not None and registered.page_count != pages)
    )


def _scan_field_label(name: str) -> str:
    """预览字段使用中文名称，区分在线来源与本地记录。"""
    labels = {
        "title": "标题",
        "author": "作者",
        "chapter_count": "本地章节数",
        "page_count": "本地实际页数",
        "status": "本地状态",
        "source": "来源",
        "authors": "全部作者",
        "tags": "标签",
        "description": "简介",
        "pub_date": "发布日期",
        "update_date": "更新日期",
        "works": "相关作品",
        "actors": "登场人物",
        "chapters": "章节列表",
        "chapter_page_count": "逐章图片总数",
    }
    if name.startswith("remote."):
        field_name = name.removeprefix("remote.")
        remote_labels = {"page_count": "总页数", "chapter_count": "章节数"}
        return "站点" + (
            remote_labels[field_name]
            if field_name in remote_labels
            else labels[field_name]
        )
    return labels[name]
