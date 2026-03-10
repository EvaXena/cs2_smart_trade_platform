# -*- coding: utf-8 -*-
"""
错误处理测试
"""
import pytest
from fastapi import FastAPI, status
from fastapi.testclient import TestClient

from app.core.exceptions import (
    APIError,
    ValidationError,
    NotFoundError,
    UnauthorizedError,
    ForbiddenError,
    ConflictError,
    RateLimitError,
    ExternalServiceError,
    BusinessError,
    register_error_handlers,
)


# 创建测试应用
def create_test_app():
    app = FastAPI()
    
    @app.get("/test-not-found")
    async def test_not_found():
        raise NotFoundError("Order", "ORD-123")
    
    @app.get("/test-validation")
    async def test_validation():
        raise ValidationError("Invalid input", details={"field": "price"})
    
    @app.get("/test-unauthorized")
    async def test_unauthorized():
        raise UnauthorizedError()
    
    @app.get("/test-forbidden")
    async def test_forbidden():
        raise ForbiddenError()
    
    @app.get("/test-conflict")
    async def test_conflict():
        raise ConflictError("Resource already exists")
    
    @app.get("/test-rate-limit")
    async def test_rate_limit():
        raise RateLimitError()
    
    @app.get("/test-external")
    async def test_external():
        raise ExternalServiceError("Steam API")
    
    @app.get("/test-business")
    async def test_business():
        raise BusinessError("Insufficient balance", error_code="INSUFFICIENT_BALANCE")
    
    @app.get("/test-generic")
    async def test_generic():
        raise ValueError("Unexpected error")
    
    register_error_handlers(app)
    
    return app


class TestAPIError:
    """API错误基类测试"""
    
    def test_api_error_creation(self):
        """测试创建API错误"""
        error = APIError("Test error", status_code=400, error_code="TEST_ERROR")
        
        assert error.message == "Test error"
        assert error.status_code == 400
        assert error.error_code == "TEST_ERROR"
    
    def test_api_error_with_details(self):
        """测试带详细信息的错误"""
        error = APIError(
            "Test error",
            details={"field": "price", "reason": "invalid"}
        )
        
        assert error.details["field"] == "price"


class TestNotFoundError:
    """资源不存在错误测试"""
    
    def test_not_found_error(self):
        """测试404错误"""
        error = NotFoundError("Order", "ORD-123")
        
        assert error.status_code == status.HTTP_404_NOT_FOUND
        assert "Order" in error.message
        assert "ORD-123" in error.message
        assert error.error_code == "NOT_FOUND"


class TestValidationError:
    """验证错误测试"""
    
    def test_validation_error(self):
        """测试422验证错误"""
        error = ValidationError("Invalid input", details={"field": "price"})
        
        assert error.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert error.error_code == "VALIDATION_ERROR"


class TestUnauthorizedError:
    """认证错误测试"""
    
    def test_unauthorized_error(self):
        """测试401认证错误"""
        error = UnauthorizedError()
        
        assert error.status_code == status.HTTP_401_UNAUTHORIZED
        assert error.error_code == "UNAUTHORIZED"
    
    def test_unauthorized_custom_message(self):
        """测试自定义消息"""
        error = UnauthorizedError("Token expired")
        
        assert "Token expired" in error.message


class TestForbiddenError:
    """权限错误测试"""
    
    def test_forbidden_error(self):
        """测试403权限错误"""
        error = ForbiddenError()
        
        assert error.status_code == status.HTTP_403_FORBIDDEN
        assert error.error_code == "FORBIDDEN"


class TestConflictError:
    """冲突错误测试"""
    
    def test_conflict_error(self):
        """测试409冲突错误"""
        error = ConflictError("Resource exists")
        
        assert error.status_code == status.HTTP_409_CONFLICT
        assert error.error_code == "CONFLICT"


class TestRateLimitError:
    """限流错误测试"""
    
    def test_rate_limit_error(self):
        """测试429限流错误"""
        error = RateLimitError()
        
        assert error.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert error.error_code == "RATE_LIMIT_EXCEEDED"


class TestExternalServiceError:
    """外部服务错误测试"""
    
    def test_external_service_error(self):
        """测试503外部服务错误"""
        error = ExternalServiceError("Steam API")
        
        assert error.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert error.error_code == "EXTERNAL_SERVICE_ERROR"
        assert error.details["service"] == "Steam API"


class TestBusinessError:
    """业务错误测试"""
    
    def test_business_error(self):
        """测试业务错误"""
        error = BusinessError("Insufficient balance", error_code="INSUFFICIENT_BALANCE")
        
        assert error.status_code == status.HTTP_400_BAD_REQUEST
        assert error.error_code == "INSUFFICIENT_BALANCE"


class TestErrorHandlers:
    """错误处理器测试"""
    
    def test_not_found_handler(self):
        """测试404错误处理"""
        app = create_test_app()
        client = TestClient(app)
        
        response = client.get("/test-not-found")
        
        assert response.status_code == 404
        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == "NOT_FOUND"
    
    def test_validation_handler(self):
        """测试422错误处理"""
        app = create_test_app()
        client = TestClient(app)
        
        response = client.get("/test-validation")
        
        assert response.status_code == 422
        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == "VALIDATION_ERROR"
    
    def test_unauthorized_handler(self):
        """测试401错误处理"""
        app = create_test_app()
        client = TestClient(app)
        
        response = client.get("/test-unauthorized")
        
        assert response.status_code == 401
        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == "UNAUTHORIZED"
    
    def test_forbidden_handler(self):
        """测试403错误处理"""
        app = create_test_app()
        client = TestClient(app)
        
        response = client.get("/test-forbidden")
        
        assert response.status_code == 403
        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == "FORBIDDEN"
    
    def test_conflict_handler(self):
        """测试409错误处理"""
        app = create_test_app()
        client = TestClient(app)
        
        response = client.get("/test-conflict")
        
        assert response.status_code == 409
        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == "CONFLICT"
    
    def test_rate_limit_handler(self):
        """测试429错误处理"""
        app = create_test_app()
        client = TestClient(app)
        
        response = client.get("/test-rate-limit")
        
        assert response.status_code == 429
        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == "RATE_LIMIT_EXCEEDED"
    
    def test_external_handler(self):
        """测试503错误处理"""
        app = create_test_app()
        client = TestClient(app)
        
        response = client.get("/test-external")
        
        assert response.status_code == 503
        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == "EXTERNAL_SERVICE_ERROR"
    
    def test_business_handler(self):
        """测试业务错误处理"""
        app = create_test_app()
        client = TestClient(app)
        
        response = client.get("/test-business")
        
        assert response.status_code == 400
        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == "INSUFFICIENT_BALANCE"
    
    def test_generic_handler(self):
        """测试通用错误处理"""
        app = create_test_app()
        client = TestClient(app)
        
        response = client.get("/test-generic")
        
        assert response.status_code == 500
        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == "INTERNAL_ERROR"
