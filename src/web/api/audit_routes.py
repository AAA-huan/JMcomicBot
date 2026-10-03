"""只读审计查询 API，复用认证与分页规范。"""

from dataclasses import asdict
from typing import Annotated, Callable, Optional

from fastapi import APIRouter, Depends, Query

from src.service.web_auth_service import AuthenticatedSession
from src.web.dependencies import WebDependencies
from src.web.errors import ApiError


def create_audit_router(
    dependencies: WebDependencies,
    authenticate: Callable[..., AuthenticatedSession],
) -> APIRouter:
    """创建只向已登录管理员开放的审计路由。"""
    router = APIRouter(tags=["审计"])

    @router.get("/audit-events")
    def list_events(
        _authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
        event_type: Annotated[Optional[str], Query(max_length=128)] = None,
        source: Optional[str] = None,
    ) -> dict[str, object]:
        """返回事件摘要，禁止暴露未受控元数据。"""
        try:
            return asdict(
                dependencies.audit_query_service.list(
                    page, page_size, event_type, source
                )
            )
        except ValueError as error:
            raise ApiError(400, "INVALID_QUERY", str(error)) from error

    return router
