# -*- coding: utf-8 -*-
"""
API限流中间件
基于IP和用户的请求限流
"""
from fastapi import Request, HTTPException, Depends
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from typing import Dict, Optional, Tuple
import time
import logging
from collections import defaultdict
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class RateLimiter:
    """限流器"""
    
    def __init__(self):
        # IP -> [(timestamp, count)]
        self.ip_requests: Dict[str, list] = defaultdict(list)
        # User ID -> [(timestamp, count)]
        self.user_requests: Dict[int, list] = defaultdict(list)
        
        # 从配置读取限流参数
        from app.core.config import settings
        self.ip_limit = settings.RATE_LIMIT_DEFAULT_REQUESTS  # IP每分钟最大请求数
        self.ip_window = settings.RATE_LIMIT_DEFAULT_WINDOW   # IP时间窗口(秒)
        self.user_limit = settings.RATE_LIMIT_DEFAULT_REQUESTS * 2  # 用户每分钟最大请求数
        self.user_window = settings.RATE_LIMIT_DEFAULT_WINDOW      # 用户时间窗口(秒)
        
        # 清理间隔
        self.last_cleanup = time.time()
        self.cleanup_interval = 300  # 5分钟清理一次
    
    def _cleanup_old_requests(self):
        """清理过期的请求记录"""
        current_time = time.time()
        
        if current_time - self.last_cleanup < self.cleanup_interval:
            return
        
        # 清理IP请求记录
        for ip in list(self.ip_requests.keys()):
            self.ip_requests[ip] = [
                (ts, count) for ts, count in self.ip_requests[ip]
                if current_time - ts < self.ip_window
            ]
            if not self.ip_requests[ip]:
                del self.ip_requests[ip]
        
        # 清理用户请求记录
        for user_id in list(self.user_requests.keys()):
            self.user_requests[user_id] = [
                (ts, count) for ts, count in self.user_requests[user_id]
                if current_time - ts < self.user_window
            ]
            if not self.user_requests[user_id]:
                del self.user_requests[user_id]
        
        self.last_cleanup = current_time
    
    def _get_client_ip(self, request: Request) -> str:
        """获取客户端IP"""
        # 优先获取X-Forwarded-For
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        
        # 获取X-Real-IP
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip
        
        # 获取连接IP
        if request.client:
            return request.client.host
        
        return "unknown"
    
    async def check_rate_limit(
        self,
        request: Request,
        user_id: Optional[int] = None
    ) -> Tuple[bool, Dict]:
        """
        检查限流
        返回: (是否允许, 限流信息)
        """
        self._cleanup_old_requests()
        
        current_time = time.time()
        client_ip = self._get_client_ip(request)
        
        # 检查IP限流
        ip_requests = self.ip_requests[client_ip]
        ip_requests = [(ts, count) for ts, count in ip_requests if current_time - ts < self.ip_window]
        
        if len(ip_requests) >= self.ip_limit:
            # 计算重置时间
            oldest = min(ts for ts, _ in ip_requests) if ip_requests else current_time
            reset_time = int(oldest + self.ip_window - current_time)
            
            logger.warning(f"IP {client_ip} rate limit exceeded")
            
            return False, {
                "limit": self.ip_limit,
                "remaining": 0,
                "reset": reset_time,
                "type": "ip"
            }
        
        # 记录请求
        ip_requests.append((current_time, 1))
        self.ip_requests[client_ip] = ip_requests
        
        # 检查用户限流(如果已认证)
        if user_id:
            user_requests = self.user_requests[user_id]
            user_requests = [(ts, count) for ts, count in user_requests if current_time - ts < self.user_window]
            
            if len(user_requests) >= self.user_limit:
                oldest = min(ts for ts, _ in user_requests) if user_requests else current_time
                reset_time = int(oldest + self.user_window - current_time)
                
                logger.warning(f"User {user_id} rate limit exceeded")
                
                return False, {
                    "limit": self.user_limit,
                    "remaining": 0,
                    "reset": reset_time,
                    "type": "user"
                }
            
            user_requests.append((current_time, 1))
            self.user_requests[user_id] = user_requests
        
        # 计算剩余请求数
        remaining_ip = self.ip_limit - len(ip_requests)
        
        return True, {
            "limit": self.ip_limit,
            "remaining": remaining_ip,
            "reset": int(self.ip_window),
            "type": "ip"
        }
    
    def set_limits(self, ip_limit: int = None, ip_window: int = None, 
                   user_limit: int = None, user_window: int = None):
        """自定义限流参数"""
        if ip_limit is not None:
            self.ip_limit = ip_limit
        if ip_window is not None:
            self.ip_window = ip_window
        if user_limit is not None:
            self.user_limit = user_limit
        if user_window is not None:
            self.user_window = user_window


# 全局限流器实例
rate_limiter = RateLimiter()


class RateLimitMiddleware(BaseHTTPMiddleware):
    """限流中间件"""
    
    async def dispatch(self, request: Request, call_next):
        # 跳过限流的路径
        skip_paths = ["/docs", "/redoc", "/openapi.json", "/health"]
        if any(request.url.path.startswith(path) for path in skip_paths):
            return await call_next(request)
        
        # 获取用户ID(如果已认证)
        user_id = None
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            try:
                from app.core.security import decode_token
                token = auth_header.replace("Bearer ", "")
                payload = decode_token(token)
                if payload:
                    user_id = payload.get("sub")
                    if isinstance(user_id, str):
                        user_id = int(user_id)
            except Exception:
                pass
        
        # 检查限流
        allowed, rate_info = await rate_limiter.check_rate_limit(request, user_id)
        
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "请求过于频繁，请稍后再试",
                    "rate_limit": rate_info
                },
                headers={
                    "X-RateLimit-Limit": str(rate_info["limit"]),
                    "X-RateLimit-Remaining": str(rate_info["remaining"]),
                    "X-RateLimit-Reset": str(rate_info["reset"])
                }
            )
        
        # 处理请求
        response = await call_next(request)
        
        # 添加限流响应头
        response.headers["X-RateLimit-Limit"] = str(rate_info["limit"])
        response.headers["X-RateLimit-Remaining"] = str(rate_info["remaining"])
        response.headers["X-RateLimit-Reset"] = str(rate_info["reset"])
        
        return response


# 依赖项方式使用限流
async def check_rate_limit(request: Request) -> Dict:
    """依赖项方式检查限流"""
    user_id = None
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        try:
            from app.core.security import decode_token
            token = auth_header.replace("Bearer ", "")
            payload = decode_token(token)
            if payload:
                user_id = payload.get("sub")
                if isinstance(user_id, str):
                    user_id = int(user_id)
        except Exception:
            pass
    
    allowed, rate_info = await rate_limiter.check_rate_limit(request, user_id)
    
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail={
                "message": "请求过于频繁，请稍后再试",
                "rate_limit": rate_info
            }
        )
    
    return rate_info
