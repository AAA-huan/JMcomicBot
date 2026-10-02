"""Web API 共享认证依赖与操作上下文工具。"""

from typing import Annotated, Callable, Optional

from fastapi import Cookie, HTTPException, Request, status

from src.service import OperationContext
from src.service.web_auth_service import AuthenticatedSession, WebAuthService
from src.web.errors import ApiError

SESSION_COOKIE_NAME = "jmbot_session"


def build_authenticate(
    auth_service: WebAuthService,
) -> Callable[..., AuthenticatedSession]:
    """构造会话认证依赖；未登录与无效会话统一返回 401。"""

    def authenticate(
        token: Annotated[Optional[str], Cookie(alias=SESSION_COOKIE_NAME)] = None,
    ) -> AuthenticatedSession:
        if token is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "尚未登录")
        authenticated = auth_service.authenticate(token)
        if authenticated is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "会话无效或已过期")
        return authenticated

    return authenticate


def build_operation_context(
    request: Request, authenticated: AuthenticatedSession
) -> OperationContext:
    """构造 Web 操作上下文；无法识别客户端地址时明确报错。"""
    if request.client is None:
        raise ApiError(400, "CLIENT_ADDRESS_MISSING", "无法识别客户端地址")
    return OperationContext.web(str(authenticated.admin_id), request.client.host)
