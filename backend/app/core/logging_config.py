# -*- coding: utf-8 -*-
"""
日志标准化配置
"""
import logging
import sys
from typing import Any, Dict
from datetime import datetime
import json
from logging.handlers import RotatingFileHandler
import os


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
