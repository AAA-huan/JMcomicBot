"""阅读器偏好设置读写 API。"""

from datetime import datetime
from typing import Annotated, Callable, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from src.database.models import ReadingSetting
from src.service.web_auth_service import AuthenticatedSession
from src.web.dependencies import WebDependencies
from src.web.errors import ApiError

from .common import build_operation_context

AuthenticateCallable = Callable[..., AuthenticatedSession]


class ReadingSettingUpdateRequest(BaseModel):
    """阅读设置整体更新请求；未传字段保留已有值。"""

    reading_mode: Optional[str] = Field(default=None, max_length=16)
    continuous: Optional[bool] = None
    click_to_turn: Optional[bool] = None
    reverse_click: Optional[bool] = None
    dark_background: Optional[bool] = None
    prefetch_pages: Optional[int] = None


def _setting_payload(setting: ReadingSetting) -> dict[str, object]:
    """把阅读设置记录转换为稳定响应结构。"""
    updated_at: Optional[datetime] = setting.updated_at
    return {
        "reading_mode": setting.reading_mode,
        "continuous": setting.continuous,
        "click_to_turn": setting.click_to_turn,
        "reverse_click": setting.reverse_click,
        "dark_background": setting.dark_background,
        "prefetch_pages": setting.prefetch_pages,
        "updated_at": updated_at,
    }


def create_reader_router(
    dependencies: WebDependencies, authenticate: AuthenticateCallable
) -> APIRouter:
    """创建阅读设置路由；设置按当前登录管理员账户隔离。"""
    router = APIRouter(tags=["阅读器"])

    @router.get("/reader/settings")
    def get_reader_settings(
        authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> dict[str, object]:
        """返回当前管理员阅读设置；未保存时返回默认值。"""
        return _setting_payload(
            dependencies.reading_setting_service.get_or_default(authenticated.admin_id)
        )

    @router.put("/reader/settings")
    def update_reader_settings(
        body: ReadingSettingUpdateRequest,
        request: Request,
        authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> dict[str, object]:
        """整体更新阅读设置；非法模式或反转依赖缺失返回 400。"""
        fields = {name: getattr(body, name) for name in body.model_fields_set}
        try:
            setting = dependencies.reading_setting_service.upsert(
                authenticated.admin_id,
                fields,
                build_operation_context(request, authenticated),
            )
        except ValueError as error:
            raise ApiError(400, "READER_SETTING_INVALID", str(error)) from error
        return _setting_payload(setting)

    return router
