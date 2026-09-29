"""Web API 统一错误对象与异常处理器。"""

from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from src.logging.logger_config import logger


class ApiError(Exception):
    """包含稳定错误码且不会泄露内部异常信息的 API 异常。"""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: Optional[Any] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


def error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: Optional[Any] = None,
) -> JSONResponse:
    """构造统一错误响应，不包含 traceback 或内部路径。"""
    request_id = request.state.request_id
    return JSONResponse(
        status_code=status_code,
        content={
            "code": code,
            "message": message,
            "details": details,
            "request_id": request_id,
        },
        headers={"X-Request-ID": request_id},
    )


def install_error_handlers(app: FastAPI) -> None:
    """注册 API、验证、HTTP 和未处理异常的统一响应格式。"""

    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, error: ApiError) -> JSONResponse:
        return error_response(
            request,
            error.status_code,
            error.code,
            error.message,
            error.details,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        details = [
            {
                "field": ".".join(str(part) for part in item["loc"]),
                "message": item["msg"],
            }
            for item in error.errors()
        ]
        return error_response(
            request,
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "VALIDATION_ERROR",
            "请求参数不符合要求",
            details,
        )

    @app.exception_handler(HTTPException)
    async def handle_http_error(request: Request, error: HTTPException) -> JSONResponse:
        codes = {
            status.HTTP_400_BAD_REQUEST: "BAD_REQUEST",
            status.HTTP_401_UNAUTHORIZED: "AUTH_REQUIRED",
            status.HTTP_403_FORBIDDEN: "FORBIDDEN",
            status.HTTP_404_NOT_FOUND: "NOT_FOUND",
            status.HTTP_409_CONFLICT: "CONFLICT",
            status.HTTP_429_TOO_MANY_REQUESTS: "RATE_LIMITED",
        }
        return error_response(
            request,
            error.status_code,
            codes.get(error.status_code, "HTTP_ERROR"),
            str(error.detail),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(
        request: Request, error: Exception
    ) -> JSONResponse:
        logger.error(
            f"Web API 未处理异常，请求ID {request.state.request_id}，"
            f"异常类型: {type(error).__name__}"
        )
        return error_response(
            request,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "INTERNAL_ERROR",
            "服务器内部错误",
        )
