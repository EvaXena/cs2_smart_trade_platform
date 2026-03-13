# -*- coding: utf-8 -*-
"""
限流器 - 支持本地和分布式 Redis 限流
"""
import asyncio
import logging
import time
from typing import Dict, Optional, Tuple
from dataclasses import dataclass
from collections import defaultdict
from enum import Enum

from app.core.config import settings

logger = logging.getLogger(__name__)


class RateLimitBackend(str, Enum):
    """限流后端类型"""
    MEMORY = "memory"
    REDIS = "redis"


@dataclass
class RateLimitConfig:
    """限流配置"""
    requests: int  # 时间窗口内允许的请求数
    window: int    # 时间窗口（秒）
    burst: int     # 突发限制


class TokenBucket:
    """令牌桶算法实现"""
    
    def __init__(self, capacity: int, refill_rate: float):
        self.capacity = capacity  # 桶容量
        self.tokens = float(capacity)  # 当前令牌数
        self.refill_rate = refill_rate  # 每秒补充令牌数
        self.last_refill = time.time()
    
    def _refill(self) -> None:
        """补充令牌"""
        now = time.time()
        elapsed = now - self.last_refill
        self.tokens = min(
            self.capacity,
            self.tokens + elapsed * self.refill_rate
        )
        self.last_refill = now
    
    async def acquire(self, tokens: int = 1) -> bool:
        """
        获取令牌
        
        Args:
            tokens: 需要获取的令牌数
        
        Returns:
            是否成功获取
        """
        self._refill()
        
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        
        # 等待足够令牌
        wait_time = (tokens - self.tokens) / self.refill_rate
        await asyncio.sleep(wait_time)
        
        self._refill()
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        
        return False


class RateLimiter:
    """
    限流器
    
    支持：
    - 滑动窗口限流（本地/Redis分布式）
    - 令牌桶算法（用于突发流量）
    - 从settings读取配置
    - Redis 分布式环境支持
    """
    
    def __init__(self):
        self._buckets: Dict[str, TokenBucket] = {}
        self._window_requests: Dict[str, list] = defaultdict(list)
        self._enabled = settings.RATE_LIMIT_ENABLED
        self._default_requests = settings.RATE_LIMIT_DEFAULT_REQUESTS
        self._default_window = settings.RATE_LIMIT_DEFAULT_WINDOW
        self._default_burst = settings.RATE_LIMIT_DEFAULT_BURST
        
        # Redis 分布式限流支持
        self._redis_limiter: Optional[RedisRateLimiter] = None
        self._use_redis = getattr(settings, 'RATE_LIMIT_USE_REDIS', False) and settings.REDIS_URL
        self._redis_backend: Optional[RateLimitBackend] = None
    
    async def initialize_redis(self) -> bool:
        """初始化 Redis 限流器"""
        if not self._use_redis:
            return False
        
        if self._redis_limiter is None:
            self._redis_limiter = RedisRateLimiter(settings.REDIS_URL)
            connected = await self._redis_limiter.connect()
            if connected:
                self._redis_backend = RateLimitBackend.REDIS
                logger.info("Rate limiter initialized with Redis backend")
                return True
        
        return False
    
    def _get_backend(self) -> RateLimitBackend:
        """获取当前使用的后端"""
        if self._redis_backend:
            return self._redis_backend
        return RateLimitBackend.MEMORY
    
    def _get_config(self, key: str) -> RateLimitConfig:
        """
        获取限流配置（从settings读取）
        
        Args:
            key: 限流标识（通常是endpoint）
        
        Returns:
            限流配置
        """
        # 尝试从settings获取特定配置
        endpoint_config = settings.get_rate_limit_config(key)
        
        if endpoint_config:
            return RateLimitConfig(
                requests=endpoint_config.get("requests", self._default_requests),
                window=endpoint_config.get("window", self._default_window),
                burst=endpoint_config.get("burst", self._default_burst)
            )
        
        # 返回默认配置
        return RateLimitConfig(
            requests=self._default_requests,
            window=self._default_window,
            burst=self._default_burst
        )
    
    async def check_rate_limit(
        self,
        key: str,
        user_id: Optional[int] = None
    ) -> Tuple[bool, Optional[float]]:
        """
        检查是否触发限流
        
        Args:
            key: 限流标识（通常是endpoint）
            user_id: 用户ID（可选）
        
        Returns:
            (是否允许, 剩余时间)
        """
        if not self._enabled:
            return True, None
        
        # 如果有用户ID，加入到key中实现用户级别限流
        if user_id:
            key = f"{key}:{user_id}"
        
        config = self._get_config(key)
        
        # 尝试使用 Redis 分布式限流
        if self._redis_limiter and self._redis_backend == RateLimitBackend.REDIS:
            result = await self._redis_limiter.check_rate_limit(
                key, config.requests, config.window
            )
            if result[0] is not None:
                return result
        
        # 回退到内存限流
        now = time.time()
        
        # 滑动窗口清理
        window_start = now - config.window
        self._window_requests[key] = [
            t for t in self._window_requests[key]
            if t > window_start
        ]
        
        # 检查是否超限
        if len(self._window_requests[key]) >= config.requests:
            # 计算剩余时间
            oldest = min(self._window_requests[key])
            retry_after = oldest + config.window - now
            logger.warning(f"限流触发: key={key}, retry_after={retry_after:.2f}s")
            return False, retry_after
        
        # 记录请求
        self._window_requests[key].append(now)
        
        return True, None
    
    async def wait_if_needed(
        self,
        key: str,
        user_id: Optional[int] = None
    ) -> None:
        """
        如果触发限流则等待
        
        Args:
            key: 限流标识
            user_id: 用户ID
        """
        allowed, retry_after = await self.check_rate_limit(key, user_id)
        
        if not allowed and retry_after:
            logger.info(f"限流等待: key={key}, wait={retry_after:.2f}s")
            await asyncio.sleep(retry_after)
    
    def get_remaining(
        self,
        key: str,
        user_id: Optional[int] = None
    ) -> int:
        """
        获取剩余请求数
        
        Args:
            key: 限流标识
            user_id: 用户ID
        
        Returns:
            剩余请求数
        """
        if not self._enabled:
            return -1
        
        if user_id:
            key = f"{key}:{user_id}"
        
        config = self._get_config(key)
        now = time.time()
        
        # 清理过期记录
        window_start = now - config.window
        self._window_requests[key] = [
            t for t in self._window_requests[key]
            if t > window_start
        ]
        
        return max(0, config.requests - len(self._window_requests[key]))
    
    def reset(self, key: str, user_id: Optional[int] = None) -> None:
        """
        重置限流记录
        
        Args:
            key: 限流标识
            user_id: 用户ID
        """
        if user_id:
            key = f"{key}:{user_id}"
        
        self._window_requests.pop(key, None)
        self._buckets.pop(key, None)


# 全局单例
_rate_limiter_instance: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    """获取限流器单例"""
    global _rate_limiter_instance
    if _rate_limiter_instance is None:
        _rate_limiter_instance = RateLimiter()
    return _rate_limiter_instance


class RedisRateLimiter:
    """
    Redis 分布式限流器
    
    使用 Redis 的有序集合（ZSET）实现滑动窗口限流，
    支持分布式环境下的统一限流计数。
    """
    
    def __init__(self, redis_url: str = None):
        self._redis_url = redis_url or "redis://localhost:6379/0"
        self._redis = None
        self._connected = False
    
    async def connect(self) -> bool:
        """连接 Redis"""
        try:
            import redis.asyncio as redis
            self._redis = redis.from_url(
                self._redis_url,
                encoding="utf-8",
                decode_responses=True
            )
            await self._redis.ping()
            self._connected = True
            logger.info("Redis rate limiter connected")
            return True
        except Exception as e:
            logger.warning(f"Redis rate limiter connection failed: {e}")
            self._connected = False
            return False
    
    async def disconnect(self) -> None:
        """断开 Redis 连接"""
        if self._redis:
            await self._redis.close()
            self._redis = None
            self._connected = False
    
    async def check_rate_limit(
        self,
        key: str,
        requests: int,
        window: int
    ) -> Tuple[bool, Optional[float]]:
        """
        检查是否触发限流（滑动窗口算法）
        
        Args:
            key: 限流标识
            requests: 时间窗口内允许的请求数
            window: 时间窗口（秒）
        
        Returns:
            (是否允许, 剩余时间)
        """
        if not self._connected:
            # 未连接时回退到内存限流
            return None, None
        
        try:
            now = time.time()
            window_start = now - window
            
            # 使用 Redis ZSET 实现滑动窗口
            redis_key = f"ratelimit:{key}"
            
            # 移除窗口外的请求记录
            await self._redis.zremrangebyscore(redis_key, 0, window_start)
            
            # 获取当前请求数
            current_count = await self._redis.zcard(redis_key)
            
            if current_count >= requests:
                # 获取最旧的请求时间，计算剩余等待时间
                oldest = await self._redis.zrange(redis_key, 0, 0, withscores=True)
                if oldest:
                    oldest_timestamp = oldest[0][1]
                    retry_after = oldest_timestamp + window - now
                    logger.warning(f"限流触发: key={key}, retry_after={retry_after:.2f}s")
                    return False, retry_after
                return False, window
            
            # 记录当前请求
            await self._redis.zadd(redis_key, {f"{now}": now})
            # 设置过期时间，自动清理过期记录
            await self._redis.expire(redis_key, window + 1)
            
            return True, None
            
        except Exception as e:
            logger.error(f"Redis rate limit check failed: {e}")
            return None, None
    
    async def get_remaining(
        self,
        key: str,
        requests: int,
        window: int
    ) -> int:
        """获取剩余请求数"""
        if not self._connected:
            return -1
        
        try:
            now = time.time()
            window_start = now - window
            
            redis_key = f"ratelimit:{key}"
            await self._redis.zremrangebyscore(redis_key, 0, window_start)
            current_count = await self._redis.zcard(redis_key)
            
            return max(0, requests - current_count)
        except Exception as e:
            logger.error(f"Redis get remaining failed: {e}")
            return -1
    
    async def reset(self, key: str) -> None:
        """重置限流记录"""
        if not self._connected:
            return
        
        try:
            redis_key = f"ratelimit:{key}"
            await self._redis.delete(redis_key)
        except Exception as e:
            logger.error(f"Redis rate limit reset failed: {e}")
