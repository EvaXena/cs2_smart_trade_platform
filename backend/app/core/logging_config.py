# -*- coding: utf-8 -*-
"""
日志标准化配置
支持日志脱敏功能
"""
import logging
import sys
import re
from typing import Any, Dict
from datetime import datetime
import json
from logging.handlers import RotatingFileHandler
import os


# 敏感字段模式
SENSITIVE_PATTERNS = {
    # HTTP头中的认证信息
    "authorization": re.compile(r'(authorization|auth_token|access_token|refresh_token)["\s:=]+([^\s",}]+)', re.IGNORECASE),
    # Cookie
    "cookie": re.compile(r'(cookie["\s:=]+[^\s;]+)', re.IGNORECASE),
    # 密码字段
    "password": re.compile(r'("?password"?["\s:=]+)[^\s,}"{]+', re.IGNORECASE),
    # Steam cookie
    "steam_cookie": re.compile(r'(steamcookie|steam_session)["\s:=]+[^\s,}"{]+', re.IGNORECASE),
    # Buff cookie
    "buff_cookie": re.compile(r'(buffcookie|buff_session)["\s:=]+[^\s,}"{]+', re.IGNORECASE),
    # MaFile
    "mafile": re.compile(r'(mafile|steam_mafile)["\s:=]+[^\s,}"{]+', re.IGNORECASE),
    # Token
    "token": re.compile(r'("?token"?["\s:=]+)[^\s,}"{]+', re.IGNORECASE),
    # JWT
    "jwt": re.compile(r'(jwt|bearer)["\s:=]+\.eyJ[^\s,}"{]+', re.IGNORECASE),
    # API Key
    "api_key": re.compile(r'(api[_-]?key|apikey)["\s:=]+[^\s,}"{]+', re.IGNORECASE),
    # Steam API Key
    "steam_api": re.compile(r'(steam[_-]?api[_-]?key)["\s:=]+[^\s,}"{]+', re.IGNORECASE),
    # 邮箱(可选脱敏)
    "email": re.compile(r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})'),
}

# 需要完全屏蔽的字段(不显示任何内容)
BLOCKED_FIELDS = {"password", "steam_cookie", "buff_cookie", "mafile", "token", "api_key", "steam_api_key", "secret"}


class SensitiveDataFilter(logging.Filter):
    """
    敏感数据过滤过滤器
    自动检测并脱敏日志中的敏感信息
    """
    
    def __init__(self):
        super().__init__()
        self._sensitive_fields = BLOCKED_FIELDS
    
    def filter(self, record: logging.LogRecord) -> bool:
        # 获取原始消息
        message = record.getMessage()
        
        # 脱敏处理
        sanitized_message = self._sanitize(message)
        
        # 如果消息被修改，更新record
        if sanitized_message != message:
            # 创建一个新的消息
            record.msg = sanitized_message
            record.args = ()  # 清除原始参数
        
        return True
    
    def _sanitize(self, text: str) -> str:
        """脱敏文本"""
        if not text:
            return text
        
        result = text
        
        # 1. 屏蔽特定字段
        for field in self._sensitive_fields:
            # 匹配 "field": "value" 或 "field": "value"
            pattern = re.compile(rf'("{field}"["\s:=]+)[^\s,}}"{{]+', re.IGNORECASE)
            result = pattern.sub(rf'\1"***"', result)
        
        # 2. 替换匹配到的敏感模式
        for name, pattern in SENSITIVE_PATTERNS.items():
            if name in self._sensitive_fields:
                continue  # 已在上一步处理
            
            # 替换为脱敏版本
            def replace_func(match):
                prefix = match.group(1)
                return prefix + "***"
            
            result = pattern.sub(replace_func, result)
        
        # 3. 通用token替换(长字符串，看起来像token)
        # 替换40+字符的十六进制字符串(Steam ID等)
        long_hex_pattern = re.compile(r'\b[0-9a-f]{40,}\b')
        result = long_hex_pattern.sub("***", result)
        
        # 替换看起来像JWT的字符串
        jwt_pattern = re.compile(r'eyJ[0-9A-Za-z\-_]+\.eyJ[0-9A-Za-z\-_]+\.[0-9A-Za-z\-_]+')
        result = jwt_pattern.sub("***", result)
        
        return result


class SensitiveFieldFilter(logging.Filter):
    """
    特定字段过滤 - 用于结构化日志
    """
    
    def __init__(self, fields_to_mask: set = None):
        super().__init__()
        self.fields_to_mask = fields_to_mask or BLOCKED_FIELDS
    
    def filter(self, record: logging.LogRecord) -> bool:
        # 处理record的__dict__
        if hasattr(record, 'extra_data') and isinstance(record.extra_data, dict):
            record.extra_data = self._mask_dict(record.extra_data)
        
        return True
    
    def _mask_dict(self, data: dict) -> dict:
        """递归处理字典中的敏感字段"""
        if not isinstance(data, dict):
            return data
        
        masked = {}
        for key, value in data.items():
            key_lower = key.lower()
            
            if key_lower in self.fields_to_mask:
                masked[key] = "***"
            elif isinstance(value, dict):
                masked[key] = self._mask_dict(value)
            elif isinstance(value, list):
                masked[key] = [
                    self._mask_dict(item) if isinstance(item, dict) else "***" 
                    if self._is_sensitive(key_lower) else item
                    for item in value
                ]
            else:
                masked[key] = value
        
        return masked
    
    def _is_sensitive(self, key: str) -> bool:
        """判断字段是否敏感"""
        return key in self.fields_to_mask


class StandardizedFormatter(logging.Formatter):
    """
    标准化日志格式化器
    
    输出格式:
    {
        "timestamp": "2024-01-01T12:00:00.000Z",
        "level": "INFO",
        "logger": "app.services.cache",
        "message": "Cache hit for key: item_123",
        "context": {...},
        "trace_id": "abc123"
    }
    """
    
    def __init__(self, include_context: bool = True):
        super().__init__()
        self.include_context = include_context
    
    def format(self, record: logging.LogRecord) -> str:
        # 构建标准化的日志结构
        log_entry: Dict[str, Any] = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        
        # 添加上下文信息（如果存在）
        if self.include_context:
            context = getattr(record, "context", None)
            if context:
                log_entry["context"] = context
            
            trace_id = getattr(record, "trace_id", None)
            if trace_id:
                log_entry["trace_id"] = trace_id
        
        # 添加异常信息
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        
        # 添加额外字段
        if hasattr(record, "extra_data"):
            log_entry["extra"] = record.extra_data
        
        return json.dumps(log_entry, ensure_ascii=False)


class ContextFilter(logging.Filter):
    """
    上下文过滤器 - 为日志添加上下文信息
    """
    
    def __init__(self, context: Dict[str, Any] = None):
        super().__init__()
        self._context = context or {}
    
    def filter(self, record: logging.LogRecord) -> bool:
        # 设置上下文
        for key, value in self._context.items():
            setattr(record, key, value)
        return True


def setup_logging(
    log_level: str = "INFO",
    log_file: str = None,
    enable_standardized: bool = True,
    include_context: bool = True,
    enable_rotation: bool = True,
    max_bytes: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5
) -> None:
    """
    配置日志系统
    
    Args:
        log_level: 日志级别 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: 日志文件路径 (可选)
        enable_standardized: 是否启用标准化格式
        include_context: 是否包含上下文信息
        enable_rotation: 是否启用日志轮转
        max_bytes: 单个日志文件最大字节数
        backup_count: 保留的备份文件数量
    """
    # 获取根日志记录器
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))
    
    # 清除现有的处理器
    root_logger.handlers.clear()
    
    # 控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, log_level.upper()))
    
    if enable_standardized:
        # 标准化格式
        console_handler.setFormatter(StandardizedFormatter(include_context=include_context))
    else:
        # 标准格式
        console_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"
            )
        )
    
    root_logger.addHandler(console_handler)
    
    # 添加敏感数据过滤器
    sensitive_filter = SensitiveDataFilter()
    console_handler.addFilter(sensitive_filter)
    root_logger.addFilter(sensitive_filter)
    
    # 文件处理器 - 支持日志轮转 (如果指定)
    if log_file:
        # 确保日志目录存在
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)
        
        if enable_rotation:
            # 使用 RotatingFileHandler 进行日志轮转
            file_handler = RotatingFileHandler(
                log_file,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding="utf-8"
            )
        else:
            # 使用普通 FileHandler
            file_handler = logging.FileHandler(log_file, encoding="utf-8")
        
        file_handler.setLevel(getattr(logging, log_level.upper()))
        file_handler.setFormatter(StandardizedFormatter(include_context=include_context))
        root_logger.addHandler(file_handler)
    
    # 设置第三方库的日志级别
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("fastapi").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def get_logger(
    name: str,
    context: Dict[str, Any] = None,
    trace_id: str = None
) -> logging.Logger:
    """
    获取带有上下文信息的日志记录器
    
    Args:
        name: 日志记录器名称
        context: 上下文信息字典
        trace_id: 追踪ID
    
    Returns:
        配置好的日志记录器
    """
    logger = logging.getLogger(name)
    
    # 添加上下文过滤器
    if context:
        context_filter = ContextFilter(context)
        logger.addFilter(context_filter)
    
    return logger


# 便捷函数：记录带上下文的日志
def log_with_context(
    logger: logging.Logger,
    level: str,
    message: str,
    context: Dict[str, Any] = None,
    trace_id: str = None,
    extra_data: Dict[str, Any] = None
) -> None:
    """
    记录带上下文的日志
    
    Args:
        logger: 日志记录器
        level: 日志级别
        message: 日志消息
        context: 上下文信息
        trace_id: 追踪ID
        extra_data: 额外数据
    """
    log_func = getattr(logger, level.lower())
    
    # 创建日志记录并添加额外属性
    extra = {}
    if context:
        extra["context"] = context
    if trace_id:
        extra["trace_id"] = trace_id
    if extra_data:
        extra["extra_data"] = extra_data
    
    if extra:
        # 使用 logger.makeRecord 来添加额外属性
        record = logger.makeRecord(
            logger.name,
            getattr(logging, level.upper()),
            "",
            0,
            message,
            (),
            None,
            extra=extra
        )
        log_func(record)
    else:
        log_func(message)


# 初始化默认日志配置
def init_logging(
    log_file: str = "logs/app.log",
    log_level: str = "INFO",
    enable_rotation: bool = True
) -> None:
    """
    初始化默认日志配置
    
    Args:
        log_file: 日志文件路径
        log_level: 日志级别
        enable_rotation: 是否启用日志轮转
    """
    setup_logging(
        log_level=log_level,
        log_file=log_file,
        enable_standardized=True,
        include_context=True,
        enable_rotation=enable_rotation,
        max_bytes=10 * 1024 * 1024,  # 10MB
        backup_count=5
    )
