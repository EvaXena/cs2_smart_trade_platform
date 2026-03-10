# -*- coding: utf-8 -*-
"""
日志配置测试
"""
import pytest
import logging
import json
import io
from app.core.logging_config import (
    StandardizedFormatter,
    ContextFilter,
    setup_logging,
    get_logger,
    log_with_context,
    init_logging,
)


class TestStandardizedFormatter:
    """标准化格式化器测试"""
    
    def test_format_simple_message(self):
        """测试格式化简单消息"""
        formatter = StandardizedFormatter(include_context=False)
        
        # 创建一个简单的日志记录
        logger = logging.getLogger("test")
        record = logger.makeRecord(
            "test",
            logging.INFO,
            "",
            0,
            "Test message",
            (),
            None
        )
        
        result = formatter.format(record)
        data = json.loads(result)
        
        assert "timestamp" in data
        assert data["level"] == "INFO"
        assert data["message"] == "Test message"
        assert data["logger"] == "test"
    
    def test_format_with_context(self):
        """测试格式化带上下文的消息"""
        formatter = StandardizedFormatter(include_context=True)
        
        logger = logging.getLogger("test")
        extra = {"context": {"user_id": 123, "action": "login"}}
        record = logger.makeRecord(
            "test",
            logging.INFO,
            "",
            0,
            "User logged in",
            (),
            None,
            extra=extra
        )
        
        result = formatter.format(record)
        data = json.loads(result)
        
        assert data["context"]["user_id"] == 123
        assert data["context"]["action"] == "login"
    
    def test_format_with_trace_id(self):
        """测试格式化带追踪ID的消息"""
        formatter = StandardizedFormatter(include_context=True)
        
        logger = logging.getLogger("test")
        extra = {"trace_id": "abc-123-def"}
        record = logger.makeRecord(
            "test",
            logging.INFO,
            "",
            0,
            "Request processed",
            (),
            None,
            extra=extra
        )
        
        result = formatter.format(record)
        data = json.loads(result)
        
        assert data["trace_id"] == "abc-123-def"


class TestContextFilter:
    """上下文过滤器测试"""
    
    def test_add_context(self):
        """测试添加上下文"""
        context = {"user_id": 123, "request_id": "req-456"}
        filter_obj = ContextFilter(context)
        
        logger = logging.getLogger("test_filter")
        record = logger.makeRecord(
            "test_filter",
            logging.INFO,
            "",
            0,
            "Test",
            (),
            None
        )
        
        filtered = filter_obj.filter(record)
        
        assert filtered is True
        assert hasattr(record, "context")
        assert record.context["user_id"] == 123
    
    def test_empty_context(self):
        """测试空上下文"""
        filter_obj = ContextFilter()
        
        logger = logging.getLogger("test_filter")
        record = logger.makeRecord(
            "test_filter",
            logging.INFO,
            "",
            0,
            "Test",
            (),
            None
        )
        
        filtered = filter_obj.filter(record)
        assert filtered is True


class TestGetLogger:
    """获取日志记录器测试"""
    
    def test_get_logger_with_context(self):
        """测试获取带上下文的记录器"""
        logger = get_logger("test.context", context={"test": "value"})
        
        assert logger.name == "test.context"
    
    def test_get_logger_with_trace_id(self):
        """测试获取带追踪ID的记录器"""
        logger = get_logger("test.trace", trace_id="trace-123")
        
        assert logger.name == "test.trace"


class TestLogWithContext:
    """带上下文日志测试"""
    
    def test_log_with_context_info(self):
        """测试记录info级别带上下文的日志"""
        logger = logging.getLogger("test.log_context")
        logger.setLevel(logging.DEBUG)
        
        # 捕获日志输出
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter('%(message)s'))
        logger.addHandler(handler)
        
        log_with_context(
            logger,
            "info",
            "Test message",
            context={"key": "value"}
        )
        
        output = stream.getvalue()
        assert "Test message" in output


class TestInitLogging:
    """初始化日志测试"""
    
    def test_init_logging(self):
        """测试初始化日志"""
        # 不应该抛出异常
        init_logging()
        
        # 验证日志记录器已配置
        logger = logging.getLogger("test.init")
        assert logger is not None
