# -*- coding: utf-8 -*-
"""
速率限制中间件 - API 限流
支持分布式环境（Redis）
"""
import time
import json
import logging
import threading
from typing import Dict, Optional, Tuple
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import settings
from app.core.redis_manager import get_redis

logger = logging.getLogger(__name__)


class MemoryRateLimiter:
    """内存限流器（Redis 故障时的降级方案）"""
    
    def __init__(self):
        self._data: Dict[str, list] = {}
        self._lock = threading.Lock()
    
    def _clean_old_entries(self, key: str, window: int):
        """清理过期记录"""
        current_time = time.time()
        if key in self._data:
            self._data[key] = [t for t in self._data[key] if current_time - t < window]
    
    def check_and_record(self, key: str, limit: int, window: int) -> Tuple[bool, Optional[Dict]]:
        """检查限流并记录请求
        
        Returns:
            (是否允许, 超限信息)
        """
        with self._lock:
            self._clean_old_entries(key, window)
            
            request_count = len(self._data.get(key, []))
            
            if request_count >= limit:
                oldest = min(self._data.get(key, [current_time])) if self._data.get(key) else time.time()
                retry_after = int(window - (time.time() - oldest)) + 1
                
                logger.warning(f"Memory rate limit exceeded for {key}: {request_count}/{limit}")
                
                return False, {
                    "requests": request_count,
                    "limit": limit,
                    "window": window,
                    "retry_after": retry_after,
                }
            
            # 记录请求
            if key not in self._data:
                self._data[key] = []
            self._data[key].append(time.time())
            
            return True, None


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    速率限制中间件（分布式 Redis 版本）
    
    支持按端点配置不同的限流规则:
    - 登录端点: 严格限制（防暴力破解）
    - API端点: 一般限制
    - 监控端点: 宽松限制
    
    限流策略:
    - 基于 IP + 端点的双重限制
    - 滑动窗口算法
    - 可配置 burst（突发）限制
    - 支持分布式多进程（Redis 存储）
    """
    
    def __init__(self, app, config: Optional[Dict] = None):
        super().__init__(app)
        # 默认限流配置
        self.default_config = {
            "requests": 60,      # 默认每分钟60次
            "window": 60,        # 窗口60秒
            "burst": 10,         # 突发限制10次
        }
        # 端点特定配置
        self.endpoint_config = config or {
            "/api/v1/auth/login": {
                "requests": 5,
                "window": 60,
                "burst": 3,
                "description": "登录端点严格限制"
            },
            "/api/v1/auth/register": {
                "requests": 3,
                "window": 300,
                "burst": 1,
                "description": "注册端点更严格限制"
            },
            "/api/v1/orders": {
                "requests": 120,
                "window": 60,
                "burst": 20,
                "description": "订单端点中等限制"
            },
            "/api/v1/monitoring": {
                "requests": 300,
                "window": 60,
                "burst": 50,
                "description": "监控端点宽松限制"
            },
            "/api/v1/bots": {
                "requests": 100,
                "window": 60,
                "burst": 15,
                "description": "机器人端点中等限制"
            },
        }
        
        # Redis 客户端
        self._redis_prefix = "rate_limit:"
        
        # 内存限流器（Redis 故障时的降级方案）
        self._memory_limiter = MemoryRateLimiter()
    
    async def _get_redis(self):
        """获取 Redis 连接（使用统一管理器）"""
        return await get_redis()
    
    async def _close_redis(self):
        """关闭 Redis 连接（由全局管理器统一管理）"""
        pass  # 不再单独关闭，由 redis_manager 统一管理
    
    def _get_client_ip(self, request: Request) -> str:
        """获取客户端IP"""
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"
    
    def _get_rate_limit_key(self, request: Request, endpoint: str) -> str:
        """生成限流key"""
        client_ip = self._get_client_ip(request)
        return f"{self._redis_prefix}{client_ip}:{endpoint}"
    
    def _get_endpoint_config(self, path: str) -> Dict:
        """获取端点限流配置"""
        # 精确匹配
        if path in self.endpoint_config:
            return self.endpoint_config[path]
        
        # 前缀匹配
        for endpoint, config in self.endpoint_config.items():
            if path.startswith(endpoint):
                return config
        
        return self.default_config
    
    async def _check_rate_limit(self, key: str, config: Dict) -> Tuple[bool, Optional[Dict]]:
        """
        检查是否超过限流（Redis 分布式版本）
        
        返回: (是否允许, 超限信息)
        """
        try:
            r = await self._get_redis()
            current_time = time.time()
            window = config["window"]
            requests_limit = config["requests"]
            burst_limit = config.get("burst", requests_limit)
            
            # 使用 Redis Sorted Set 实现滑动窗口
            # 添加当前请求
            score = current_time
            await r.zadd(key, {str(score): score})
            
            # 清理过期记录
            min_score = current_time - window
            await r.zremrangebyscore(key, "-inf", str(min_score))
            
            # 获取请求数量
            request_count = await r.zcard(key)
            
            # 设置 TTL
            await r.expire(key, window + 1)
            
            # 检查是否超过限制
            if request_count >= requests_limit:
                # 计算剩余时间
                oldest = await r.zrange(key, 0, 0, withscores=True)
                if oldest:
                    oldest_time = oldest[0][1]
                    retry_after = int(window - (current_time - oldest_time)) + 1
                else:
                    retry_after = window
                
                logger.warning(f"Rate limit exceeded for {key}: {request_count}/{requests_limit}")
                
                return False, {
                    "requests": request_count,
                    "limit": requests_limit,
                    "window": window,
                    "retry_after": retry_after,
                }
            
            # 检查突发限制
            if request_count >= burst_limit:
                logger.info(f"Rate limit warning for {key}: {request_count}/{burst_limit}")
            
            return True, None
            
        except Exception as e:
            logger.error(f"Redis rate limit error: {e}")
            # Redis 故障时使用内存限流作为降级方案
            logger.warning(f"Using memory fallback rate limiter for {key}")
            return self._memory_limiter.check_and_record(
                key, 
                config["requests"], 
                config["window"]
            )
    
    async def dispatch(self, request: Request, call_next):
        # 只对 API 端点进行限流
        path = request.url.path
        
        if not path.startswith("/api/"):
            return await call_next(request)
        
        # 获取配置
        config = self._get_endpoint_config(path)
        key = self._get_rate_limit_key(request, path)
        
        # 检查限流
        allowed, info = await self._check_rate_limit(key, config)
        
        if not allowed:
            response = JSONResponse(
                status_code=429,
                content={
                    "detail": "请求过于频繁，请稍后重试",
                    "error": "rate_limit_exceeded",
                    "retry_after": info["retry_after"],
                }
            )
            response.headers["X-RateLimit-Limit"] = str(info["limit"])
            response.headers["X-RateLimit-Remaining"] = "0"
            response.headers["X-RateLimit-Reset"] = str(int(time.time()) + info["retry_after"])
            response.headers["Retry-After"] = str(info["retry_after"])
            return response
        
        # 处理请求
        response = await call_next(request)
        
        # 添加限流头（从 Redis 获取当前计数）
        try:
            r = await self._get_redis()
            current_time = time.time()
            min_score = current_time - config["window"]
            await r.zremrangebyscore(key, "-inf", str(min_score))
            remaining = config["requests"] - await r.zcard(key)
            response.headers["X-RateLimit-Limit"] = str(config["requests"])
            response.headers["X-RateLimit-Remaining"] = str(max(0, remaining))
            response.headers["X-RateLimit-Reset"] = str(int(current_time) + config["window"])
        except Exception as e:
            logger.error(f"Failed to set rate limit headers: {e}")
        
        return response


class ConnectionLimitMiddleware(BaseHTTPMiddleware):
    """
    并发连接数限制中间件
    
    使用Redis Set存储活跃连接，限制最大并发连接数
    防止DDoS攻击和资源耗尽
    """
    
    # 默认最大并发连接数
    DEFAULT_MAX_CONNECTIONS = 100
    
    # Redis key前缀
    _REDIS_KEY_PREFIX = "connection_limit:"
    _ACTIVE_CONNECTIONS_KEY = "active_connections"
    
    def __init__(self, app, max_connections: int = DEFAULT_MAX_CONNECTIONS):
        super().__init__(app)
        self.max_connections = max_connections
        
        # 内存降级方案
        self._memory_connections: set = set()
        self._memory_lock = threading.Lock()
    
    async def _get_redis(self):
        """获取Redis连接"""
        return await get_redis()
    
    def _get_client_id(self, request: Request) -> str:
        """获取客户端唯一标识"""
        # 优先使用X-Forwarded-For
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            client_ip = forwarded.split(",")[0].strip()
        else:
            client_ip = request.client.host if request.client else "unknown"
        
        # 如果有用户ID，添加用户标识
        # 从请求属性中获取（需要先经过认证中间件设置）
        user_id = getattr(request.state, "user_id", None)
        if user_id:
            return f"user:{user_id}:{client_ip}"
        
        return f"ip:{client_ip}"
    
    async def _check_connection_limit(self, client_id: str) -> Tuple[bool, Optional[Dict]]:
        """
        检查并记录连接
        
        Returns:
            (是否允许, 限制信息)
        """
        try:
            r = await self._get_redis()
            key = f"{self._REDIS_KEY_PREFIX}{self._ACTIVE_CONNECTIONS_KEY}"
            
            # 尝试添加连接
            added = await r.sadd(key, client_id)
            
            if added == 0:
                # 连接已存在，说明是同一个客户端的多个连接
                pass
            
            # 获取当前连接数
            current_count = await r.scard(key)
            
            # 设置TTL（5分钟自动清理）
            await r.expire(key, 300)
            
            if current_count > self.max_connections:
                # 超限，移除刚添加的连接
                await r.srem(key, client_id)
                
                logger.warning(
                    f"Connection limit exceeded for {client_id}: "
                    f"{current_count}/{self.max_connections}"
                )
                
                return False, {
                    "current_connections": current_count,
                    "max_connections": self.max_connections,
                    "retry_after": 60,
                }
            
            return True, {
                "current_connections": current_count,
                "max_connections": self.max_connections,
            }
            
        except Exception as e:
            logger.error(f"Redis connection limit error: {e}")
            # 降级到内存方案
            return self._check_memory_connection_limit(client_id)
    
    def _check_memory_connection_limit(self, client_id: str) -> Tuple[bool, Optional[Dict]]:
        """内存降级方案"""
        with self._memory_lock:
            current_count = len(self._memory_connections)
            
            if current_count >= self.max_connections:
                logger.warning(
                    f"Memory connection limit exceeded: "
                    f"{current_count}/{self.max_connections}"
                )
                return False, {
                    "current_connections": current_count,
                    "max_connections": self.max_connections,
                    "retry_after": 60,
                }
            
            self._memory_connections.add(client_id)
            
            return True, {
                "current_connections": current_count + 1,
                "max_connections": self.max_connections,
            }
    
    async def _release_connection(self, client_id: str):
        """释放连接"""
        try:
            r = await self._get_redis()
            key = f"{self._REDIS_KEY_PREFIX}{self._ACTIVE_CONNECTIONS_KEY}"
            await r.srem(key, client_id)
        except Exception as e:
            logger.error(f"Failed to release connection: {e}")
            # 降级到内存
            with self._memory_lock:
                self._memory_connections.discard(client_id)
    
    async def dispatch(self, request: Request, call_next):
        # 获取客户端ID
        client_id = self._get_client_id(request)
        
        # 检查连接限制
        allowed, info = await self._check_connection_limit(client_id)
        
        if not allowed:
            response = JSONResponse(
                status_code=503,
                content={
                    "detail": "服务器繁忙，请稍后重试",
                    "error": "connection_limit_exceeded",
                    "retry_after": info["retry_after"],
                }
            )
            response.headers["X-ConnectionLimit-Limit"] = str(info["max_connections"])
            response.headers["X-ConnectionLimit-Current"] = str(info["current_connections"])
            response.headers["Retry-After"] = str(info["retry_after"])
            return response
        
        # 处理请求
        try:
            response = await call_next(request)
            
            # 添加连接限制头
            response.headers["X-ConnectionLimit-Limit"] = str(self.max_connections)
            response.headers["X-ConnectionLimit-Current"] = str(info["current_connections"])
            
            return response
        finally:
            # 释放连接
            await self._release_connection(client_id)


def create_rate_limit_middleware(config: Optional[Dict] = None):
    """创建限流中间件的工厂函数"""
    def middleware(app):
        return RateLimitMiddleware(app, config)
    return middleware


def create_connection_limit_middleware(max_connections: int = 100):
    """创建连接数限制中间件的工厂函数"""
    def middleware(app):
        return ConnectionLimitMiddleware(app, max_connections)
    return middleware
