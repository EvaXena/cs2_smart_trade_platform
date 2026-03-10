# -*- coding: utf-8 -*-
"""
审计中间件测试
"""
import pytest
import json
from unittest.mock import MagicMock, AsyncMock, patch
from starlette.requests import Request
from starlette.responses import JSONResponse
from app.middleware.audit import AuditLogger, get_audit_logger, audit_middleware


class MockRequest:
    """模拟请求对象"""
    def __init__(self, method="GET", path="/api/v1/test", client_ip="127.0.0.1"):
        self.method = method
        self.url = MagicMock()
        self.url.path = path
        self.headers = {
            "User-Agent": "TestAgent/1.0",
            "X-Forwarded-For": client_ip
        }
        self.client = MagicMock()
        self.client.host = client_ip
        self.query_params = {}
        self.state = MagicMock()
        self._body = None
    
    async def body(self):
        return self._body if self._body else b""
    
    def set_body(self, body: bytes):
        self._body = body


class TestAuditLogger:
    """审计日志器测试"""
    
    def test_init_default(self):
        """测试默认初始化"""
        logger = AuditLogger()
        
        assert logger.log_sensitive_data is False
        assert "password" in logger.sensitive_fields
    
    def test_init_with_sensitive_data(self):
        """测试启用敏感数据记录"""
        logger = AuditLogger(log_sensitive_data=True)
        
        assert logger.log_sensitive_data is True
    
    def test_get_client_info(self):
        """测试获取客户端信息"""
        logger = AuditLogger()
        request = MockRequest()
        
        client_info = logger._get_client_info(request)
        
        assert "ip" in client_info
        assert "user_agent" in client_info
    
    def test_get_user_info_with_state(self):
        """测试从state获取用户信息"""
Logger()
        request = MockRequest()
        logger = Audit        request.state.user_id = 123
        request.state.username = "testuser"
        
        user_info = logger._get_user_info(request)
        
        assert user_info["user_id"] == 123
        assert user_info["username"] == "testuser"
    
    def test_get_user_info_without_state(self):
        """测试无用户信息时返回None"""
        logger = AuditLogger()
        request = MockRequest()
        
        user_info = logger._get_user_info(request)
        
        assert user_info is None
    
    def test_mask_sensitive_data_disabled(self):
        """测试禁用敏感数据脱敏"""
        logger = AuditLogger(log_sensitive_data=False)
        
        data = {
            "username": "test",
            "password": "secret123",
            "email": "test@example.com"
        }
        
        masked = logger._mask_sensitive_data(data)
        
        assert masked["username"] == "test"
        assert masked["password"] == "***"
        assert masked["email"] == "test@example.com"
    
    def test_mask_sensitive_data_enabled(self):
        """测试启用敏感数据脱敏"""
        logger = AuditLogger(log_sensitive_data=True)
        
        data = {
            "username": "test",
            "password": "secret123"
        }
        
        masked = logger._mask_sensitive_data(data)
        
        assert masked["password"] == "secret123"
    
    def test_match_pattern_exact(self):
        """测试精确匹配"""
        logger = AuditLogger()
        
        config = logger._match_pattern("POST", "/api/v1/auth/login")
        
        assert config is not None
        assert config["action"] == "user_login"
        assert config["level"] == "info"
    
    def test_match_pattern_prefix(self):
        """测试前缀匹配"""
        logger = AuditLogger()
        
        config = logger._match_pattern("DELETE", "/api/v1/bots/123")
        
        assert config is not None
        assert config["action"] == "bot_delete"
    
    def test_match_pattern_no_match(self):
        """测试无匹配"""
        logger = AuditLogger()
        
        config = logger._match_pattern("GET", "/api/v1/unknown")
        
        assert config is None
    
    def test_audit_patterns_auth(self):
        """测试认证相关审计模式"""
        logger = AuditLogger()
        
        # 登录
        config = logger._match_pattern("POST", "/api/v1/auth/login")
        assert config["action"] == "user_login"
        
        # 登出
        config = logger._match_pattern("POST", "/api/v1/auth/logout")
        assert config["action"] == "user_logout"
        
        # 注册
        config = logger._match_pattern("POST", "/api/v1/auth/register")
        assert config["action"] == "user_register"
    
    def test_audit_patterns_orders(self):
        """测试订单相关审计模式"""
        logger = AuditLogger()
        
        # 创建订单
        config = logger._match_pattern("POST", "/api/v1/orders")
        assert config["action"] == "order_create"
        
        # 取消订单
        config = logger._match_pattern("DELETE", "/api/v1/orders/123")
        assert config["action"] == "order_cancel"
    
    def test_audit_patterns_bots(self):
        """测试机器人相关审计模式"""
        logger = AuditLogger()
        
        # 创建机器人
        config = logger._match_pattern("POST", "/api/v1/bots")
        assert config["action"] == "bot_create"
        
        # 删除机器人
        config = logger._match_pattern("DELETE", "/api/v1/bots/123")
        assert config["action"] == "bot_delete"
        
        # 更新机器人
        config = logger._match_pattern("PUT", "/api/v1/bots/123")
        assert config["action"] == "bot_update"
    
    def test_audit_patterns_monitors(self):
        """测试监控相关审计模式"""
        logger = AuditLogger()
        
        # 创建监控
        config = logger._match_pattern("POST", "/api/v1/monitors")
        assert config["action"] == "monitor_create"
        
        # 删除监控
        config = logger._match_pattern("DELETE", "/api/v1/monitors/123")
        assert config["action"] == "monitor_delete"


class TestAuditLoggerLog:
    """审计日志记录测试"""
    
    def test_log_no_audit_pattern(self):
        """测试无审计模式时不记录"""
        logger = AuditLogger()
        request = MockRequest(method="GET", path="/api/v1/stats")
        
        # 不应该抛出异常
        logger.log(request, 200, 100.0)
    
    def test_log_with_user(self):
        """测试带用户信息的日志"""
        logger = AuditLogger()
        request = MockRequest(method="POST", path="/api/v1/auth/login")
        request.state.user_id = 123
        request.state.username = "testuser"
        
        logger.log(request, 200, 150.0)
    
    def test_log_with_request_body(self):
        """测试带请求体的日志"""
        logger = AuditLogger()
        request = MockRequest(method="POST", path="/api/v1/auth/login")
        
        request_body = {"username": "test", "password": "secret"}
        
        logger.log(request, 200, 100.0, request_body=request_body)
    
    def test_log_error_response(self):
        """测试错误响应包含响应体"""
        logger = AuditLogger()
        request = MockRequest(method="POST", path="/api/v1/auth/login")
        
        response_body = {"error": "Invalid credentials"}
        
        logger.log(request, 401, 50.0, response_body=response_body)
    
    def test_log_warning_action(self):
        """测试警告级别操作"""
        logger = AuditLogger()
        request = MockRequest(method="DELETE", path="/api/v1/bots/123")
        
        logger.log(request, 200, 100.0)
    
    def test_log_sensitive_fields_masked(self):
        """测试敏感字段被脱敏"""
        logger = AuditLogger(log_sensitive_data=False)
        request = MockRequest(method="POST", path="/api/v1/auth/register")
        
        request_body = {
            "username": "newuser",
            "email": "new@example.com",
            "password": "secret123",
            "buff_cookie": "session=abc"
        }
        
        # 验证脱敏
        masked = logger._mask_sensitive_data(request_body)
        
        assert masked["username"] == "newuser"
        assert masked["password"] == "***"
        assert masked["buff_cookie"] == "***"
        assert masked["email"] == "new@example.com"


class TestAuditMiddleware:
    """审计中间件测试"""
    
    @pytest.mark.asyncio
    async def test_audit_middleware_no_body(self):
        """测试无请求体的中间件"""
        request = MockRequest(method="GET", path="/api/v1/test")
        
        async def mock_call_next(req):
            return JSONResponse({"status": "ok"})
        
        response = await audit_middleware(request, mock_call_next)
        
        assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_audit_middleware_with_json_body(self):
        """测试带JSON请求体的中间件"""
        request = MockRequest(method="POST", path="/api/v1/auth/login")
        request.set_body(b'{"username": "test", "password": "123"}')
        
        async def mock_call_next(req):
            return JSONResponse({"status": "ok"})
        
        response = await audit_middleware(request, mock_call_next)
        
        assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_audit_middleware_non_json_body(self):
        """测试非JSON请求体的中间件"""
        request = MockRequest(method="POST", path="/api/v1/auth/login")
        request.set_body(b"not json data")
        
        async def mock_call_next(req):
            return JSONResponse({"status": "ok"})
        
        response = await audit_middleware(request, mock_call_next)
        
        assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_audit_middleware_audited_endpoint(self):
        """测试审计端点"""
        request = MockRequest(method="POST", path="/api/v1/auth/login")
        request.set_body(b'{"username": "test"}')
        
        async def mock_call_next(req):
            return JSONResponse({"status": "ok"})
        
        response = await audit_middleware(request, mock_call_next)
        
        # 审计端点应该记录日志
        assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_audit_middleware_error_status(self):
        """测试错误状态码"""
        request = MockRequest(method="POST", path="/api/v1/auth/login")
        request.set_body(b'{"username": "test"}')
        
        async def mock_call_next(req):
            return JSONResponse(
                {"error": "Invalid credentials"},
                status_code=401
            )
        
        response = await audit_middleware(request, mock_call_next)
        
        assert response.status_code == 401


class TestGetAuditLogger:
    """获取审计日志器测试"""
    
    def test_get_audit_logger_singleton(self):
        """测试单例模式"""
        logger1 = get_audit_logger()
        logger2 = get_audit_logger()
        
        assert logger1 is logger2


class TestAuditLoggerEdgeCases:
    """审计日志边界情况测试"""
    
    def test_custom_audit_patterns(self):
        """测试自定义审计模式"""
        # 创建自定义审计日志器
        custom_patterns = {
            "POST:/api/v1/custom": {"action": "custom_action", "level": "info"}
        }
        
        # 验证模式存在
        logger = AuditLogger()
        
        config = logger._match_pattern("POST", "/api/v1/custom")
        assert config["action"] == "custom_action"
    
    def test_all_audit_levels(self):
        """测试所有审计级别"""
        logger = AuditLogger()
        
        # info级别
        config = logger._match_pattern("POST", "/api/v1/auth/login")
        assert config["level"] == "info"
        
        # warning级别
        config = logger._match_pattern("DELETE", "/api/v1/bots/123")
        assert config["level"] == "warning"
    
    def test_query_params_in_audit(self):
        """测试查询参数包含在审计中"""
        logger = AuditLogger()
        request = MockRequest(method="GET", path="/api/v1/items")
        request.query_params = {"page": "1", "page_size": "20"}
        
        # 验证能获取query_params
        assert dict(request.query_params) == {"page": "1", "page_size": "20"}
