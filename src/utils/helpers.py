import os
import re
import shutil
from typing import List, Tuple

from src.logging.logger_config import logger


def parse_id_list(id_string: str) -> List[str]:
    """
    解析ID列表字符串，将逗号分隔的ID转换为列表

    Args:
        id_string: 逗号分隔的ID字符串

    Returns:
        清理后的ID列表
    """
    if not id_string or not id_string.strip():
        return []

    ids = [id.strip() for id in id_string.split(",") if id.strip()]
    return ids


def cleanup_failed_downloads(download_path: str) -> int:
    """
    清理下载目录中下载失败的文件和文件夹
    - 删除未转换为PDF的漫画文件夹
    - 删除临时文件

    Args:
        download_path: 下载目录路径

    Returns:
        清理的项目数量

    Raises:
        FileNotFoundError: 当下载目录不存在时
    """
    logger.info(f"开始清理下载目录: {download_path}")

    if not os.path.exists(download_path):
        logger.info("下载目录不存在，跳过清理")
        raise FileNotFoundError(f"下载目录不存在: {download_path}")

    cleaned_count = 0

    for item in os.listdir(download_path):
        item_path = os.path.join(download_path, item)

        if os.path.isdir(item_path):
            if re.match(r"^\d+", item):
                pdf_file = os.path.join(download_path, f"{item}.pdf")
                if not os.path.exists(pdf_file):
                    logger.info(f"清理下载失败的漫画文件夹: {item}")
                    shutil.rmtree(item_path)
                    cleaned_count += 1

        elif os.path.isfile(item_path):
            if item.endswith(".tmp") or item.endswith(".temp"):
                logger.info(f"清理临时文件: {item}")
                os.remove(item_path)
                cleaned_count += 1
            elif re.match(r"^\d+", item) and not item.endswith(".pdf"):
                logger.info(f"清理下载失败的文件: {item}")
                os.remove(item_path)
                cleaned_count += 1

    logger.info(f"下载目录清理完成，共清理 {cleaned_count} 个项目")
    return cleaned_count


def find_manga_pdf(download_path: str, manga_id: str) -> str | None:
    """
    在下载目录中查找指定漫画ID的PDF文件

    Args:
        download_path: 下载目录路径
        manga_id: 漫画ID

    Returns:
        PDF文件路径，如果未找到则返回None
    """
    if not os.path.exists(download_path):
        return None

    for file_name in os.listdir(download_path):
        if file_name.startswith(f"{manga_id}-") and file_name.endswith(".pdf"):
            return os.path.join(download_path, file_name)

    return None


def list_downloaded_mangas(download_path: str) -> List[str]:
    """
    列出已下载的漫画PDF文件

    Args:
        download_path: 下载目录路径

    Returns:
        漫画PDF文件名列表（不含扩展名）

    Raises:
        FileNotFoundError: 当下载目录不存在时
    """
    if not os.path.exists(download_path):
        raise FileNotFoundError(f"下载目录不存在: {download_path}")

    pdf_files = []
    for file_name in os.listdir(download_path):
        if file_name.endswith(".pdf"):
            name_without_ext = os.path.splitext(file_name)[0]
            pdf_files.append(name_without_ext)

    pdf_files.sort()
    return pdf_files


def get_file_size_mb(file_path: str) -> float:
    """
    获取文件大小（以MB为单位）

    Args:
        file_path: 文件路径

    Returns:
        文件大小（MB），保留两位小数

    Raises:
        FileNotFoundError: 当文件不存在时
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"文件不存在: {file_path}")

    file_size_bytes = os.path.getsize(file_path)
    file_size_mb = file_size_bytes / (1024 * 1024)
    return round(file_size_mb, 2)


def list_downloaded_mangas_with_size(download_path: str) -> List[Tuple[str, float]]:
    """
    列出已下载的漫画PDF文件及其大小

    Args:
        download_path: 下载目录路径

    Returns:
        漫画PDF文件名列表（不含扩展名）和文件大小（MB）的元组列表

    Raises:
        FileNotFoundError: 当下载目录不存在时
    """
    if not os.path.exists(download_path):
        raise FileNotFoundError(f"下载目录不存在: {download_path}")

    pdf_files = []
    try:
        file_names = os.listdir(download_path)
    except OSError:
        file_names = []

    for file_name in file_names:
        if file_name.endswith(".pdf"):
            name_without_ext = os.path.splitext(file_name)[0]
            file_path = os.path.join(download_path, file_name)
            file_size_mb = get_file_size_mb(file_path)
            pdf_files.append((name_without_ext, file_size_mb))

    pdf_files.sort(key=lambda x: x[0])
    return pdf_files
