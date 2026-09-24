"""真实下载冒烟测试脚本

复用 DownloadManager 完整下载链路（整本下载 + img2pdf 插件合并 PDF），
真实下载指定漫画，校验 PDF 生成后清理全部下载产物（临时目录、PDF、测试用 option.yml）。

用法:
    uv run python tests/integration/download_test.py               # 下载默认测试漫画并清理
    uv run python tests/integration/download_test.py 12345 67890   # 下载指定漫画ID

注意:
    - 需要网络可访问禁漫站点
    - 脚本会在项目根临时创建 option.yml（若不存在），结束后删除/恢复
"""

import argparse
import os
import shutil
import sys
import time
from typing import Callable, List, Optional, Tuple

# 该文件是手动执行的冒烟测试脚本，不参与 pytest 收集
__test__ = False

# 需要先定位项目根并注入 sys.path 后才能导入 src 包（故 import 不在文件顶部）
# pylint: disable=wrong-import-position


# 定位项目根（从 __file__ 逐级向上，找到包含 src 包的最外层目录）
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
# 确保项目根可导入 src 包
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.download.manager import DownloadManager
from src.logging.logger_config import logger

OPTION_FILE = os.path.join(PROJECT_ROOT, "option.yml")
OPTION_FILE_BAK = os.path.join(PROJECT_ROOT, "option.yml.bak")
DOWNLOAD_DIR = os.path.join(PROJECT_ROOT, "downloads")
PROGRESS_LOG = os.path.join(PROJECT_ROOT, "logs", "jmcomic-download.log")

# 默认测试漫画ID
DEFAULT_MANGA_IDS = ["114514", "516751"]


def parse_args() -> argparse.Namespace:
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="真实下载漫画并验证PDF生成，结束后清理"
    )
    parser.add_argument(
        "manga_ids", nargs="*", help="要下载的漫画ID，默认 114514 516751"
    )
    return parser.parse_args()


def prepare_option_file() -> bool:
    """准备测试用 option.yml

    若已存在则备份；否则生成最小配置（不含 plugins，走代码注入路径）。
    返回 True 表示原文件不存在（测试后应删除），False 表示原文件存在（测试后应恢复）。
    """
    if os.path.exists(OPTION_FILE):
        shutil.copy2(OPTION_FILE, OPTION_FILE_BAK)
        return False

    content = "\n".join(
        [
            "download:",
            "  image:",
            "    suffix: .jpg  # 下载图片格式",
            "  threading:",
            "    image: 10  # 图片并发，调低以降低内存占用",
            "    photo: 1  # 章节并发",
            "  dir:",
            "    base: ./downloads  # 基础下载目录",
        ]
    )
    with open(OPTION_FILE, "w", encoding="utf-8") as f:
        f.write(content)
    return True


def restore_option_file(was_missing: bool) -> None:
    """测试后清理 option.yml：恢复被备份的，或删除测试生成的"""
    if os.path.exists(OPTION_FILE_BAK):
        shutil.move(OPTION_FILE_BAK, OPTION_FILE)
    elif was_missing:
        if os.path.exists(OPTION_FILE):
            os.remove(OPTION_FILE)


def make_message_sender(
    messages: List[Tuple[str, str]],
) -> Callable[[str, str, Optional[str], bool], None]:
    """构造消息发送函数，收集 bot 回复供测试校验"""

    def sender(
        user_id: str,
        message: str,
        group_id: Optional[str],  # pylint: disable=unused-argument
        private: bool,  # pylint: disable=unused-argument
    ) -> None:
        messages.append((user_id, message))
        preview = message.replace("\n", " ")
        print(f"[bot回复->{user_id}] {preview}")

    return sender


def wait_downloads_finished(
    download_manager: "DownloadManager",
    messages: List[Tuple[str, str]],
    expected_ids: List[str],
    timeout_seconds: int = 3600,
) -> bool:
    """轮询等待下载任务完成，或检测到失败回复

    Returns:
        True: 全部下载任务结束；False: 超时或检测到下载失败回复
    """
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        # 检测失败回复（bot 的下载失败消息以 ❌ 开头）
        if any(message.startswith("❌") for _, message in messages):
            return False

        # 队列为空且无正在下载的漫画，视为全部完成
        if (
            not download_manager.downloading_mangas
            and download_manager.download_queue.empty()
            and all(
                f"{mid}-" in " ".join(msg for _, msg in messages) or _pdf_exists(mid)
                for mid in expected_ids
            )
        ):
            return True

        time.sleep(2)

    return False


def _pdf_exists(manga_id: str) -> bool:
    """检查下载目录中是否存在指定漫画ID的 PDF"""
    if not os.path.isdir(DOWNLOAD_DIR):
        return False
    return any(
        name.endswith(".pdf")
        and (name.startswith(f"{manga_id}-") or name == f"{manga_id}.pdf")
        for name in os.listdir(DOWNLOAD_DIR)
    )


def verify_pdfs(expected_ids: List[str]) -> List[str]:
    """校验生成的 PDF，返回成功生成的漫画ID列表"""
    generated = []
    for manga_id in expected_ids:
        if _pdf_exists(manga_id):
            generated.append(manga_id)
        else:
            print(f"[校验失败] 未找到漫画 {manga_id} 的 PDF")
    return generated


def cleanup(download_manager: "DownloadManager", was_option_missing: bool) -> None:
    """清理下载产物：停止队列线程、删除下载目录、进度日志、option.yml"""
    download_manager.queue_running = False

    for target in (DOWNLOAD_DIR, PROGRESS_LOG):
        if os.path.isdir(target):
            shutil.rmtree(target, ignore_errors=True)
        elif os.path.isfile(target):
            os.remove(target)

    restore_option_file(was_option_missing)


def main() -> None:
    """下载测试主入口"""
    args = parse_args()
    manga_ids = args.manga_ids or DEFAULT_MANGA_IDS

    # 固定工作目录为项目根，保证 option.yml 相对路径正确
    os.chdir(PROJECT_ROOT)
    was_option_missing = prepare_option_file()

    messages: List[Tuple[str, str]] = []
    config = {
        "MANGA_DOWNLOAD_PATH": DOWNLOAD_DIR,
        "LOW_MEMORY_MODE": False,
        "LOW_MEMORY_DELETE_DELAY": 3,
    }

    download_manager = DownloadManager(
        logger_instance=logger,
        config=config,
        message_sender=make_message_sender(messages),
        file_sender=None,
        manga_repo=None,
        task_log_repo=None,
    )

    try:
        for manga_id in manga_ids:
            print(f"[提交任务] 漫画ID: {manga_id}")
            download_manager.download_manga("test", manga_id, None, False)

        print("[等待] 下载进行中，请耐心等待……")
        finished = wait_downloads_finished(download_manager, messages, manga_ids)

        if not finished:
            failed = [mid for mid in manga_ids if not _pdf_exists(mid)]
            print(
                f"[结果] 下载未全部成功，可用的PDF: {[mid for mid in manga_ids if _pdf_exists(mid)]}"
            )
            sys.exit(1 if failed else 0)

        generated = verify_pdfs(manga_ids)
        print(f"[结果] 成功生成 PDF: {generated} 个")

        if len(generated) == len(manga_ids):
            print("[通过] 全部漫画下载并合并 PDF 成功")
        else:
            print("[失败] 存在未生成 PDF 的漫画")
            sys.exit(1)
    finally:
        cleanup(download_manager, was_option_missing)
        print("[清理] 已删除下载目录与测试产物")


if __name__ == "__main__":
    main()
