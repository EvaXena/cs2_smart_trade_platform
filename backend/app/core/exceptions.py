# -*- coding: utf-8 -*-
"""
统一的错误处理模块
"""
from typing import Optional, Dict, Any
from fastapi import HTTPException, status
from fastapi.responses import JSONResponse
from fastapi import Request
import logging
import traceback

logger = logging.getLogger(__name__)


class APIError(Exception):
    """API错误基类"""
    
    def __init__(
        self,
        message: str,
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        error_code: str = "INTERNAL_ERROR",
        details: Dict[str, Any] = None
    ):
        self.message = message
        self.status_code = status_code
        self.error_code = error_code
        self.details = details or {}
        super().__init__(self.message)


class ValidationError(APIError):
    """验证错误"""
    
    def __init__(self, message: str, details: Dict[str, Any] = None):
        super().__init__(
            message=message,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            error_code="VALIDATION_ERROR",
            details=details
        )


class NotFoundError(APIError):
    """资源不存在错误"""
    
    def __init__(self, resource: str, resource_id: Any):
        super().__init__(
            message=f"{resource}不存在: {resource_id}",
            status_code=status.HTTP_404_NOT_FOUND,
            error_code="NOT_FOUND",
            details={"resource": resource, "id": resource_id}
        )


class UnauthorizedError(APIError):
    """认证错误"""
    
    def __init__(self, message: str = "未授权访问"):
        super().__init__(
            message=message,
            status_code=status.HTTP_401_UNAUTHORIZED,
            error_code="UNAUTHORIZED"
        )


class ForbiddenError(APIError):
    """权限错误"""
    
    def __init__(self, message: str = "权限不足"):
        super().__init__(
            message=message,
            status_code=status.HTTP_403_FORBIDDEN,
            error_code="FORBIDDEN"
        )


class ConflictError(APIError):
    """冲突错误"""
    
    def __init__(self, message: str, details: Dict[str, Any] = None):
        super().__init__(
            message=message,
            status_code=status.HTTP_409_CONFLICT,
            error_code="CONFLICT",
            details=details
        )


class RateLimitError(APIError):
    """限流错误"""
    
    def __init__(self, message: str = "请求过于频繁，请稍后再试"):
        super().__init__(
            message=message,
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            error_code="RATE_LIMIT_EXCEEDED"
        )


class ExternalServiceError(APIError):
    """外部服务错误"""
    
    def __init__(self, service: str, message: str = None):
        super().__init__(
            message=message or f"外部服务 {service} 不可用",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            error_code="EXTERNAL_SERVICE_ERROR",
            details={"service": service}
        )


class BusinessError(APIError):
    """业务逻辑错误"""
    
    def __init__(self, message: str, error_code: str = "BUSINESS_ERROR", details: Dict[str, Any] = None):
        super().__init__(
            message=message,
            status_code=status.HTTP_400_BAD_REQUEST,
            error_code=error_code,
            details=details
        )


async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:
    """
    API错误处理器
    
    返回标准化的错误响应:
    {
        "error": {
            "code": "VALIDATION_ERROR",
            "message": "错误消息",
            "details": {...},
            "path": "/api/v1/orders"
        }
    }
    """
    error_response = {
        "error": {
            "code": exc.error_code,
            "message": exc.message,
            "details": exc.details,
            "path": str(request.url.path),
        }
    }
    
    # 记录错误日志
    log_level = "warning" if exc.status_code < 500 else "error"
    getattr(logger, log_level)(
        f"API Error: {exc.error_code} - {exc.message}",
        extra={
            "context": {
                "error_code": exc.error_code,
                "status_code": exc.status_code,
                "path": str(request.url.path),
                "method": request.method,
                "details": exc.details
            }
        }
    )
    
    return JSONResponse(
        status_code=exc.status_code,
        content=error_response
    )


async def generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    通用错误处理器 - 处理未预期的错误
    """
    # 记录完整的错误堆栈
    logger.error(
        f"Unhandled exception: {str(exc)}",
        extra={
            "context": {
                "path": str(request.url.path),
                "method": request.method,
                "exception_type": type(exc).__name__
            }
        }
    )
    
    # 返回脱敏的错误响应（生产环境不暴露详细信息）
    error_response = {
        "error": {
            "code": "INTERNAL_ERROR",
            "message": "服务器内部错误" if not settings.DEBUG else str(exc),
            "details": {"exception_type": type(exc).__name__} if settings.DEBUG else {},
            "path": str(request.url.path),
        }
    }
    
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=error_response
    )


def register_error_handlers(app) -> None:
    """注册错误处理器到应用"""
    from fastapi import FastAPI
    
    # 注册API错误处理器
    app.add_exception_handler(APIError, api_error_handler)
    
    # 注册通用错误处理器
    app.add_exception_handler(Exception, generic_error_handler)
