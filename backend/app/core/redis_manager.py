# -*- coding: utf-8 -*-
"""
Redis 连接管理器 - 统一管理 Redis 连接
避免在多个模块中重复创建 Redis 连接

异步安全版本（v4）- 支持密码认证
"""
import os
import asyncio
import logging
from typing import Optional

import redis.asyncio as redis

from app.core.config import settings

logger = logging.getLogger(__name__)


def _build_redis_url(url: str, password: Optional[str] = None) -> str:
    """
    构建 Redis URL，支持密码认证
    
    Args:
        url: Redis URL (redis://host:port/db)
        password: Redis 密码（可选）。如果为 None，则尝试从环境变量 REDIS_PASSWORD 获取。
        
    Returns:
        带密码的 Redis URL (redis://:password@host:port/db)
    """
    # 如果未提供密码，尝试从环境变量获取
    if password is None:
        password = os.environ.get("REDIS_PASSWORD")
    
    if not password:
        return url
    
    # 解析原始URL，插入密码
    # 格式: redis://host:port/db -> redis://:password@host:port/db
    if url.startswith("redis://"):
        # 去除现有的认证信息
        if "@" in url:
            # 已有认证信息，替换
            parts = url.split("@")
            host_part = parts[-1]
            url_without_auth = f"redis://{host_part}"
        else:
            # 没有认证信息，直接处理
            url_without_auth = url
        
        # 插入密码
        # 格式: redis://host:port/db -> redis://:password@host:port/db
        # 找到 / 位置
        if "/" in url_without_auth[8:]:  # redis:// 之后
            slash_pos = url_without_auth.find("/", 8)
            host_port = url_without_auth[8:slash_pos]
            db_path = url_without_auth[slash_pos:]
            return f"redis://:{password}@{host_port}{db_path}"
        else:
            return f"redis://:{password}@{url_without_auth[8:]}"
    
    return url


class RedisManager:
    """Redis 连接管理器（单例模式，异步安全）"""
    
    _instance: Optional["RedisManager"] = None
    _redis_client: Optional[redis.Redis] = None
    _lock: asyncio.Lock = None  # 延迟初始化
    _reconnect_task: Optional[asyncio.Task] = None
    _last_connection_error: Optional[str] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """初始化锁"""
        if not hasattr(self, '_init_lock') or self._init_lock is None:
            self._init_lock = asyncio.Lock()
    
    def _get_redis_url(self) -> str:
        """获取 Redis URL（支持密码）"""
        password = os.environ.get("REDIS_PASSWORD") or getattr(settings, 'REDIS_PASSWORD', None)
        return _build_redis_url(settings.REDIS_URL, password)
    
    async def get_client(self) -> redis.Redis:
        """获取 Redis 客户端（单例，异步安全）"""
        async with self._init_lock:
            if self._redis_client is None:
                redis_url = self._get_redis_url()
                self._redis_client = redis.from_url(
                    redis_url,
                    encoding="utf-8",
                    decode_responses=True
                )
                logger.info("Redis client initialized")
        return self._redis_client
    
    async def close(self):
        """关闭 Redis 连接"""
        async with self._init_lock:
            if self._redis_client:
                await self._redis_client.close()
                self._redis_client = None
                logger.info("Redis client closed")
    
    async def is_connected(self) -> bool:
        """检查是否已连接"""
        if self._redis_client is None:
            return False
        try:
            await self._redis_client.ping()
            return True
        except Exception:
            return False
    
    async def reconnect(self) -> bool:
        """
        手动重连 Redis
        
        Returns:
            是否重连成功
        """
        async with self._init_lock:
            if self._redis_client:
                try:
                    await self._redis_client.close()
                except Exception:
                    pass
                self._redis_client = None
        
        try:
            await self.get_client()
            self._last_connection_error = None
            logger.info("Redis reconnected successfully")
            return True
        except Exception as e:
            self._last_connection_error = str(e)
            logger.error(f"Redis reconnection failed: {e}")
            return False
    
    def _start_reconnect_task(self) -> None:
        """启动定时重连任务（每60秒检查一次）"""
        if self._reconnect_task and not self._reconnect_task.done():
            return
        
        async def reconnect_loop():
            while True:
                await asyncio.sleep(60)  # 每60秒检查一次
                if not await self.is_connected():
                    logger.warning("Redis connection lost, attempting to reconnect...")
                    if await self.reconnect():
                        logger.info("Redis reconnected via background task")
        
        self._reconnect_task = asyncio.create_task(reconnect_loop())
        logger.info("Redis background reconnect task started")
    
    async def close(self):
        """关闭 Redis 连接"""
        async with self._init_lock:
            if self._reconnect_task:
                self._reconnect_task.cancel()
                try:
                    await self._reconnect_task
                except asyncio.CancelledError:
                    pass
                self._reconnect_task = None
            
            if self._redis_client:
                await self._redis_client.close()
                self._redis_client = None
                logger.info("Redis client closed")
    
    def get_last_error(self) -> Optional[str]:
        """获取最后的连接错误信息"""
        return self._last_connection_error


# 全局实例
redis_manager = RedisManager()


async def get_redis() -> redis.Redis:
    """获取 Redis 客户端的便捷函数"""
    return await redis_manager.get_client()


async def close_redis():
    """关闭 Redis 连接的便捷函数"""
    await redis_manager.close()
