"""页面图片服务测试：抽图、缩放、缓存失效、非图片型与越界。"""

from io import BytesIO
from pathlib import Path
import os

from PIL import Image
from pypdf import PdfReader, PdfWriter

import img2pdf
import pytest

from src.service import PageImageError
from src.service.page_image_service import PageImageService


def _write_image(path: Path, color: str, size: tuple[int, int]) -> Path:
    """生成指定颜色和尺寸的测试图片。"""
    image_format = "JPEG" if path.suffix.lower() in {".jpg", ".jpeg"} else "PNG"
    Image.new("RGB", size, color).save(path, format=image_format)
    return path


def _write_image_pdf(path: Path, colors: list[str]) -> Path:
    """把多张测试图片合并为每一页嵌入原图的 PDF。"""
    image_paths = [
        str(
            _write_image(
                path.with_name(f"{path.stem}-{index}{suffix}"),
                color,
                (400 + index * 10, 600 + index * 10),
            )
        )
        for index, (color, suffix) in enumerate(zip(colors, [".jpg", ".png"]))
    ]
    path.write_bytes(img2pdf.convert(image_paths))
    return path


def test_cover_is_scaled_to_480_width_jpeg(tmp_path: Path) -> None:
    """封面固定缩放到 480 宽并编码为 JPEG。"""
    pdf_path = _write_image_pdf(tmp_path / "manga.pdf", ["red", "blue"])
    service = PageImageService()

    data = service.extract_cover(pdf_path)

    assert data.startswith(b"\xff\xd8\xff")
    with Image.open(BytesIO(data)) as cover:
        assert cover.format == "JPEG"
        assert cover.width == 480
        assert cover.height == 720


def test_page_returns_original_embedded_bytes(tmp_path: Path) -> None:
    """页图直接返回嵌入原图字节，不做缩放或重新编码。"""
    pdf_path = _write_image_pdf(tmp_path / "manga.pdf", ["red", "blue"])
    original = PdfReader(str(pdf_path)).pages[1].images[0].data

    data = PageImageService().extract_page(pdf_path, 2)

    assert data == original
    assert PageImageService.media_type_for(data) == "image/png"


def test_page_cache_hit_and_invalidation_by_mtime(tmp_path: Path) -> None:
    """缓存命中不重复打开 PDF，文件修改时间变化后重新抽取。"""
    pdf_path = _write_image_pdf(tmp_path / "manga.pdf", ["red", "blue"])
    service = PageImageService()
    calls = 0
    original_open = service._open_pdf  # pylint: disable=protected-access

    def counting_open(path: Path):
        nonlocal calls
        calls += 1
        return original_open(path)

    service._open_pdf = counting_open  # type: ignore[method-assign]
    first = service.extract_page(pdf_path, 1)
    second = service.extract_page(pdf_path, 1)
    assert first == second
    assert calls == 1

    before = pdf_path.stat().st_mtime_ns
    changed = before + 1_000_000
    os.utime(pdf_path, ns=(changed, changed))
    service.extract_page(pdf_path, 1)
    assert calls == 2


def test_non_image_pdf_raises_and_probe_returns_false(tmp_path: Path) -> None:
    """矢量/空白 PDF 无嵌入图：探测为 False，抽取抛 PageImageError。"""
    pdf_path = tmp_path / "blank.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    with pdf_path.open("wb") as stream:
        writer.write(stream)
    service = PageImageService()

    assert service.is_image_pdf(pdf_path) is False
    with pytest.raises(PageImageError):
        service.extract_cover(pdf_path)
    with pytest.raises(PageImageError):
        service.extract_page(pdf_path, 1)


def test_probe_true_and_page_bounds(tmp_path: Path) -> None:
    """图片型探测为 True；0、负数与超过总页数均明确抛错。"""
    pdf_path = _write_image_pdf(tmp_path / "manga.pdf", ["red", "blue"])
    service = PageImageService()

    assert service.is_image_pdf(pdf_path) is True
    for page_number in (0, -1, 3):
        with pytest.raises(PageImageError, match="页码超出范围"):
            service.extract_page(pdf_path, page_number)


def test_corrupt_pdf_raises_page_image_error(tmp_path: Path) -> None:
    """损坏文件与不存在文件都转换为 PageImageError。"""
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"not a pdf")
    service = PageImageService()

    assert service.is_image_pdf(broken) is False
    with pytest.raises(PageImageError):
        service.extract_cover(broken)
    with pytest.raises(PageImageError):
        service.extract_page(tmp_path / "missing.pdf", 1)
