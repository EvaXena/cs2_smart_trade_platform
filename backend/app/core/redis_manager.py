# -*- coding: utf-8 -*-
"""
Redis 连接管理器 - 统一管理 Redis 连接
避免在多个模块中重复创建 Redis 连接
"""
import logging
from typing import Optional

import redis.asyncio as redis

from app.core.config import settings

logger = logging.getLogger(__name__)


class RedisManager:
    """Redis 连接管理器（单例模式）"""
    
    _instance: Optional["RedisManager"] = None
    _redis_client: Optional[redis.Redis] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    async def get_client(self) -> redis.Redis:
        """获取 Redis 客户端（单例）"""
        if self._redis_client is None:
            self._redis_client = redis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True
            )
            logger.info("Redis client initialized")
        return self._redis_client
    
    async def close(self):
        """关闭 Redis 连接"""
        if self._redis_client:
            await self._redis_client.close()
            self._redis_client = None
            logger.info("Redis client closed")
    
    @property
    def is_connected(self) -> bool:
        """检查是否已连接"""
        return self._redis_client is not None


# 全局实例
redis_manager = RedisManager()


async def get_redis() -> redis.Redis:
    """获取 Redis 客户端的便捷函数"""
    return await redis_manager.get_client()


async def close_redis():
    """关闭 Redis 连接的便捷函数"""
    await redis_manager.close()
