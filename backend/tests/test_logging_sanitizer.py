# -*- coding: utf-8 -*-
"""
日志脱敏过滤器测试
测试 SensitiveDataFilter 各字段脱敏效果
验证 JWT、Token、密码等敏感信息确实被过滤
"""
import pytest
import logging
import json
from app.core.logging_config import (
    SensitiveDataFilter, 
    SensitiveFieldFilter, 
    SENSITIVE_PATTERNS, 
    BLOCKED_FIELDS
)


class TestSensitiveDataFilter:
    """测试敏感数据过滤器"""
    
    def setup_method(self):
        """每个测试方法前设置过滤器"""
        self.filter = SensitiveDataFilter()
    
    def _create_log_record(self, message: str) -> logging.LogRecord:
        """创建日志记录"""
        logger = logging.getLogger("test")
        return logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg=message,
            args=(),
            exc_info=None
        )
    
    def test_password_masking(self):
        """测试密码字段脱敏"""
        test_cases = [
            ('{"password": "secret123"}', '"password":"***"'),
            ('password=secret123', 'password=***'),
            ('"password": "my_password"', '"password": "***"'),
            ('User password: test123', 'User password: ***'),
        ]
        
        for original, expected in test_cases:
            record = self._create_log_record(original)
            self.filter.filter(record)
            assert expected in record.getMessage(), f"Failed for: {original}"
    
    def test_token_masking(self):
        """测试Token字段脱敏"""
        test_cases = [
            ('{"token": "abc123xyz"}', '"token":"***"'),
            ('"token": "Bearer xyz123"', '"token": "***"'),
            ('access_token=token123', 'access_token=***'),
        ]
        
        for original, expected in test_cases:
            record = self._create_log_record(original)
            self.filter.filter(record)
            assert expected in record.getMessage(), f"Failed for: {original}"
    
    def test_jwt_masking(self):
        """测试JWT token脱敏"""
        # 完整的JWT格式
        jwt_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        
        test_cases = [
            (f'Authorization: Bearer {jwt_token}', 'Authorization: Bearer ***'),
            (f'"jwt": "{jwt_token}"', '"jwt": "***"'),
            (f'jwt={jwt_token}', 'jwt=***'),
        ]
        
        for original, expected in test_cases:
            record = self._create_log_record(original)
            self.filter.filter(record)
            assert expected in record.getMessage(), f"Failed for: {original}"
            # 确保原始JWT不在日志中
            assert jwt_token not in record.getMessage(), f"JWT leaked for: {original}"
    
    def test_api_key_masking(self):
        """测试API Key脱敏"""
        test_cases = [
            ('{"api_key": "sk-1234567890"}', '"api_key":"***"'),
            ('apiKey=abcdef123456', 'apiKey=***'),
            ('"steam_api_key": "key123"', '"steam_api_key":"***"'),
        ]
        
        for original, expected in test_cases:
            record = self._create_log_record(original)
            self.filter.filter(record)
            assert expected in record.getMessage(), f"Failed for: {original}"
    
    def test_cookie_masking(self):
        """测试Cookie脱敏"""
        test_cases = [
            ('Cookie: session=abc123', 'Cookie: ***'),
            ('cookie="session=xyz"', 'cookie="***"'),
        ]
        
        for original, expected in test_cases:
            record = self._create_log_record(original)
            self.filter.filter(record)
            assert expected in record.getMessage(), f"Failed for: {original}"
    
    def test_steam_cookie_masking(self):
        """测试Steam Cookie脱敏"""
        test_cases = [
            ('steam_cookie=steam123', 'steam_cookie=***'),
            ('"steam_session": "session123"', '"steam_session":"***"'),
        ]
        
        for original, expected in test_cases:
            record = self._create_log_record(original)
            self.filter.filter(record)
            assert expected in record.getMessage(), f"Failed for: {original}"
    
    def test_buff_cookie_masking(self):
        """测试Buff Cookie脱敏"""
        test_cases = [
            ('buff_cookie=buff123', 'buff_cookie=***'),
            ('"buff_session": "session123"', '"buff_session":"***"'),
        ]
        
        for original, expected in test_cases:
            record = self._create_log_record(original)
            self.filter.filter(record)
            assert expected in record.getMessage(), f"Failed for: {original}"
    
    def test_mafile_masking(self):
        """测试MaFile脱敏"""
        test_cases = [
            ('mafile={"secret": "data"}', 'mafile="***"'),
            ('"steam_mafile": "content"', '"steam_mafile":"***"'),
        ]
        
        for original, expected in test_cases:
            record = self._create_log_record(original)
            self.filter.filter(record)
            assert expected in record.getMessage(), f"Failed for: {original}"
    
    def test_long_hex_pattern_masking(self):
        """测试长十六进制字符串脱敏"""
        # Steam ID (17位数字)
        steam_id = "76561198012345678"
        record = self._create_log_record(f"SteamID: {steam_id}")
        self.filter.filter(record)
        assert "***" in record.getMessage()
        assert steam_id not in record.getMessage()
        
        # 40位十六进制字符串
        long_hex = "a" * 40
        record = self._create_log_record(f"Hex: {long_hex}")
        self.filter.filter(record)
        assert "***" in record.getMessage()
    
    def test_email_masking(self):
        """测试邮箱脱敏（可选）"""
        # 邮箱在 SENSITIVE_PATTERNS 中定义但不在 BLOCKED_FIELDS 中
        # 这是一个检测模式，不是完全屏蔽
        test_cases = [
            'user@example.com',
            'test.user@domain.co.uk',
        ]
        
        for email in test_cases:
            record = self._create_log_record(f"User: {email}")
            self.filter.filter(record)
            # 邮箱应该被脱敏
            result = record.getMessage()
            assert "***" in result
    
    def test_multiple_sensitive_fields(self):
        """测试多个敏感字段同时存在"""
        original = '{"password": "pass123", "token": "abc", "api_key": "key123"}'
        record = self._create_log_record(original)
        self.filter.filter(record)
        result = record.getMessage()
        
        assert '"password":"***"' in result
        assert '"token":"***"' in result
        assert '"api_key":"***"' in result
    
    def test_non_sensitive_data_unchanged(self):
        """测试非敏感数据不被修改"""
        test_cases = [
            '{"item_id": "12345", "price": 100}',
            'User logged in successfully',
            '{"status": "ok", "message": "done"}',
            'Normal log message without sensitive data',
        ]
        
        for original in test_cases:
            record = self._create_log_record(original)
            self.filter.filter(record)
            assert record.getMessage() == original
    
    def test_sensitive_fields_blocked_list(self):
        """测试BLOCKED_FIELDS列表中的字段"""
        for field in BLOCKED_FIELDS:
            original = f'{{"{field}": "sensitive_data"}}'
            record = self._create_log_record(original)
            self.filter.filter(record)
            assert '"***"' in record.getMessage(), f"Field {field} not blocked"


class TestSensitiveFieldFilter:
    """测试结构化字段过滤器"""
    
    def setup_method(self):
        """每个测试方法前设置过滤器"""
        self.filter = SensitiveFieldFilter()
    
    def _create_log_record(self, extra_data: dict) -> logging.LogRecord:
        """创建带extra_data的日志记录"""
        logger = logging.getLogger("test")
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="test",
            args=(),
            exc_info=None
        )
        record.extra_data = extra_data
        return record
    
    def test_dict_password_masking(self):
        """测试字典中密码字段脱敏"""
        original = {"password": "secret123", "username": "testuser"}
        record = self._create_log_record(original.copy())
        self.filter.filter(record)
        
        assert record.extra_data["password"] == "***"
        assert record.extra_data["username"] == "testuser"
    
    def test_nested_dict_masking(self):
        """测试嵌套字典脱敏"""
        original = {
            "user": {
                "password": "secret",
                "data": "normal"
            }
        }
        record = self._create_log_record(original.copy())
        self.filter.filter(record)
        
        assert record.extra_data["user"]["password"] == "***"
        assert record.extra_data["user"]["data"] == "normal"
    
    def test_list_masking(self):
        """测试列表脱敏"""
        original = {
            "users": [
                {"password": "pass1", "name": "user1"},
                {"password": "pass2", "name": "user2"}
            ]
        }
        record = self._create_log_record(original.copy())
        self.filter.filter(record)
        
        assert record.extra_data["users"][0]["password"] == "***"
        assert record.extra_data["users"][1]["password"] == "***"
        assert record.extra_data["users"][0]["name"] == "user1"
        assert record.extra_data["users"][1]["name"] == "user2"
    
    def test_non_sensitive_unchanged(self):
        """测试非敏感字段不变"""
        original = {"item_id": "123", "price": 100, "name": "test"}
        record = self._create_log_record(original.copy())
        self.filter.filter(record)
        
        assert record.extra_data == original


class TestSensitivePatterns:
    """测试敏感字段正则模式"""
    
    def test_all_patterns_compiled(self):
        """测试所有模式都已编译"""
        for name, pattern in SENSITIVE_PATTERNS.items():
            assert isinstance(pattern, type(re.compile(""))), f"Pattern {name} not compiled"
    
    def test_patterns_match_expected(self):
        """测试各模式能匹配预期内容"""
        # Authorization 模式
        assert SENSITIVE_PATTERNS["authorization"].search('auth_token: abc123')
        assert SENSITIVE_PATTERNS["authorization"].search('Authorization: Bearer xyz')
        
        # Password 模式
        assert SENSITIVE_PATTERNS["password"].search('"password": "secret"')
        assert SENSITIVE_PATTERNS["password"].search('password=123456')
        
        # JWT 模式
        jwt_example = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.signature"
        assert SENSITIVE_PATTERNS["jwt"].search(f'jwt={jwt_example}')


class TestLoggingIntegration:
    """集成测试：测试日志记录时脱敏"""
    
    def test_logger_with_filter(self, caplog):
        """测试带过滤器的日志记录"""
        # 创建带敏感数据过滤器的logger
        logger = logging.getLogger("integration_test")
        logger.setLevel(logging.INFO)
        
        # 添加过滤器
        sensitive_filter = SensitiveDataFilter()
        logger.addFilter(sensitive_filter)
        
        # 记录敏感数据
        logger.info('Login attempt with password: secret123')
        
        # 验证输出
        assert "***" in caplog.text
        assert "secret123" not in caplog.text
    
    def test_json_log_sanitization(self, caplog):
        """测试JSON日志脱敏"""
        logger = logging.getLogger("json_test")
        logger.setLevel(logging.INFO)
        logger.addFilter(SensitiveDataFilter())
        
        # 记录JSON
        log_data = {
            "event": "login",
            "username": "testuser",
            "password": "supersecret",
            "token": "abc123"
        }
        logger.info(json.dumps(log_data))
        
        # 验证
        assert "supersecret" not in caplog.text
        assert "abc123" not in caplog.text
        assert "testuser" in caplog.text  # 非敏感字段保留


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
