# -*- coding: utf-8 -*-
"""
速率限制中间件 - API 限流
支持分布式环境（Redis）
"""
import time
import json
import logging
from typing import Dict, Optional, Tuple
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

import redis.asyncio as redis

from app.core.config import settings

logger = logging.getLogger(__name__)


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
        self._redis_client: Optional[redis.Redis] = None
        self._redis_prefix = "rate_limit:"
    
    async def _get_redis(self) -> redis.Redis:
        """获取或创建 Redis 连接"""
        if self._redis_client is None:
            self._redis_client = redis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True
            )
        return self._redis_client
    
    async def _close_redis(self):
        """关闭 Redis 连接"""
        if self._redis_client:
            await self._redis_client.close()
            self._redis_client = None
    
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
            # Redis 出错时允许请求通过，避免阻断服务
            return True, None
    
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
