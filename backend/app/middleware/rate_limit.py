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


def create_rate_limit_middleware(config: Optional[Dict] = None):
    """创建限流中间件的工厂函数"""
    def middleware(app):
        return RateLimitMiddleware(app, config)
    return middleware
