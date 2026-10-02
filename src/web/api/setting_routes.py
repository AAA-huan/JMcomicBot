"""运行时配置查看与修改 API。"""

from dataclasses import asdict
from typing import Annotated, Any, Callable

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from src.service.web_auth_service import AuthenticatedSession
from src.web.api.common import build_operation_context
from src.web.dependencies import WebDependencies
from src.web.errors import ApiError

AuthenticateCallable = Callable[..., AuthenticatedSession]


class SettingUpdateRequest(BaseModel):
    """配置修改请求；具体类型由设置注册表校验。"""

    value: Any


def create_setting_router(
    dependencies: WebDependencies, authenticate: AuthenticateCallable
) -> APIRouter:
    """创建配置查看与修改路由。"""
    router = APIRouter(tags=["配置"])

    @router.get("/settings")
    def list_settings(
        _authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> dict[str, object]:
        """返回全部配置项；敏感值只暴露是否已设置。"""
        return {
            "items": [asdict(view) for view in dependencies.settings_service.list()]
        }

    @router.patch("/settings/{key}")
    def update_setting(
        key: str,
        body: SettingUpdateRequest,
        request: Request,
        authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> dict[str, object]:
        """修改配置并立即生效；只读与敏感配置明确拒绝。"""
        context = build_operation_context(request, authenticated)
        if key not in dependencies.settings_service.definitions:
            raise ApiError(404, "SETTING_NOT_FOUND", "不支持的配置项")
        try:
            view = dependencies.settings_service.update(key, body.value, context)
        except ValueError as error:
            raise ApiError(400, "SETTING_INVALID_VALUE", str(error)) from error
        return asdict(view)

    return router
