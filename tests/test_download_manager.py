# pylint: disable=protected-access
"""下载管理器单元测试"""

import os
from unittest import mock

import yaml
from PIL import Image

from src.download.manager import DownloadManager


def make_manager(tmp_path, low_memory_mode: bool = False) -> DownloadManager:
    """构造DownloadManager，使用临时目录，mock日志与发送器"""
    download_path = str(tmp_path / "downloads")
    os.makedirs(download_path, exist_ok=True)
    config = {
        "MANGA_DOWNLOAD_PATH": download_path,
        "LOW_MEMORY_MODE": low_memory_mode,
        "LOW_MEMORY_DELETE_DELAY": 0,
    }
    logger = mock.MagicMock()
    message_sender = mock.MagicMock()
    file_sender = mock.MagicMock()
    return DownloadManager(logger, config, message_sender, file_sender)


def make_chapter_folder(tmp_path, page_count: int = 3) -> str:
    """创建含指定数量JPEG图片的章节文件夹，返回其路径"""
    chapter_folder = tmp_path / "chapter1"
    chapter_folder.mkdir()
    for i in range(1, page_count + 1):
        image = Image.new("RGB", (50, 80), color=(i * 40, 100, 200))
        image.save(chapter_folder / f"{i:05d}.jpg")
    return str(chapter_folder)


def test_convert_chapter_to_pdf_produces_valid_pdf(tmp_path):
    """章节文件夹应被转换为有效的PDF文件并移动到下载目录"""
    manager = make_manager(tmp_path)
    chapter_folder = make_chapter_folder(tmp_path)
    download_path = str(tmp_path / "downloads")

    result = manager._convert_chapter_to_pdf(chapter_folder, download_path)

    assert result is not None
    assert result == os.path.join(download_path, "chapter1.pdf")
    assert os.path.exists(result)
    with open(result, "rb") as pdf_file:
        content = pdf_file.read()
    assert content.startswith(b"%PDF")
    assert len(content) > 0


def test_convert_chapter_to_pdf_with_png_images(tmp_path):
    """img2pdf应支持PNG图片转换，不因混合格式失败"""
    manager = make_manager(tmp_path)
    chapter_folder = tmp_path / "chapter_png"
    chapter_folder.mkdir()
    image = Image.new("RGB", (50, 80), color=(10, 20, 30))
    image.save(chapter_folder / "00001.png")
    download_path = str(tmp_path / "downloads")

    result = manager._convert_chapter_to_pdf(str(chapter_folder), download_path)

    assert result is not None
    assert os.path.exists(result)
    with open(result, "rb") as pdf_file:
        assert pdf_file.read().startswith(b"%PDF")


def test_convert_chapter_to_pdf_empty_folder_returns_none(tmp_path):
    """空章节文件夹应返回None并记录警告"""
    manager = make_manager(tmp_path)
    empty_folder = tmp_path / "empty"
    empty_folder.mkdir()

    result = manager._convert_chapter_to_pdf(
        str(empty_folder), str(tmp_path / "downloads")
    )

    assert result is None
    manager.logger.warning.assert_called()


def test_option_threading_config():
    """option.yml的threading配置应能被jmcomic正确解析"""
    option_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "option.yml"
    )
    if not os.path.exists(option_path):
        return
    with open(option_path, "r", encoding="utf-8") as config_file:
        option_data = yaml.safe_load(config_file)
    threading = option_data["download"]["threading"]
    assert threading["image"] == 8
    assert threading["photo"] == 2
