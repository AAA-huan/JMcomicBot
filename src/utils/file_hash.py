"""文件摘要工具，供文件校验与数据库备份共用。"""

from pathlib import Path

import hashlib

_HASH_CHUNK_SIZE = 1024 * 1024


def sha256_of(path: Path) -> str:
    """流式计算文件 SHA-256，避免一次性读入大文件。"""
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(_HASH_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()
