"""运行时配置查看与修改 API。"""

from dataclasses import asdict
from typing import Annotated, Any, Callable

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from src.service.web_auth_service import AuthenticatedSession
from src.web.dependencies import WebDependencies
from src.web.errors import ApiError

from .common import build_operation_context

AuthenticateCallable = Callable[..., AuthenticatedSession]


class SettingUpdateRequest(BaseModel):
    """配置修改请求；具体类型由设置注册表校验。"""

    value: Any


class OptionFileUpdateRequest(BaseModel):
    """option.yml 内容修改请求。"""

    content: str


def create_setting_router(
    dependencies: WebDependencies, authenticate: AuthenticateCallable
) -> APIRouter:
    """创建配置查看与修改路由。"""
    router = APIRouter(tags=["配置"])

    @router.get("/settings")
    def list_settings(
        _authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> dict[str, object]:
        """返回全部配置项；敏感值明文返回（局域网单管理员控制台）。"""
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
        """修改配置；启动项保存后重启生效，敏感值明文返回。"""
        context = build_operation_context(request, authenticated)
        if key not in dependencies.settings_service.definitions:
            raise ApiError(404, "SETTING_NOT_FOUND", "不支持的配置项")
        try:
            view = dependencies.settings_service.update(key, body.value, context)
        except ValueError as error:
            raise ApiError(400, "SETTING_INVALID_VALUE", str(error)) from error
        return asdict(view)

    @router.get("/settings/option-file")
    def read_option_file(
        _authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> dict[str, object]:
        """返回 option.yml 当前内容；文件不存在时返回空串。"""
        return {"content": dependencies.option_file_service.read()}

    @router.put("/settings/option-file")
    def update_option_file(
        body: OptionFileUpdateRequest,
        request: Request,
        authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> dict[str, object]:
        """校验并保存 option.yml；保存后下一个下载任务即生效，无需重启。"""
        context = build_operation_context(request, authenticated)
        try:
            dependencies.option_file_service.write(body.content, context)
        except ValueError as error:
            raise ApiError(400, "OPTION_FILE_INVALID", str(error)) from error
        return {
            "content": dependencies.option_file_service.read(),
            "updated": True,
        }

    return router
