"""项目文档只读接口，限定访问 docs 内的 Markdown 文件。"""

from pathlib import Path
from typing import Annotated, Callable, Dict, List

from fastapi import APIRouter, Depends

from src.service.web_auth_service import AuthenticatedSession
from src.web.errors import ApiError


def create_document_router(
    authenticate: Callable[..., AuthenticatedSession],
    docs_root: Path,
) -> APIRouter:
    """创建登录后可访问的文档目录和正文接口。"""
    router = APIRouter(tags=["文档"])
    root = docs_root.resolve()

    def resolve_document(relative_path: str) -> Path:
        """拒绝路径越界、符号链接越界与非文档文件。"""
        candidate = (root / relative_path).resolve()
        if not candidate.is_relative_to(root) or candidate.suffix.lower() != ".md":
            raise ApiError(404, "DOCUMENT_NOT_FOUND", "文档不存在")
        if not candidate.is_file():
            raise ApiError(404, "DOCUMENT_NOT_FOUND", "文档不存在")
        return candidate

    @router.get("/documents")
    def list_documents(
        _authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> List[Dict[str, str]]:
        """递归列出项目文档，标题使用首个一级 Markdown 标题。"""
        if not root.is_dir():
            raise ApiError(404, "DOCUMENT_DIRECTORY_MISSING", "项目 docs 目录不存在")
        items: List[Dict[str, str]] = []
        for path in sorted(root.rglob("*.md")):
            if not path.resolve().is_relative_to(root) or not path.is_file():
                continue
            content = path.read_text(encoding="utf-8")
            title = next(
                (
                    line[2:].strip()
                    for line in content.splitlines()
                    if line.startswith("# ")
                ),
                path.stem,
            )
            items.append({"path": path.relative_to(root).as_posix(), "title": title})
        return items

    @router.get("/documents/{document_path:path}")
    def get_document(
        document_path: str,
        _authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> Dict[str, str]:
        """返回 Markdown 原文，前端负责安全渲染。"""
        path = resolve_document(document_path)
        return {"path": document_path, "content": path.read_text(encoding="utf-8")}

    return router
