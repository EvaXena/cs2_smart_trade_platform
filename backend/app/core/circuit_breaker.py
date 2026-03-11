# -*- coding: utf-8 -*-
"""
熔断器 - 防止外部服务故障导致级联失败
"""
import asyncio
import logging
import time
from enum import Enum
from typing import Callable, Any, Optional, Dict
from functools import wraps
from datetime import datetime

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """熔断器状态"""
    CLOSED = "closed"      # 正常状态，允许请求通过
    OPEN = "open"         # 熔断状态，拒绝请求
    HALF_OPEN = "half_open"  # 半开状态，尝试允许少量请求


class CircuitBreaker:
    """
    熔断器实现
    
    特性:
    - 三态转换 (CLOSED -> OPEN -> HALF_OPEN -> CLOSED)
    - 可配置失败阈值和恢复超时
    - 失败计数自动重置
    - 支持异步函数
    """
    
    def __init__(
        self,
        name: str = "default",
        failure_threshold: int = 5,       # 失败次数阈值
        recovery_timeout: int = 30,       # 恢复超时（秒）
        half_open_max_calls: int = 3,     # 半开状态最大尝试次数
        success_threshold: int = 2,       # 半开状态成功次数阈值
        excluded_exceptions: tuple = (),  # 排除的异常类型
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls
        self.success_threshold = success_threshold
        self.excluded_exceptions = excluded_exceptions
        
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: Optional[float] = None
        self._last_state_change_time = time.time()
        self._half_open_calls = 0
    
    @property
    def state(self) -> CircuitState:
        """获取当前状态"""
        self._check_state_transition()
        return self._state
    
    def _check_state_transition(self) -> None:
        """检查状态转换"""
        if self._state == CircuitState.OPEN:
            # 检查是否应该转换到 HALF_OPEN
            if self._last_failure_time is not None:
                elapsed = time.time() - self._last_failure_time
                if elapsed >= self.recovery_timeout:
                    self._transition_to(CircuitState.HALF_OPEN)
    
    def _transition_to(self, new_state: CircuitState) -> None:
        """转换到新状态"""
        old_state = self._state
        self._state = new_state
        self._last_state_change_time = time.time()
        
        if new_state == CircuitState.HALF_OPEN:
            self._half_open_calls = 0
            self._success_count = 0
        
        logger.info(
            f"Circuit breaker '{self.name}' state changed: {old_state.value} -> {new_state.value}"
        )
    
    def _record_success(self) -> None:
        """记录成功"""
        if self._state == CircuitState.HALF_OPEN:
            self._success_count += 1
            self._half_open_calls += 1
            
            if self._success_count >= self.success_threshold:
                self._transition_to(CircuitState.CLOSED)
                self._failure_count = 0
        elif self._state == CircuitState.CLOSED:
            # 成功时重置失败计数
            self._failure_count = 0
    
    def _record_failure(self) -> None:
        """记录失败"""
        self._failure_count += 1
        self._last_failure_time = time.time()
        
        if self._state == CircuitState.HALF_OPEN:
            self._half_open_calls += 1
            if self._half_open_calls >= self.half_open_max_calls:
                self._transition_to(CircuitState.OPEN)
        elif self._state == CircuitState.CLOSED:
            if self._failure_count >= self.failure_threshold:
                self._transition_to(CircuitState.OPEN)
    
    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        通过熔断器调用函数
        
        Args:
            func: 要调用的异步函数
            *args, **kwargs: 函数参数
            
        Returns:
            函数返回值
            
        Raises:
            CircuitBreakerOpen: 当熔断器处于 OPEN 状态时
        """
        if self.state == CircuitState.OPEN:
            raise CircuitBreakerOpen(
                f"Circuit breaker '{self.name}' is OPEN, request rejected"
            )
        
        try:
            result = await func(*args, **kwargs)
            self._record_success()
            return result
        except self.excluded_exceptions:
            # 排除的异常不计入失败
            raise
        except Exception as e:
            self._record_failure()
            raise
    
    def _sync_call(self, func: Callable, *args, **kwargs) -> Any:
        """
        同步调用（用于同步函数）
        """
        if self.state == CircuitState.OPEN:
            raise CircuitBreakerOpen(
                f"Circuit breaker '{self.name}' is OPEN, request rejected"
            )
        
        try:
            result = func(*args, **kwargs)
            # 同步函数不自动记录成功/失败，由外部处理
            return result
        except self.excluded_exceptions:
            raise
        except Exception as e:
            self._record_failure()
            raise
    
    def reset(self) -> None:
        """手动重置熔断器"""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = None
        self._half_open_calls = 0
        logger.info(f"Circuit breaker '{self.name}' has been reset")
    
    def get_stats(self) -> dict:
        """获取熔断器统计信息"""
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "last_failure_time": self._last_failure_time,
            "last_state_change_time": self._last_state_change_time,
            "half_open_calls": self._half_open_calls,
        }
    
    def __repr__(self) -> str:
        return f"CircuitBreaker(name='{self.name}', state={self.state.value})"


class CircuitBreakerOpen(Exception):
    """熔断器开启异常"""
    pass


class CircuitBreakerDecorator:
    """熔断器装饰器"""
    
    _breakers: Dict[str, CircuitBreaker] = {}
    
    @classmethod
    def get_breaker(cls, name: str = "default", **kwargs) -> CircuitBreaker:
        """获取或创建命名熔断器"""
        if name not in cls._breakers:
            cls._breakers[name] = CircuitBreaker(name=name, **kwargs)
        return cls._breakers[name]
    
    @classmethod
    def reset_all(cls) -> None:
        """重置所有熔断器"""
        for breaker in cls._breakers.values():
            breaker.reset()
        cls._breakers.clear()
    
    @classmethod
    def get_all_stats(cls) -> dict:
        """获取所有熔断器状态"""
        return {name: breaker.get_stats() for name, breaker in cls._breakers.items()}


def circuit_breaker(
    name: str = "default",
    failure_threshold: int = 5,
    recovery_timeout: int = 30,
    **kwargs
):
    """
    熔断器装饰器
    
    Usage:
        @circuit_breaker(name="steam_api", failure_threshold=3)
        async def call_steam_api():
            ...
    """
    def decorator(func: Callable):
        breaker = CircuitBreakerDecorator.get_breaker(
            name=name,
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
            **kwargs
        )
        
        if asyncio.iscoroutinefunction(func):
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                return await breaker.call(func, *args, **kwargs)
            return async_wrapper
        else:
            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                return breaker._sync_call(func, *args, **kwargs)
            return sync_wrapper
    
    return decorator


# 预定义的常用熔断器
steam_circuit_breaker = CircuitBreaker(
    name="steam",
    failure_threshold=5,
    recovery_timeout=30,
    success_threshold=2,
)

buff_circuit_breaker = CircuitBreaker(
    name="buff",
    failure_threshold=5,
    recovery_timeout=30,
    success_threshold=2,
)

market_circuit_breaker = CircuitBreaker(
    name="market",
    failure_threshold=10,
    recovery_timeout=60,
    success_threshold=3,
)
