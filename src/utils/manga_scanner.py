"""漫画扫描模块，负责扫描下载目录内的漫画PDF并将元数据同步到数据库

该模块供根目录的 scan_mangas.py 脚本使用，扫描已下载漫画的 PDF 文件，
解析文件名中的漫画ID与标题，并将元数据与文件记录写入 SQLite 数据库。
同时支持清理数据库中存在但文件已不存在的残留记录。
"""

import os
import re
from dataclasses import dataclass, field
from typing import List, Optional

from src.database.repositories import MangaRepository
from src.logging.logger_config import logger

# PDF 文件名正则：新格式为「漫画ID-标题(章节数章).pdf」，旧格式为「漫画ID.pdf」
_NEW_FORMAT_PATTERN = re.compile(r"^(\d+)-(.+?)\((\d+)章\)\.pdf$")
_OLD_FORMAT_PATTERN = re.compile(r"^(\d+)\.pdf$")


@dataclass
class MangaScanEntry:
    """扫描到的单个漫画条目"""

    manga_id: str
    title: str
    chapter_count: int = 0
    files: List[tuple[str, float]] = field(default_factory=list)

    def add_file(self, file_path: str, file_size_mb: float) -> None:
        """添加该漫画的一个PDF文件记录

        Args:
            file_path: PDF文件绝对路径
            file_size_mb: 文件大小(MB)
        """
        self.files.append((file_path, file_size_mb))

    @property
    def max_chapter_count(self) -> int:
        """所有文件章节数的最大值"""
        return self.chapter_count


@dataclass
class ScanResult:
    """扫描与同步结果统计"""

    scanned_files: int = 0
    manga_count: int = 0
    new_count: int = 0
    updated_count: int = 0
    pending_cleanup_count: int = 0
    deleted_count: int = 0


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

    manga_map: dict[str, MangaScanEntry] = {}
    scanned_files_count = 0

    for file_name in os.listdir(download_path):
        if not file_name.lower().endswith(".pdf"):
            continue

        file_path = os.path.join(download_path, file_name)
        if not os.path.isfile(file_path):
            continue

        scanned_files_count += 1
        entry = parse_pdf_filename(file_name)
        if entry is None:
            continue

        file_size_mb = round(os.path.getsize(file_path) / (1024 * 1024), 2)

        if entry.manga_id in manga_map:
            existing = manga_map[entry.manga_id]
            # 同ID聚合：章节数取所有文件中的最大值
            existing.chapter_count = max(existing.chapter_count, entry.chapter_count)
            if not existing.title and entry.title:
                existing.title = entry.title
        else:
            manga_map[entry.manga_id] = entry

        manga_map[entry.manga_id].add_file(file_path, file_size_mb)

    entries = list(manga_map.values())
    entries.sort(key=lambda e: int(e.manga_id))

    if scanned_files_count == 0:
        logger.info("扫描完成：下载目录内没有PDF文件")
    else:
        logger.info(
            f"扫描完成：共发现{scanned_files_count}个PDF文件，聚合为{len(entries)}个漫画"
        )

    return entries


def sync_scanned_to_db(
    repo: MangaRepository, entries: List[MangaScanEntry], dry_run: bool = False
) -> ScanResult:
    """
    将扫描到的漫画条目同步到数据库

    对数据库已有记录仅更新可解析的标题与章节数，保留更完整的元数据；
    对数据库中存在但文件已不存在的残留记录进行清理。

    Args:
        repo: 漫画元数据仓储
        entries: 扫描到的漫画条目列表
        dry_run: 是否仅预览不写入数据库

    Returns:
        ScanResult: 同步结果统计
    """
    result = ScanResult()
    result.manga_count = len(entries)
    result.scanned_files = _count_scan_files(entries)

    disk_ids: set[str] = set()

    for entry in entries:
        disk_ids.add(entry.manga_id)
        existing = repo.get(entry.manga_id) if not dry_run else None

        if existing is None and dry_run:
            result.new_count += 1
            continue

        if existing is not None:
            # 计算本次要写入的值，保留数据库已有且当前无法解析的元数据
            title = entry.title if entry.title else existing.title
            chapter_count = (
                entry.chapter_count if entry.chapter_count else existing.chapter_count
            )
            status = existing.status
            result.updated_count += 1
        else:
            title = entry.title
            chapter_count = entry.chapter_count
            status = "downloaded"
            result.new_count += 1

        if dry_run:
            continue

        repo.upsert(
            manga_id=entry.manga_id,
            title=title,
            author=existing.author if existing is not None else "",
            tags=existing.tags if existing is not None else "",
            chapter_count=chapter_count,
            page_count=existing.page_count if existing is not None else 0,
            status=status,
        )

        for file_path, file_size_mb in entry.files:
            repo.add_file(entry.manga_id, file_path, file_size_mb)

    # 清理数据库中文件已不存在的残留记录
    if not dry_run:
        db_ids = {manga.id for manga in repo.get_all()}
        orphan_ids = db_ids - disk_ids
        for manga_id in sorted(orphan_ids):
            logger.info(f"清理残留记录: 漫画ID {manga_id} 的PDF文件已不存在")
            repo.delete(manga_id)
        result.deleted_count = len(orphan_ids)
    else:
        result.pending_cleanup_count = _count_pending_cleanup(repo, disk_ids)

    return result


def _count_scan_files(entries: List[MangaScanEntry]) -> int:
    """统计全部漫画条目的PDF文件总数"""
    return sum(len(entry.files) for entry in entries)


def _count_pending_cleanup(repo: MangaRepository, disk_ids: set[str]) -> int:
    """统计数据库中存在但不在磁盘文件集合中的残留记录数量"""
    db_ids = {manga.id for manga in repo.get_all()}
    return len(db_ids - disk_ids)
