# -*- coding: utf-8 -*-
"""
Debug Mode Tests

测试调试模式下的功能：
- 错误信息详细程度
- 敏感数据脱敏
- 日志级别
- 配置差异
"""
import pytest
import asyncio
from unittest.mock import Mock, patch, MagicMock
from fastapi import Request
from fastapi.testclient import TestClient
from fastapi.responses import JSONResponse
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.exceptions import (
    generic_error_handler,
    sanitize_error_message,
    sanitize_details,
    SENSITIVE_PATTERNS
)
from app.core.config import settings


class TestSensitiveDataSanitization:
    """敏感数据脱敏测试"""
    
    def test_sanitize_password_in_message(self):
        """测试消息中密码脱敏"""
        message = "Database connection failed: password=123456, user=admin"
        result = sanitize_error_message(message)
        
        assert "password=***" in result
        assert "123456" not in result
        assert "user=admin" in result  # 非敏感字段保留
    
    def test_sanitize_token_in_message(self):
        """测试消息中Token脱敏"""
        message = "Auth failed: token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        result = sanitize_error_message(message)
        
        assert "token=***" in result
        assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in result
    
    def test_sanitize_api_key_in_message(self):
        """测试消息中API Key脱敏"""
        message = "API error: api_key=sk-1234567890abcdef"
        result = sanitize_error_message(message)
        
        assert "api_key=***" in result
        assert "sk-1234567890abcdef" not in result
    
    def test_sanitize_connection_string(self):
        """测试连接字符串脱敏"""
        message = "Connection: mysql://user:password@localhost:3306/db"
        result = sanitize_error_message(message)
        
        # 敏感信息被脱敏
        assert "password" not in result or "***" in result
    
    def test_sanitize_bearer_token(self):
        """测试Bearer Token脱敏"""
        message = "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0"
        result = sanitize_error_message(message)
        
        # Bearer token被脱敏
        assert "eyJhbGciOiJIUzI1NiJ9" not in result
    
    def test_sanitize_secret_in_message(self):
        """测试Secret脱敏"""
        message = "Config error: secret=my_super_secret_key"
        result = sanitize_error_message(message)
        
        assert "secret=***" in result
        assert "my_super_secret_key" not in result


class TestSanitizeDetails:
    """详情字典脱敏测试"""
    
    def test_sanitize_dict_password(self):
        """测试字典中密码字段脱敏"""
        details = {
            "username": "admin",
            "password": "secret123",
            "database": "testdb"
        }
        result = sanitize_details(details)
        
        assert result["password"] == "***"
        assert result["username"] == "admin"
        assert result["database"] == "testdb"
    
    def test_sanitize_nested_dict(self):
        """测试嵌套字典脱敏"""
        details = {
            "config": {
                "database": {
                    "host": "localhost",
                    "password": "dbpass"
                }
            }
        }
        result = sanitize_details(details)
        
        assert result["config"]["database"]["password"] == "***"
        assert result["config"]["database"]["host"] == "localhost"
    
    def test_sanitize_list_of_dicts(self):
        """测试字典列表脱敏"""
        details = {
            "users": [
                {"name": "Alice", "password": "pass1"},
                {"name": "Bob", "password": "pass2"}
            ]
        }
        result = sanitize_details(details)
        
        assert result["users"][0]["password"] == "***"
        assert result["users"][1]["password"] == "***"
        assert result["users"][0]["name"] == "Alice"
    
    def test_sanitize_depth_limit(self):
        """测试递归深度限制"""
        # 创建深层嵌套
        details = {"level1": {"level2": {"level3": {"level4": {"password": "deep"}}}}}
        result = sanitize_details(details, depth=0)
        
        # 应该达到深度限制
        assert "..." in str(result) or result.get("level1", {}).get("level2", {}).get("level3", {}).get("level4", {}).get("password") == "***"
    
    def test_sanitize_credential_key(self):
        """测试credential字段脱敏"""
        details = {
            "credential": "important_data",
            "token": "bearer_token"
        }
        result = sanitize_details(details)
        
        assert result["credential"] == "***"
        assert result["token"] == "***"


class TestDebugModeErrorHandler:
    """DEBUG模式错误处理器测试"""
    
    @pytest.mark.asyncio
    async def test_debug_true_returns_full_error(self):
        """测试DEBUG=True返回完整错误"""
        # Mock request
        request = Mock(spec=Request)
        request.url.path = "/api/test"
        request.client.host = "127.0.0.1"
        request.method = "GET"
        
        # Mock exception
        exc = Exception("Database connection failed: password=secret123")
        
        # 设置DEBUG=True
        with patch.object(settings, 'DEBUG', True):
            response = await generic_error_handler(request, exc)
        
        assert response.status_code == 500
        
        # 获取响应内容
        content = response.body.decode()
        assert "Database connection failed" in content or "password=***" in content
    
    @pytest.mark.asyncio
    async def test_debug_false_returns_sanitized(self):
        """测试DEBUG=False返回脱敏错误"""
        # Mock request
        request = Mock(spec=Request)
        request.url.path = "/api/test"
        request.client.host = "127.0.0.1"
        request.method = "GET"
        
        # Mock exception
        exc = Exception("Database connection failed: password=secret123")
        
        # 设置DEBUG=False
        with patch.object(settings, 'DEBUG', False):
            response = await generic_error_handler(request, exc)
        
        assert response.status_code == 500
        
        # 获取响应内容
        content = response.body.decode()
        assert "服务器内部错误" in content or "Internal Server Error" in content
    
    @pytest.mark.asyncio
    async def test_sensitive_data_in_error_is_masked(self):
        """测试错误中的敏感数据被脱敏"""
        # Mock request
        request = Mock(spec=Request)
        request.url.path = "/api/test"
        request.client.host = "127.0.0.1"
        request.method = "GET"
        
        # Mock exception with sensitive data
        exc = Exception("Auth error: token=my_secret_token and password=hidden123")
        
        # 设置DEBUG=True（仍然应该脱敏）
        with patch.object(settings, 'DEBUG', True):
            response = await generic_error_handler(request, exc)
        
        content = response.body.decode()
        
        # 敏感数据应该被脱敏
        assert "my_secret_token" not in content
        assert "hidden123" not in content
    
    @pytest.mark.asyncio
    async def test_exception_type_exposed_in_debug(self):
        """测试DEBUG模式下暴露异常类型"""
        # Mock request
        request = Mock(spec=Request)
        request.url.path = "/api/test"
        request.client.host = "127.0.0.1"
        request.method = "GET"
        
        # 自定义异常
        class CustomError(Exception):
            pass
        
        exc = CustomError("Custom error message")
        
        with patch.object(settings, 'DEBUG', True):
            response = await generic_error_handler(request, exc)
        
        content = response.body.decode()
        assert "CustomError" in content


class TestDebugConfiguration:
    """调试配置测试"""
    
    def test_debug_flag_exists(self):
        """测试DEBUG标志存在"""
        assert hasattr(settings, 'DEBUG')
    
    def test_debug_can_be_boolean(self):
        """测试DEBUG是布尔值"""
        assert isinstance(settings.DEBUG, bool)


class TestSensitivePatterns:
    """敏感信息模式测试"""
    
    def test_patterns_defined(self):
        """测试敏感模式已定义"""
        assert len(SENSITIVE_PATTERNS) > 0
    
    def test_pattern_covers_password(self):
        """测试模式覆盖password"""
        assert any('password' in p for p in SENSITIVE_PATTERNS)
    
    def test_pattern_covers_token(self):
        """测试模式覆盖token"""
        assert any('token' in p for p in SENSITIVE_PATTERNS)
    
    def test_pattern_covers_secret(self):
        """测试模式覆盖secret"""
        assert any('secret' in p for p in SENSITIVE_PATTERNS)
    
    def test_pattern_covers_bearer(self):
        """测试模式覆盖Bearer"""
        assert any('Bearer' in p for p in SENSITIVE_PATTERNS)


class TestLoggingInDebug:
    """调试模式日志测试"""
    
    @pytest.mark.asyncio
    async def test_error_logged_in_debug(self):
        """测试DEBUG模式下记录错误日志"""
        import logging
        from unittest.mock import MagicMock
        
        # Mock request
        request = Mock(spec=Request)
        request.url.path = "/api/test"
        request.client.host = "127.0.0.1"
        request.method = "GET"
        
        exc = ValueError("Test error")
        
        # 使用patch来捕获日志
        with patch('app.core.exceptions.logger') as mock_logger:
            with patch.object(settings, 'DEBUG', True):
                await generic_error_handler(request, exc)
            
            # 验证error被调用
            assert mock_logger.error.called


class TestErrorResponseStructure:
    """错误响应结构测试"""
    
    @pytest.mark.asyncio
    async def test_error_response_has_code(self):
        """测试错误响应包含code"""
        request = Mock(spec=Request)
        request.url.path = "/api/test"
        request.client.host = "127.0.0.1"
        request.method = "GET"
        
        exc = Exception("Test error")
        
        with patch.object(settings, 'DEBUG', False):
            response = await generic_error_handler(request, exc)
        
        content = response.body.decode()
        assert '"code"' in content or "'code'" in content
    
    @pytest.mark.asyncio
    async def test_error_response_has_message(self):
        """测试错误响应包含message"""
        request = Mock(spec=Request)
        request.url.path = "/api/test"
        request.client.host = "127.0.0.1"
        request.method = "GET"
        
        exc = Exception("Test error")
        
        with patch.object(settings, 'DEBUG', False):
            response = await generic_error_handler(request, exc)
        
        content = response.body.decode()
        assert '"message"' in content or "'message'" in content
    
    @pytest.mark.asyncio
    async def test_error_response_has_path(self):
        """测试错误响应包含path"""
        request = Mock(spec=Request)
        request.url.path = "/api/test"
        request.client.host = "127.0.0.1"
        request.method = "GET"
        
        exc = Exception("Test error")
        
        with patch.object(settings, 'DEBUG', True):
            response = await generic_error_handler(request, exc)
        
        content = response.body.decode()
        assert "/api/test" in content


class TestEdgeCases:
    """边界情况测试"""
    
    def test_sanitize_empty_string(self):
        """测试空字符串脱敏"""
        result = sanitize_error_message("")
        assert result == ""
    
    def test_sanitize_none(self):
        """测试None值脱敏"""
        result = sanitize_error_message(None)
        # 应该处理None
    
    def test_sanitize_no_sensitive_data(self):
        """测试无敏感数据"""
        message = "Normal error message without sensitive data"
        result = sanitize_error_message(message)
        assert result == message
    
    def test_sanitize_multiple_passwords(self):
        """测试多个密码脱敏"""
        message = "password=123 and another_password=456"
        result = sanitize_error_message(message)
        
        assert "123" not in result
        assert "456" not in result
    
    def test_sanitize_dict_with_all_sensitive(self):
        """测试全部是敏感字段的字典"""
        details = {
            "password": "secret",
            "token": "bearer",
            "secret": "key"
        }
        result = sanitize_details(details)
        
        assert result["password"] == "***"
        assert result["token"] == "***"
        assert result["secret"] == "***"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
