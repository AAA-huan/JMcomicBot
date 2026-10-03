"""开发与冒烟测试数据准备脚本

向配置的数据库、下载目录与备份目录写入测试数据，便于迁移冒烟与 WebUI 页面验证：

- 生成多本漫画的最小合法 PDF（标题/作者/章节数/页数多样）；
- 走真实扫描流程入库（scan 任务、scan_record、审计）；
- 写入准确的页数与作者元数据，并为部分漫画写入标签；
- 删除 2 本生成的 PDF 后执行真实校验（产生 missing 状态与 verify 任务）；
- 写入成功/失败/取消/排队四种状态的下载任务；
- 写入阅读进度（不同更新时间）；
- 创建一致性备份并生成一条 deleted 状态演示记录。

仅用于开发与冒烟测试：脚本只新增数据，不删除既有漫画/任务/备份记录；
为制造缺失状态而删除的文件仅限本脚本本次生成的 PDF。
注意：扫描按真实逻辑执行，数据库中存在但磁盘缺失的既有漫画会被标记 missing。

用法:
    uv run python tests/smoke/prepare_test_data.py
    uv run python tests/smoke/prepare_test_data.py --mangas 20 --start-id 910001
    uv run python tests/smoke/prepare_test_data.py --download-path /tmp/dl --db-path /tmp/db --no-backups
"""

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import List

import argparse
import os
import random
import sys
import time

# 该文件是手动执行的冒烟数据准备脚本，不参与 pytest 收集
__test__ = False

# 需要先定位项目根并注入 sys.path 后才能导入 src 包（故 import 不在文件顶部）
# pylint: disable=wrong-import-position


def _find_project_root(start_dir: str) -> str:
    """从起始目录向上查找包含 src 包的项目根目录"""
    current = start_dir
    while True:
        if os.path.isdir(os.path.join(current, "src")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            raise RuntimeError(f"未找到项目根目录（缺少 src 包）: {start_dir}")
        current = parent


PROJECT_ROOT = _find_project_root(os.path.dirname(os.path.abspath(__file__)))
# 确保项目根可导入 src 包与 scan_mangas
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.config.manager import ConfigManager
from src.database.database import DatabaseManager
from src.database.migrations import get_schema_revision
from src.database.models import utc_now
from src.database.repositories import (
    AuditEventRepository,
    BackupRepository,
    MangaRepository,
    MangaTagRepository,
    OperationTaskRepository,
    ReadingProgressRepository,
    ScanRecordRepository,
    TaskEventRepository,
)
from src.logging.logger_config import logger
from src.service import (
    DatabaseMaintenanceService,
    OperationContext,
    OperationTaskService,
    VerifyResult,
    VerifyService,
)
from src.utils.manga_scanner import (
    record_scan_result,
    scan_download_dir,
    sync_scanned_to_db,
)

_TITLES = [
    "夜行测试录",
    "纯爱小剧场",
    "冒险者的日常",
    "城市观察笔记",
    "深海回声",
    "星尘与猫",
    "四季食谱",
    "机械之心",
    "花开时节",
    "孤岛来信",
    "雨夜推理",
    "旅行者日记",
]
_AUTHORS = ["测试作者甲", "测试作者乙", "测试作者丙"]
_TAGS = ["萌系", "纯爱", "汉化", "短篇", "连载"]


@dataclass(frozen=True)
class GeneratedManga:
    """本次生成的测试漫画元数据。"""

    manga_id: str
    title: str
    author: str
    chapter_count: int
    page_count: int
    path: Path


def parse_args() -> argparse.Namespace:
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="生成开发/冒烟测试数据（仅新增，不删除既有记录）"
    )
    parser.add_argument(
        "--mangas", type=int, default=12, help="生成的漫画数量，默认 12"
    )
    parser.add_argument(
        "--start-id", type=int, default=900001, help="漫画ID起始值，默认 900001"
    )
    parser.add_argument("--seed", type=int, default=20261001, help="随机种子")
    parser.add_argument(
        "--download-path", default=None, help="下载目录，缺省使用 MANGA_DOWNLOAD_PATH"
    )
    parser.add_argument("--db-path", default=None, help="数据库目录，缺省使用 DB_PATH")
    parser.add_argument(
        "--backup-path", default=None, help="备份目录，缺省使用 BACKUP_PATH"
    )
    parser.add_argument("--no-backups", action="store_true", help="跳过备份数据创建")
    args = parser.parse_args()
    if not 4 <= args.mangas <= 200:
        parser.error("--mangas 必须在 4 到 200 之间（需要覆盖多状态任务）")
    if args.start_id <= 0:
        parser.error("--start-id 必须大于 0")
    return args


def _build_pdf(page_count: int, page_padding_bytes: int = 0) -> bytes:
    """生成指定页数的合法 PDF，可用注释填充流测试大文件 Range 读取。"""
    font_object = 3 + page_count * 2
    objects: List[bytes] = []
    kids = " ".join(f"{3 + index * 2} 0 R" for index in range(page_count))
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {page_count} >>".encode())
    for index in range(page_count):
        content_object = 4 + index * 2
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
                f"/Contents {content_object} 0 R "
                f"/Resources << /Font << /F1 {font_object} 0 R >> >> >>"
            ).encode()
        )
        stream = (
            f"BT /F1 24 Tf 72 770 Td (JMcomicBot test page {index + 1}) Tj ET"
        ).encode()
        if page_padding_bytes:
            stream += b"\n%" + b" " * page_padding_bytes + b"\n"
        objects.append(
            b"<< /Length "
            + str(len(stream)).encode()
            + b" >>\nstream\n"
            + stream
            + b"\nendstream"
        )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    output = bytearray(b"%PDF-1.4\n")
    offsets: List[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_offset = len(output)
    output += f"xref\n0 {len(objects) + 1}\n".encode()
    output += b"0000000000 65535 f \n"
    for offset in offsets:
        output += f"{offset:010d} 00000 n \n".encode()
    output += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n"
    ).encode()
    return bytes(output)


def _ensure_ids_available(repo: MangaRepository, start_id: int, count: int) -> None:
    """检查测试ID区间未被占用，避免覆盖既有漫画记录。"""
    for offset in range(count):
        manga_id = str(start_id + offset)
        if repo.get(manga_id) is not None:
            raise SystemExit(
                f"测试漫画ID已存在，请使用 --start-id 指定未占用的区间: {manga_id}"
            )


def _write_test_pdfs(
    download_path: Path, start_id: int, count: int, rng: random.Random
) -> List[GeneratedManga]:
    """生成测试 PDF 文件并返回元数据列表。"""
    generated: List[GeneratedManga] = []
    for offset in range(count):
        manga_id = str(start_id + offset)
        chapter_count = rng.randint(1, 20)
        page_count = rng.randint(1, 30)
        item = GeneratedManga(
            manga_id=manga_id,
            title=_TITLES[offset % len(_TITLES)],
            author=_AUTHORS[offset % len(_AUTHORS)],
            chapter_count=chapter_count,
            page_count=page_count,
            path=download_path
            / f"{manga_id}-{_TITLES[offset % len(_TITLES)]}({chapter_count}章).pdf",
        )
        item.path.write_bytes(_build_pdf(page_count))
        generated.append(item)
    return generated


def _run_scan(
    download_path: Path,
    repo: MangaRepository,
    tag_repo: MangaTagRepository,
    scan_record_repo: ScanRecordRepository,
    task_service: OperationTaskService,
    context: OperationContext,
) -> None:
    """按 scripts/scan_mangas.py 的真实流程执行一次扫描入库。"""
    task = task_service.create("scan", context)
    task_service.start(task.id, "scanning")
    try:
        entries = scan_download_dir(str(download_path))
        result = sync_scanned_to_db(repo, entries, tag_repo=tag_repo)
        record_scan_result(scan_record_repo, task.id, result)
        task_service.succeed(
            task.id,
            metadata={
                "file_count": result.scanned_files,
                "new_count": result.new_count,
                "updated_count": result.updated_count,
                "missing_count": result.marked_missing_count,
            },
            context=context,
        )
    except Exception as error:
        task_service.fail(task.id, "scan_failed", type(error).__name__, context=context)
        raise


def _enrich_metadata(repo: MangaRepository, generated: List[GeneratedManga]) -> None:
    """写入准确的作者、章节数与页数（扫描无法从文件名得到真实页数）。"""
    for item in generated:
        repo.upsert(
            manga_id=item.manga_id,
            title=item.title,
            author=item.author,
            chapter_count=item.chapter_count,
            page_count=item.page_count,
        )
        repo.add_file(item.manga_id, str(item.path), page_count=item.page_count)


def _add_tags(
    tag_repo: MangaTagRepository, generated: List[GeneratedManga], rng: random.Random
) -> None:
    """为前几本漫画写入标签，覆盖标签查询与筛选场景。"""
    for item in generated[: min(5, len(generated))]:
        for tag in rng.sample(_TAGS, 2):
            tag_repo.add_for_existing_manga(tag, item.manga_id)


def _delete_and_verify(
    download_path: Path,
    repo: MangaRepository,
    scan_record_repo: ScanRecordRepository,
    task_service: OperationTaskService,
    generated: List[GeneratedManga],
    context: OperationContext,
) -> tuple[VerifyResult, List[GeneratedManga]]:
    """删除 2 本生成 PDF 制造缺失状态，并执行真实校验任务。"""
    deleted = generated[-2:]
    for item in deleted:
        item.path.unlink()
        logger.info(f"已删除测试PDF制造缺失状态: {item.path.name}")

    verify_service = VerifyService(
        repo,
        scan_record_repo,
        task_service,
        download_root=str(download_path),
    )
    result = verify_service.verify(
        [item.manga_id for item in generated], context=context
    )
    return result, deleted


def _create_history_tasks(
    task_service: OperationTaskService,
    generated: List[GeneratedManga],
    context: OperationContext,
) -> None:
    """写入成功/失败/取消/排队四种状态的下载任务。"""
    succeeded = task_service.create("download", context, manga_id=generated[0].manga_id)
    task_service.start(succeeded.id, "downloading")
    task_service.succeed(succeeded.id, metadata={"file_count": 1}, context=context)

    failed = task_service.create("download", context, manga_id=generated[1].manga_id)
    task_service.start(failed.id, "downloading")
    task_service.fail(
        failed.id, "download_failed", "测试失败数据（冒烟专用）", context=context
    )

    cancelled = task_service.create("download", context, manga_id=generated[2].manga_id)
    task_service.cancel(cancelled.id)

    # 保留一个排队中的下载任务，用于任务列表状态展示
    task_service.create("download", context, manga_id=generated[3].manga_id)


def _write_reading_progress(
    progress_repo: ReadingProgressRepository,
    repo: MangaRepository,
    generated: List[GeneratedManga],
) -> int:
    """为前 3 本漫画写入阅读进度，更新时间错开以覆盖排序。"""
    now = utc_now()
    written = 0
    for index, item in enumerate(generated[:3]):
        manga = repo.get(item.manga_id)
        if manga is None or not manga.files:
            continue
        page_number = max(1, item.page_count // (index + 2))
        progress_repo.upsert(
            manga_file_id=manga.files[0].id,
            page_number=page_number,
            page_count=item.page_count,
            percent=page_number / item.page_count,
            updated_at=now - timedelta(hours=index + 1),
        )
        written += 1
    return written


def _wait_for_next_filename_second(backup_repo: BackupRepository) -> None:
    """等待越过最近一次备份的秒级时间戳，避免同秒文件名冲突。"""
    latest = backup_repo.list(page_size=1)[0]
    while (utc_now() - latest.created_at) < timedelta(seconds=1):
        time.sleep(0.1)


def _create_backups(
    db_manager: DatabaseManager,
    task_service: OperationTaskService,
    backup_repo: BackupRepository,
    backup_path: Path,
    context: OperationContext,
    start_id: int,
) -> int:
    """创建 2 份真实备份并生成一条 deleted 状态演示记录。"""
    maintenance = DatabaseMaintenanceService(
        db_manager, task_service, backup_repo, backup_dir=str(backup_path)
    )
    maintenance.create_backup(context=context)
    # 文件名精确到秒，等待跨秒后再创建第二份，避免相对路径唯一约束冲突
    _wait_for_next_filename_second(backup_repo)
    maintenance.create_backup(context=context)

    demo_name = f"main-demo-deleted-{start_id}-{int(time.time())}.db"
    schema_version = get_schema_revision(db_manager.engine)
    demo = backup_repo.create(
        filename=demo_name,
        relative_path=demo_name,
        schema_version=schema_version,
        status="ready",
    )
    backup_repo.mark_deleted(demo.id)
    return 3


def _print_summary(
    download_path: Path,
    db_path: Path,
    generated: List[GeneratedManga],
    deleted: List[GeneratedManga],
    verify_result: VerifyResult,
    reading_count: int,
    backup_count: int,
) -> None:
    """输出本次准备的数据摘要。"""
    lines = [
        "测试数据准备完成：",
        f"  下载目录: {download_path}",
        f"  数据库目录: {db_path}",
        f"  新增漫画: {len(generated)} 本"
        f"（ID {generated[0].manga_id} ~ {generated[-1].manga_id}）",
        f"  缺失状态: {len(deleted)} 本"
        f"（{', '.join(item.manga_id for item in deleted)}）",
        f"  校验结果: 正常 {verify_result.ready_count}、"
        f"缺失 {verify_result.missing_count}、"
        f"损坏 {verify_result.corrupted_count}、"
        f"路径异常 {verify_result.invalid_path_count}、"
        f"错误 {verify_result.error_count}",
        "  下载任务: 成功/失败/取消/排队 各 1 个",
        f"  阅读进度: {reading_count} 条，备份记录: {backup_count} 条",
        "提示：扫描按真实逻辑执行，数据库中存在但磁盘缺失的既有漫画会被标记 missing。",
    ]
    for line in lines:
        logger.info(line)


def main() -> None:
    """测试数据准备主入口"""
    args = parse_args()
    rng = random.Random(args.seed)
    config = ConfigManager()
    config.load_config()
    download_path = Path(
        args.download_path or str(config.get("MANGA_DOWNLOAD_PATH"))
    ).resolve()
    db_path = Path(args.db_path or str(config.get("DB_PATH"))).resolve()
    backup_path = Path(args.backup_path or str(config.get("BACKUP_PATH"))).resolve()

    download_path.mkdir(parents=True, exist_ok=True)
    db_manager = DatabaseManager(db_path=str(db_path))
    db_manager.init_db()
    try:
        repo = MangaRepository(db_manager, download_root=str(download_path))
        tag_repo = MangaTagRepository(db_manager)
        scan_record_repo = ScanRecordRepository(db_manager)
        progress_repo = ReadingProgressRepository(db_manager)
        backup_repo = BackupRepository(db_manager)
        task_service = OperationTaskService(
            OperationTaskRepository(db_manager),
            TaskEventRepository(db_manager),
            AuditEventRepository(db_manager),
        )
        context = OperationContext.system()

        _ensure_ids_available(repo, args.start_id, args.mangas)
        generated = _write_test_pdfs(download_path, args.start_id, args.mangas, rng)
        _run_scan(
            download_path, repo, tag_repo, scan_record_repo, task_service, context
        )
        _enrich_metadata(repo, generated)
        _add_tags(tag_repo, generated, rng)
        verify_result, deleted = _delete_and_verify(
            download_path, repo, scan_record_repo, task_service, generated, context
        )
        _create_history_tasks(task_service, generated, context)
        reading_count = _write_reading_progress(progress_repo, repo, generated)
        backup_count = 0
        if not args.no_backups:
            backup_count = _create_backups(
                db_manager,
                task_service,
                backup_repo,
                backup_path,
                context,
                args.start_id,
            )
        _print_summary(
            download_path,
            db_path,
            generated,
            deleted,
            verify_result,
            reading_count,
            backup_count,
        )
    finally:
        db_manager.close()


if __name__ == "__main__":
    main()
