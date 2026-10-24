"""从图片型 PDF 抽取嵌入图，内存 LRU 缓存且不落盘。

jmcomic 通过 img2pdf 生成的 PDF 每页直接嵌入一张原始图片，因此无需
PDF.js 或服务端重新光栅化：封面读取首页并缩放为 JPEG，阅读器按页返回
原始图片字节，由浏览器自行解码与缩放。缓存 key 含文件修改时间，文件被
替换后自动失效。

PdfReader 会解析并持有整本 PDF 的 xref 表与页面对象，重复打开大文件
耗时明显，因此额外缓存最近使用的 reader 对象；pypdf 的 reader 不是线程
安全的，所有实际读取操作都通过一把可重入锁串行执行。
"""

from collections import OrderedDict
from collections.abc import Hashable
from io import BytesIO
from pathlib import Path
from threading import Lock, RLock
from typing import Generic, Optional, TypeVar

from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader
from pypdf.errors import PyPdfError

_COVER_CACHE_SIZE = 256
_PAGE_CACHE_SIZE = 128
_PROBE_CACHE_SIZE = 512
# PdfReader 持有 xref 表与页字典，内存占用较大；单用户阅读场景下 4 项
# 足以覆盖当前漫画与少量切换，可按设备内存调整，不暴露为用户配置。
_READER_CACHE_SIZE = 4
_COVER_WIDTH = 480
_COVER_JPEG_QUALITY = 80

_CacheKey = tuple[Hashable, ...]
_ValueT = TypeVar("_ValueT")


class PageImageError(Exception):
    """页面图片不可用；接口层统一映射为 404，不泄露内部路径。"""


class _MemoryLRU(Generic[_ValueT]):
    """线程安全的有界内存 LRU，命中时移动到队尾，超限淘汰最旧项。"""

    def __init__(self, max_entries: int) -> None:
        self.max_entries = max_entries
        self._items: OrderedDict[_CacheKey, _ValueT] = OrderedDict()
        self._lock = Lock()

    def get(self, key: _CacheKey) -> Optional[_ValueT]:
        """读取缓存并刷新最近使用顺序；不存在返回 None。"""
        with self._lock:
            value = self._items.get(key)
            if value is None:
                return None
            self._items.move_to_end(key)
            return value

    def put(self, key: _CacheKey, value: _ValueT) -> None:
        """写入缓存；超过容量时淘汰最久未使用的项。"""
        with self._lock:
            self._items[key] = value
            self._items.move_to_end(key)
            while len(self._items) > self.max_entries:
                self._items.popitem(last=False)


class PageImageService:
    """从图片型 PDF 抽取嵌入图并缩放，内存 LRU 缓存，不落盘。"""

    def __init__(self) -> None:
        self._cover_cache: _MemoryLRU[bytes] = _MemoryLRU(_COVER_CACHE_SIZE)
        self._page_cache: _MemoryLRU[bytes] = _MemoryLRU(_PAGE_CACHE_SIZE)
        self._probe_cache: _MemoryLRU[bool] = _MemoryLRU(_PROBE_CACHE_SIZE)
        self._reader_cache: _MemoryLRU[PdfReader] = _MemoryLRU(_READER_CACHE_SIZE)
        # pypdf 的 PdfReader 不是线程安全的：打开、抽图与读尺寸都用同一把
        # 可重入锁串行执行，避免并发请求同时访问同一个 reader 对象。
        self._reader_lock = RLock()

    def extract_cover(self, path: Path) -> bytes:
        """首页图 → Pillow 缩放为 480 宽 JPEG(q80) 字节。

        Raises:
            PageImageError: 文件损坏、加密或首页没有可提取的嵌入图。
        """
        cache_key = self._file_key(path)
        cached = self._cover_cache.get(cache_key)
        if cached is not None:
            return cached

        with self._reader_lock:
            reader = self._get_reader(path)
            image_data = self._first_page_image_data(reader, 1)
        try:
            with Image.open(BytesIO(image_data)) as source:
                source.load()
                rgb = source.convert("RGB")
                width, height = rgb.size
                if width <= 0 or height <= 0:
                    raise PageImageError("PDF 首页图片尺寸无效")
                target_height = max(1, round(height * _COVER_WIDTH / width))
                cover = rgb.resize(
                    (_COVER_WIDTH, target_height), Image.Resampling.LANCZOS
                )
                output = BytesIO()
                cover.save(output, format="JPEG", quality=_COVER_JPEG_QUALITY)
        except (UnidentifiedImageError, OSError, ValueError) as error:
            raise PageImageError("PDF 首页图片无法解码") from error

        data = output.getvalue()
        self._cover_cache.put(cache_key, data)
        return data

    def extract_page(self, path: Path, page_number: int) -> bytes:
        """返回第 page_number（1 基）页嵌入图原图字节，不做缩放。

        Raises:
            PageImageError: 页码越界、文件损坏/加密或页面没有嵌入图。
        """
        cache_key = self._file_key(path) + (page_number,)
        cached = self._page_cache.get(cache_key)
        if cached is not None:
            return cached

        with self._reader_lock:
            reader = self._get_reader(path)
            page_count = len(reader.pages)
            if page_number < 1 or page_number > page_count:
                raise PageImageError(
                    f"页码超出范围：{page_number}，有效范围 1-{page_count}"
                )
            data = self._first_page_image_data(reader, page_number)
        self._page_cache.put(cache_key, data)
        return data

    def page_size(self, path: Path, page_number: int) -> tuple[int, int]:
        """读取指定页首张嵌入图的原始像素尺寸，不抽取图片字节。

        直接读取图片 XObject 的 /Width 与 /Height 整数元数据，不 decode
        像素，供前端在打开阅读器时轻量获取占位尺寸。

        Raises:
            PageImageError: 页码越界、资源字典缺失、页面没有图片 XObject、
                图片尺寸无效，以及文件损坏或加密。
        """
        with self._reader_lock:
            reader = self._get_reader(path)
            try:
                page_count = len(reader.pages)
                if page_number < 1 or page_number > page_count:
                    raise PageImageError(
                        f"页码超出范围：{page_number}，有效范围 1-{page_count}"
                    )
                page = reader.pages[page_number - 1]
                resources = page.get("/Resources")
                if resources is None:
                    raise PageImageError("PDF 页面缺少资源字典")
                xobjects = resources.get_object().get("/XObject")
                if xobjects is None:
                    raise PageImageError("PDF 页面没有图片资源")
                xobject_dict = xobjects.get_object()
                if not xobject_dict:
                    raise PageImageError("PDF 页面没有图片资源")
                for xobject in xobject_dict.values():
                    image_object = xobject.get_object()
                    if image_object.get("/Subtype") != "/Image":
                        continue
                    width = int(image_object["/Width"])
                    height = int(image_object["/Height"])
                    if width <= 0 or height <= 0:
                        raise PageImageError("PDF 页面图片尺寸无效")
                    return width, height
            except (PyPdfError, OSError, ValueError, KeyError, TypeError) as error:
                raise PageImageError("PDF 页面图片尺寸读取失败") from error
        raise PageImageError("PDF 页面没有可用的图片资源")

    def is_image_pdf(self, path: Path) -> bool:
        """探测首页是否有嵌入图；探测结果按文件修改时间缓存。

        仅服务内部与端点判断使用，不暴露 HTTP 接口。损坏或加密的 PDF
        视为非图片型，由 extract_cover/extract_page 负责抛出具体错误。
        """
        cache_key = self._file_key(path)
        cached = self._probe_cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            with self._reader_lock:
                reader = self._get_reader(path)
                self._first_page_image_data(reader, 1)
            result = True
        except PageImageError:
            result = False
        self._probe_cache.put(cache_key, result)
        return result

    @staticmethod
    def media_type_for(data: bytes) -> str:
        """按原始图片字节魔数返回浏览器可用的 MIME 类型。"""
        if data.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if data.startswith((b"GIF87a", b"GIF89a")):
            return "image/gif"
        if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
            return "image/webp"
        if data.startswith((b"II*\x00", b"MM\x00*")):
            return "image/tiff"
        return "application/octet-stream"

    def _file_key(self, path: Path) -> _CacheKey:
        """构造包含文件修改时间的缓存 key；文件缺失明确报错。"""
        try:
            stat = path.stat()
        except OSError as error:
            raise PageImageError("PDF 文件不存在或无法读取") from error
        return (str(path.resolve()), stat.st_mtime_ns)

    def _get_reader(self, path: Path) -> PdfReader:
        """按文件修改时间复用 PdfReader；调用方必须持有 _reader_lock。

        缓存命中时直接返回已解析的 reader，避免重复解析大文件的 xref 表；
        文件修改时间变化后 key 失效，自动重新打开。
        """
        cache_key = self._file_key(path)
        cached = self._reader_cache.get(cache_key)
        if cached is not None:
            return cached
        reader = self._open_pdf(path)
        self._reader_cache.put(cache_key, reader)
        return reader

    @staticmethod
    def _open_pdf(path: Path) -> PdfReader:
        """打开 PDF；损坏、加密或 IO 异常统一转为 PageImageError。"""
        try:
            return PdfReader(str(path))
        except (PyPdfError, OSError, ValueError) as error:
            raise PageImageError("PDF 文件损坏、加密或无法读取") from error

    @staticmethod
    def _first_page_image_data(reader: PdfReader, page_number: int) -> bytes:
        """读取指定页的首张可显示嵌入图字节。"""
        try:
            images = reader.pages[page_number - 1].images
            if not images:
                raise PageImageError("该 PDF 不是图片型，无法提取页面图片")
            image_file = images[0]
            for candidate in images:
                if candidate.is_displayed and candidate.data:
                    image_file = candidate
                    break
            if not image_file.data:
                raise PageImageError("PDF 页面嵌入图为空")
            return image_file.data
        except (PyPdfError, OSError, ValueError, KeyError, TypeError) as error:
            raise PageImageError("PDF 页面嵌入图提取失败") from error
