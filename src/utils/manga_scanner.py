"""漫画扫描模块，负责扫描下载目录内的漫画PDF并将元数据同步到数据库

该模块供根目录的 scan_mangas.py 脚本使用，扫描已下载漫画的 PDF 文件，
解析文件名中的漫画ID与标题，并将元数据与文件记录写入 SQLite 数据库。
同时支持清理数据库中存在但文件已不存在的残留记录。
"""

from dataclasses import dataclass, field
from typing import Any, List, Optional

import os
import re

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
    author: str = ""
    tags: str = ""
    files: List[str] = field(default_factory=list)

    def add_file(self, file_path: str) -> None:
        """添加该漫画的一个PDF文件记录

        Args:
            file_path: PDF文件绝对路径
        """
        self.files.append(file_path)


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
) -> ScanResult:
    """
    将扫描到的漫画条目同步到数据库

    对数据库已有记录仅更新可解析的标题与章节数，保留更完整的元数据；
    对数据库中存在但文件已不存在的残留记录标记为缺失，不直接删除。

    Args:
        repo: 漫画元数据仓储
        entries: 扫描到的漫画条目列表
        dry_run: 是否仅预览不写入数据库
        tag_repo: 漫画标签仓储，存在时用于清理孤儿标签记录

    Returns:
        ScanResult: 同步结果统计
    """
    result = ScanResult()
    result.manga_count = len(entries)
    result.scanned_files = _count_scan_files(entries)

    disk_ids: set[str] = set()

    for entry in entries:
        disk_ids.add(entry.manga_id)
        # dry-run 同样查询数据库，以准确区分新增与更新，但不会执行任何写入。
        existing = repo.get(entry.manga_id)

        if existing is not None:
            # 计算本次要写入的值，保留数据库已有且当前无法可靠解析的元数据。
            # 注意：文件名中的数字可能是章节数也可能是页数（历史版本 bug 污染），
            # 因此 DB 已有非零 chapter_count 时以 DB 为准，不覆盖。
            title = entry.title if entry.title else existing.title
            chapter_count = (
                existing.chapter_count
                if existing.chapter_count
                else entry.chapter_count
            )
            status = "downloaded"
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
            author=entry.author or (existing.author if existing is not None else ""),
            chapter_count=chapter_count,
            # 扫描无法从文件名获取真实页数，page_count 无法可靠得到，新记录保持 0
            page_count=existing.page_count if existing is not None else 0,
            status=status,
        )

        # 目标 schema 一漫画只保留一个最终 PDF；多文件旧数据取最后扫描到的候选。
        for file_path in entry.files[-1:]:
            repo.add_file(entry.manga_id, file_path)

        # 若本次扫描联网补全了标签，同步写入标签表
        if not dry_run and tag_repo is not None and entry.tags:
            for file_path in entry.files[-1:]:
                for tag in entry.tags.split(","):
                    tag = tag.strip()
                    if tag:
                        tag_repo.add_for_existing_manga(tag, entry.manga_id)

    # 清理数据库中文件已不存在的残留记录
    if not dry_run:
        db_ids = {manga.id for manga in repo.get_all()}
        orphan_ids = db_ids - disk_ids
        for manga_id in sorted(orphan_ids):
            logger.info(f"标记缺失文件: 漫画ID {manga_id} 的PDF文件已不存在")
            repo.mark_manga_missing(manga_id)
        result.deleted_count = 0
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


def enrich_metadata_from_jmcomic(
    entries: List[MangaScanEntry],
    option: Optional[Any] = None,
    only_missing: bool = True,
) -> int:
    """联网补全扫描条目的作者与标签元数据

    通过 jmcomic API 获取每个漫画的作者与标签，写入对应的 MangaScanEntry。
    联网失败或目标不存在时跳过，不影响扫描结果。

    Args:
        entries: 扫描到的漫画条目列表（就地修改）
        option: jmcomic 配置，缺省使用默认配置创建客户端
        only_missing: 仅处理作者或标签存在空值的条目，成功后同时刷新两项，默认 True

    Returns:
        int: 成功补全的条目数量
    """
    # 延迟导入 jmcomic，避免基础扫描流程（无需联网）加载重量级依赖
    import jmcomic  # pylint: disable=import-outside-toplevel

    if option is None:
        option = jmcomic.JmOption.default()
    client = option.new_jm_client()

    enriched_count = 0
    for entry in entries:
        if only_missing and entry.author and entry.tags:
            continue

        try:
            album = client.get_album_detail(entry.manga_id)
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning(f"联网获取漫画 {entry.manga_id} 元数据失败，跳过: {e}")
            continue

        if not entry.title:
            entry.title = album.name
        entry.author = ",".join(getattr(album, "authors", []))
        entry.tags = ",".join(getattr(album, "tags", []))
        enriched_count += 1

    return enriched_count
