"""权限名单读写与缓存身份查看 API。"""

from dataclasses import asdict
from typing import Annotated, Callable

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from src.service.web_auth_service import AuthenticatedSession
from src.web.dependencies import WebDependencies
from src.web.errors import ApiError

from .common import build_operation_context

AuthenticateCallable = Callable[..., AuthenticatedSession]


class PermissionValueRequest(BaseModel):
    """权限名单值请求。"""

    value: str = Field(min_length=1, max_length=64)


class AdminQQRequest(BaseModel):
    """单管理员 QQ 关联输入，不允许空值代替解绑。"""

    qq_id: str = Field(min_length=1, max_length=20)


def create_permission_router(
    dependencies: WebDependencies, authenticate: AuthenticateCallable
) -> APIRouter:
    """创建权限名单读写与缓存身份视图路由。"""
    router = APIRouter(tags=["权限"])

    @router.get("/permissions")
    def list_permissions(
        _authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> dict[str, object]:
        """返回四类名单与已缓存的 QQ 用户、群组信息。"""
        scopes = {
            scope: list(values)
            for scope, values in dependencies.permission_service.list().items()
        }
        return {
            "scopes": scopes,
            "cached_users": [
                asdict(user)
                for user in dependencies.permission_service.list_cached_users()
            ],
            "cached_groups": [
                asdict(group)
                for group in dependencies.permission_service.list_cached_groups()
            ],
        }

    @router.get("/permissions/admin-qq")
    def get_admin_qq(
        authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> dict[str, object]:
        """返回关联 QQ；不返回账户秘密。"""
        return {"qq_id": dependencies.admin_qq_service.get(authenticated.admin_id)}

    @router.put("/permissions/admin-qq")
    def link_admin_qq(
        body: AdminQQRequest,
        request: Request,
        authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> dict[str, object]:
        """关联或更换管理员 QQ，黑名单用户不能获得授权。"""
        try:
            changed = dependencies.admin_qq_service.update(
                body.qq_id,
                authenticated.admin_id,
                build_operation_context(request, authenticated),
            )
        except ValueError as error:
            raise ApiError(400, "INVALID_ADMIN_QQ", str(error)) from error
        return {"qq_id": body.qq_id, "changed": changed}

    @router.delete("/permissions/admin-qq")
    def unlink_admin_qq(
        request: Request,
        authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> dict[str, object]:
        """解除关联，立即撤销该关联赋予的管理员权限。"""
        changed = dependencies.admin_qq_service.update(
            None,
            authenticated.admin_id,
            build_operation_context(request, authenticated),
        )
        return {"qq_id": None, "changed": changed}

    @router.post("/permissions/{scope}")
    def add_permission(
        scope: str,
        body: PermissionValueRequest,
        request: Request,
        authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> dict[str, object]:
        """向指定名单添加一个 ID；重复添加返回 changed=false。"""
        context = build_operation_context(request, authenticated)
        try:
            changed = dependencies.permission_service.add(scope, body.value, context)
        except ValueError as error:
            raise ApiError(400, "INVALID_PERMISSION", str(error)) from error
        return {"scope": scope, "value": body.value, "changed": changed}

    @router.delete("/permissions/{scope}/{value}")
    def remove_permission(
        scope: str,
        value: str,
        request: Request,
        authenticated: Annotated[AuthenticatedSession, Depends(authenticate)],
    ) -> dict[str, object]:
        """从指定名单移除一个 ID；不存在时返回 changed=false。"""
        context = build_operation_context(request, authenticated)
        try:
            changed = dependencies.permission_service.remove(scope, value, context)
        except ValueError as error:
            raise ApiError(400, "INVALID_PERMISSION", str(error)) from error
        return {"scope": scope, "value": value, "changed": changed}

    return router
