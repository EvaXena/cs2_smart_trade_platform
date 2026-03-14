# -*- coding: utf-8 -*-
"""
熔断器 - 防止外部服务故障导致级联失败

支持 Redis 持久化，状态变更自动同步到 Redis
"""
import asyncio
import logging
import time
from enum import Enum
from typing import Callable, Any, Optional, Dict
from functools import wraps
from datetime import datetime

import redis.asyncio as redis

logger = logging.getLogger(__name__)

# Redis key 前缀
CIRCUIT_BREAKER_KEY_PREFIX = "circuit_breaker:"


class CircuitState(Enum):
    """熔断器状态"""
    CLOSED = "closed"      # 正常状态，允许请求通过
    OPEN = "open"         # 熔断状态，拒绝请求
    HALF_OPEN = "half_open"  # 半开状态，尝试允许少量请求


def _get_redis_key(name: str) -> str:
    """获取熔断器在 Redis 中的 key"""
    return f"{CIRCUIT_BREAKER_KEY_PREFIX}{name}"


class CircuitBreaker:
    """
    熔断器实现
    
    特性:
    - 三态转换 (CLOSED -> OPEN -> HALF_OPEN -> CLOSED)
    - 可配置失败阈值和恢复超时
    - 失败计数自动重置
    - 支持异步函数
    - Redis 持久化支持（可选）
    """
    
    def __init__(
        self,
        name: str = "default",
        failure_threshold: int = 5,       # 失败次数阈值
        recovery_timeout: int = 30,       # 恢复超时（秒）
        half_open_max_calls: int = 3,     # 半开状态最大尝试次数
        success_threshold: int = 2,       # 半开状态成功次数阈值
        excluded_exceptions: tuple = (),  # 排除的异常类型
        redis_client: Optional[redis.Redis] = None,  # Redis 客户端（可选）
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls
        self.success_threshold = success_threshold
        self.excluded_exceptions = excluded_exceptions
        
        # Redis 客户端
        self._redis_client = redis_client
        self._redis_key = _get_redis_key(name)
        
        # 内存状态
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: Optional[float] = None
        self._last_state_change_time = time.time()
        self._half_open_calls = 0
        self._opened_at: Optional[float] = None  # 记录打开时间
        
        # 尝试从 Redis 恢复状态
        if self._redis_client is not None:
            self._load_from_redis()
    
    def _load_from_redis(self) -> None:
        """从 Redis 加载熔断器状态"""
        try:
            import asyncio
            
            async def _async_load():
                try:
                    data = await self._redis_client.hgetall(self._redis_key)
                    if not data:
                        return False
                    
                    # 恢复状态
                    if "state" in data:
                        self._state = CircuitState(data["state"])
                    if "failure_count" in data:
                        self._failure_count = int(data["failure_count"])
                    if "success_count" in data:
                        self._success_count = int(data["success_count"])
                    if "last_failure_time" in data and data["last_failure_time"]:
                        self._last_failure_time = float(data["last_failure_time"])
                    if "opened_at" in data and data["opened_at"]:
                        self._opened_at = float(data["opened_at"])
                    if "last_state_change_time" in data:
                        self._last_state_change_time = float(data["last_state_change_time"])
                    if "half_open_calls" in data:
                        self._half_open_calls = int(data["half_open_calls"])
                    
                    logger.info(f"Circuit breaker '{self.name}' state loaded from Redis: {self._state.value}")
                    return True
                except Exception as e:
                    logger.warning(f"Failed to load circuit breaker '{self.name}' from Redis: {e}")
                    return False
            
            # 尝试同步运行异步加载
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # 如果在异步环境中，创建任务
                    asyncio.create_task(_async_load())
                else:
                    loop.run_until_complete(_async_load())
            except RuntimeError:
                # 没有事件循环，创建新的
                asyncio.run(_async_load())
        except Exception as e:
            logger.warning(f"Failed to load circuit breaker '{self.name}' from Redis: {e}")
    
    async def _save_to_redis(self) -> None:
        """保存熔断器状态到 Redis（异步）"""
        if self._redis_client is None:
            return
        
        try:
            data = {
                "state": self._state.value,
                "failure_count": str(self._failure_count),
                "success_count": str(self._success_count),
                "last_failure_time": str(self._last_failure_time) if self._last_failure_time else "",
                "opened_at": str(self._opened_at) if self._opened_at else "",
                "last_state_change_time": str(self._last_state_change_time),
                "half_open_calls": str(self._half_open_calls),
            }
            await self._redis_client.hset(self._redis_key, mapping=data)
            # 设置过期时间为 24 小时
            await self._redis_client.expire(self._redis_key, 86400)
        except Exception as e:
            logger.warning(f"Failed to save circuit breaker '{self.name}' to Redis: {e}")
    
    def _save_to_redis_sync(self) -> None:
        """保存熔断器状态到 Redis（同步）"""
        if self._redis_client is None:
            return
        
        try:
            import asyncio
            
            async def _async_save():
                await self._save_to_redis()
            
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(_async_save())
                else:
                    loop.run_until_complete(_async_save())
            except RuntimeError:
                asyncio.run(_async_save())
        except Exception as e:
            logger.warning(f"Failed to save circuit breaker '{self.name}' to Redis: {e}")
    
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
        elif new_state == CircuitState.OPEN:
            # 记录打开时间
            self._opened_at = time.time()
        
        logger.info(
            f"Circuit breaker '{self.name}' state changed: {old_state.value} -> {new_state.value}"
        )
        
        # 同步保存到 Redis
        self._save_to_redis_sync()
    
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
        
        # 同步保存到 Redis
        self._save_to_redis_sync()
    
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
        
        # 同步保存到 Redis
        self._save_to_redis_sync()
    
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
        self._opened_at = None
        self._half_open_calls = 0
        logger.info(f"Circuit breaker '{self.name}' has been reset")
        
        # 同步保存到 Redis
        self._save_to_redis_sync()
        
        # 如果有 Redis 客户端，删除 Redis 中的状态
        if self._redis_client is not None:
            try:
                import asyncio
                async def _async_delete():
                    await self._redis_client.delete(self._redis_key)
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.create_task(_async_delete())
                    else:
                        loop.run_until_complete(_async_delete())
                except RuntimeError:
                    asyncio.run(_async_delete())
            except Exception as e:
                logger.warning(f"Failed to delete circuit breaker '{self.name}' from Redis: {e}")
    
    def get_stats(self) -> dict:
        """获取熔断器统计信息"""
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "last_failure_time": self._last_failure_time,
            "opened_at": self._opened_at,
            "last_state_change_time": self._last_state_change_time,
            "half_open_calls": self._half_open_calls,
        }
    
    def __repr__(self) -> str:
        return f"CircuitBreaker(name='{self.name}', state={self.state.value})"
    
    def set_redis_client(self, redis_client: redis.Redis) -> None:
        """设置 Redis 客户端（可选，用于持久化）"""
        self._redis_client = redis_client
        self._redis_key = _get_redis_key(self.name)
        # 尝试从 Redis 加载状态
        if self._redis_client is not None:
            self._load_from_redis()
    
    def has_redis(self) -> bool:
        """检查是否配置了 Redis 客户端"""
        return self._redis_client is not None


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
