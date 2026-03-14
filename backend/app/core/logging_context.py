# -*- coding: utf-8 -*-
"""
日志上下文管理
使用 contextvars 实现异步任务日志上下文传递
"""
import contextvars
from typing import Optional, Dict, Any
from dataclasses import dataclass, field
import logging

# 定义上下文变量
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar('request_id', default='')
user_id_var: contextvars.ContextVar[Optional[int]] = contextvars.ContextVar('user_id', default=None)
trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar('trace_id', default='')
extra_context_var: contextvars.ContextVar[Dict[str, Any]] = contextvars.ContextVar('extra_context', default={})


@dataclass
class LogContext:
    """日志上下文"""
    request_id: str = ''
    user_id: Optional[int] = None
    trace_id: str = ''
    extra: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        result = {}
        if self.request_id:
            result['request_id'] = self.request_id
        if self.user_id is not None:
            result['user_id'] = self.user_id
        if self.trace_id:
            result['trace_id'] = self.trace_id
        if self.extra:
            result.update(self.extra)
        return result


class LoggingContextManager:
    """日志上下文管理器"""
    
    @staticmethod
    def set_request_id(request_id: str) -> None:
        """设置请求ID"""
        request_id_var.set(request_id)
    
    @staticmethod
    def get_request_id() -> str:
        """获取请求ID"""
        return request_id_var.get()
    
    @staticmethod
    def set_user_id(user_id: int) -> None:
        """设置用户ID"""
        user_id_var.set(user_id)
    
    @staticmethod
    def get_user_id() -> Optional[int]:
        """获取用户ID"""
        return user_id_var.get()
    
    @staticmethod
    def set_trace_id(trace_id: str) -> None:
        """设置追踪ID"""
        trace_id_var.set(trace_id)
    
    @staticmethod
    def get_trace_id() -> str:
        """获取追踪ID"""
        return trace_id_var.get()
    
    @staticmethod
    def set_extra(key: str, value: Any) -> None:
        """设置额外上下文"""
        extra = extra_context_var.get().copy()
        extra[key] = value
        extra_context_var.set(extra)
    
    @staticmethod
    def get_extra() -> Dict[str, Any]:
        """获取额外上下文"""
        return extra_context_var.get().copy()
    
    @staticmethod
    def clear() -> None:
        """清除上下文"""
        request_id_var.set('')
        user_id_var.set(None)
        trace_id_var.set('')
        extra_context_var.set({})
    
    @staticmethod
    def get_context() -> LogContext:
        """获取完整上下文"""
        return LogContext(
            request_id=request_id_var.get(),
            user_id=user_id_var.get(),
            trace_id=trace_id_var.get(),
            extra=extra_context_var.get().copy()
        )
    
    @staticmethod
    def copy_context() -> contextvars.Context:
        """复制当前上下文（用于异步任务）"""
        return contextvars.copy_context()


class ContextLogger:
    """带上下文的日志记录器"""
    
    def __init__(self, name: str):
        self._logger = logging.getLogger(name)
    
    def _format_message(self, msg: str) -> str:
        """格式化消息，添加上下文"""
        context = LoggingContextManager.get_context()
        ctx_str = context.to_dict()
        if ctx_str:
            ctx_parts = " | ".join(f"{k}={v}" for k, v in ctx_str.items())
            return f"{msg} | {ctx_parts}"
        return msg
    
    def debug(self, msg: str, *args, **kwargs):
        self._logger.debug(self._format_message(msg), *args, **kwargs)
    
    def info(self, msg: str, *args, **kwargs):
        self._logger.info(self._format_message(msg), *args, **kwargs)
    
    def warning(self, msg: str, *args, **kwargs):
        self._logger.warning(self._format_message(msg), *args, **kwargs)
    
    def error(self, msg: str, *args, **kwargs):
        self._logger.error(self._format_message(msg), *args, **kwargs)
    
    def critical(self, msg: str, *args, **kwargs):
        self._logger.critical(self._format_message(msg), *args, **kwargs)


def create_context_aware_task(coro, *, name: str = None):
    """
    创建带上下文的异步任务
    
    Args:
        coro: 协程函数
        name: 任务名称
        
    Returns:
        asyncio.Task
    """
    import asyncio
    
    # 复制当前上下文
    ctx = contextvars.copy_context()
    
    # 在任务的上下文中运行协程
    wrapped_coro = ctx.run(coro)
    
    return asyncio.create_task(wrapped_coro, name=name)


# 全局实例
logging_context = LoggingContextManager()
