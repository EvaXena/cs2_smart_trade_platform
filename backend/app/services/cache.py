# -*- coding: utf-8 -*-
"""
缓存服务 - 支持内存缓存和 Redis 缓存的抽象层
"""
import time
import json
import logging
from typing import Any, Dict, Optional, Callable
from threading import Lock
from enum import Enum

logger = logging.getLogger(__name__)


class CacheBackend(str, Enum):
    """缓存后端类型"""
    MEMORY = "memory"
    REDIS = "redis"


class CacheEntry:
    """缓存条目（用于内存缓存）"""
    def __init__(self, value: Any, ttl: int):
        self.value = value
        self.expire_at = time.time() + ttl if ttl > 0 else float('inf')
    
    def is_expired(self) -> bool:
        return time.time() > self.expire_at


class MemoryCache:
    """
    简单的内存缓存实现
    
    特性:
    - 支持 TTL（生存时间）
    - 线程安全
    - 自动清理过期条目
    - 支持多节点集群（分布式通知）
    """
    
    def __init__(self, node_id: str = None):
        self._cache: Dict[str, CacheEntry] = {}
        self._lock = Lock()
        # 统计信息
        self._hits = 0
        self._misses = 0
        # 集群支持
        self._node_id = node_id or f"node-{id(self)}"
        self._subscribers: Dict[str, 'MemoryCache'] = {}
    
    def set_node_id(self, node_id: str) -> None:
        """设置节点ID"""
        self._node_id = node_id
    
    def get_node_id(self) -> str:
        """获取节点ID"""
        return self._node_id
    
    def subscribe(self, other_cache: 'MemoryCache') -> None:
        """订阅另一个缓存节点的更新"""
        self._subscribers[other_cache._node_id] = other_cache
    
    def unsubscribe(self, node_id: str) -> None:
        """取消订阅"""
        if node_id in self._subscribers:
            del self._subscribers[node_id]
    
    def _notify_subscribers(self, operation: str, key: str) -> None:
        """通知订阅者缓存变更"""
        for node_id, subscriber in self._subscribers.items():
            try:
                if operation == "delete":
                    subscriber._handle_remote_delete(key)
                elif operation == "clear":
                    subscriber._handle_remote_clear()
            except Exception as e:
                logger.warning(f"Failed to notify subscriber {node_id}: {e}")
    
    def _handle_remote_delete(self, key: str) -> None:
        """处理远程删除通知"""
        with self._lock:
            if key in self._cache:
                del self._cache[key]
    
    def _handle_remote_clear(self) -> None:
        """处理远程清空通知"""
        with self._lock:
            self._cache.clear()
    
    def get(self, key: str, default: Any = None) -> Optional[Any]:
        """获取缓存值"""
        with self._lock:
            if key not in self._cache:
                self._misses += 1
                return default
            
            entry = self._cache[key]
            if entry.is_expired():
                del self._cache[key]
                self._misses += 1
                return default
            
            self._hits += 1
            return entry.value
    
    def set(self, key: str, value: Any, ttl: int = 300) -> None:
        """设置缓存值"""
        with self._lock:
            self._cache[key] = CacheEntry(value, ttl)
    
    def delete(self, key: str) -> bool:
        """删除缓存"""
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False
    
    def clear(self) -> None:
        """清空所有缓存"""
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0
    
    def cleanup_expired(self) -> int:
        """清理过期缓存"""
        with self._lock:
            expired_keys = [
                key for key, entry in self._cache.items()
                if entry.is_expired()
            ]
            for key in expired_keys:
                del self._cache[key]
            return len(expired_keys)
    
    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        with self._lock:
            total = self._hits + self._misses
            hit_rate = (self._hits / total * 100) if total > 0 else 0
            
            return {
                "hits": self._hits,
                "misses": self._misses,
                "total_requests": total,
                "hit_rate": round(hit_rate, 2),
                "total_keys": len(self._cache),
            }
    
    def keys(self) -> list:
        """获取所有缓存键"""
        with self._lock:
            return list(self._cache.keys())


class RedisCache:
    """
    Redis 缓存实现
    
    特性:
    - 支持 TTL
    - 支持集群扩展
    - 自动序列化/反序列化 JSON
    """
    
    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        self._redis_url = redis_url
        self._redis = None
        self._connected = False
        
        # 统计信息
        self._hits = 0
        self._misses = 0
    
    def _get_redis(self):
        """获取或创建 Redis 连接"""
        if self._redis is None:
            try:
                import redis.asyncio as redis
                self._redis = redis.from_url(
                    self._redis_url,
                    encoding="utf-8",
                    decode_responses=True
                )
            except ImportError:
                logger.warning("redis-py not installed, falling back to memory cache")
                return None
            except Exception as e:
                logger.error(f"Failed to connect to Redis: {e}")
                return None
        return self._redis
    
    async def connect(self) -> bool:
        """连接 Redis"""
        try:
            redis = self._get_redis()
            if redis:
                await redis.ping()
                self._connected = True
                logger.info("Connected to Redis cache")
                return True
        except Exception as e:
            logger.error(f"Redis connection failed: {e}")
        
        self._connected = False
        return False
    
    async def disconnect(self) -> None:
        """断开 Redis 连接"""
        if self._redis:
            await self._redis.close()
            self._redis = None
            self._connected = False
    
    def get(self, key: str, default: Any = None) -> Optional[Any]:
        """获取缓存值"""
        if not self._connected:
            return default
        
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 在异步环境中需要异步获取
                return default
            
            # 同步获取（用于初始化等场景）
            import redis
            r = redis.from_url(self._redis_url, decode_responses=True)
            value = r.get(key)
            r.close()
            
            if value is None:
                self._misses += 1
                return default
            
            self._hits += 1
            return json.loads(value)
            
        except Exception as e:
            logger.error(f"Redis get error: {e}")
            self._misses += 1
            return default
    
    def set(self, key: str, value: Any, ttl: int = 300) -> None:
        """设置缓存值"""
        if not self._connected:
            return
        
        try:
            import redis
            r = redis.from_url(self._redis_url, decode_responses=True)
            r.setex(key, ttl, json.dumps(value))
            r.close()
        except Exception as e:
            logger.error(f"Redis set error: {e}")
    
    def delete(self, key: str) -> bool:
        """删除缓存"""
        if not self._connected:
            return False
        
        try:
            import redis
            r = redis.from_url(self._redis_url, decode_responses=True)
            result = r.delete(key)
            r.close()
            return result > 0
        except Exception as e:
            logger.error(f"Redis delete error: {e}")
            return False
    
    def clear(self) -> None:
        """清空所有缓存"""
        if not self._connected:
            return
        
        try:
            import redis
            r = redis.from_url(self._redis_url, decode_responses=True)
            r.flushdb()
            r.close()
            self._hits = 0
            self._misses = 0
        except Exception as e:
            logger.error(f"Redis clear error: {e}")
    
    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        total = self._hits + self._misses
        hit_rate = (self._hits / total * 100) if total > 0 else 0
        
        return {
            "hits": self._hits,
            "misses": self._misses,
            "total_requests": total,
            "hit_rate": round(hit_rate, 2),
            "backend": "redis",
            "connected": self._connected,
        }


class CacheManager:
    """
    缓存管理器 - 支持内存/Redis 切换
    
    特性:
    - 统一的缓存接口
    - 支持多种后端
    - 自动故障转移
    """
    
    def __init__(self, backend: CacheBackend = CacheBackend.MEMORY, redis_url: str = None):
        self._backend = backend
        self._memory_cache = MemoryCache()
        
        # Redis 配置
        self._redis_url = redis_url or "redis://localhost:6379/0"
        self._redis_cache = None
        
        # 自动故障转移
        self._fallback_to_memory = True
        
        # 当前使用的后端
        self._current_backend: CacheBackend = backend
    
    async def initialize(self) -> None:
        """初始化缓存"""
        if self._backend == CacheBackend.REDIS:
            self._redis_cache = RedisCache(self._redis_url)
            connected = await self._redis_cache.connect()
            
            if not connected:
                logger.warning("Redis connection failed, falling back to memory cache")
                if self._fallback_to_memory:
                    self._current_backend = CacheBackend.MEMORY
                else:
                    raise RuntimeError("Failed to connect to Redis and fallback is disabled")
            else:
                self._current_backend = CacheBackend.REDIS
        
        logger.info(f"Cache initialized with backend: {self._current_backend.value}")
    
    @property
    def backend(self) -> CacheBackend:
        """获取当前使用的后端"""
        return self._current_backend
    
    def get(self, key: str, default: Any = None) -> Any:
        """获取缓存值"""
        if self._current_backend == CacheBackend.REDIS and self._redis_cache:
            try:
                return self._redis_cache.get(key, default)
            except Exception as e:
                logger.error(f"Redis get failed, falling back to memory: {e}")
                if self._fallback_to_memory:
                    return self._memory_cache.get(key, default)
                raise
        
        return self._memory_cache.get(key, default)
    
    def set(self, key: str, value: Any, ttl: int = 300) -> None:
        """设置缓存值"""
        if self._current_backend == CacheBackend.REDIS and self._redis_cache:
            try:
                self._redis_cache.set(key, value, ttl)
                return
            except Exception as e:
                logger.error(f"Redis set failed, falling back to memory: {e}")
                if self._fallback_to_memory:
                    pass  # 继续使用内存缓存
                else:
                    raise
        
        self._memory_cache.set(key, value, ttl)
    
    def delete(self, key: str) -> bool:
        """删除缓存"""
        deleted = False
        
        if self._current_backend == CacheBackend.REDIS and self._redis_cache:
            try:
                deleted = self._redis_cache.delete(key)
            except Exception as e:
                logger.error(f"Redis delete failed: {e}")
        
        # 同时删除内存缓存
        if self._memory_cache.delete(key):
            deleted = True
        
        return deleted
    
    def clear(self) -> None:
        """清空所有缓存"""
        if self._current_backend == CacheBackend.REDIS and self._redis_cache:
            try:
                self._redis_cache.clear()
            except Exception as e:
                logger.error(f"Redis clear failed: {e}")
        
        self._memory_cache.clear()
    
    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        if self._current_backend == CacheBackend.REDIS and self._redis_cache:
            stats = self._redis_cache.get_stats()
            stats["backend"] = self._current_backend.value
            return stats
        
        stats = self._memory_cache.get_stats()
        stats["backend"] = self._current_backend.value
        return stats
    
    async def cleanup_expired(self) -> int:
        """清理过期缓存（仅内存缓存需要）"""
        if self._current_backend == CacheBackend.MEMORY:
            return self._memory_cache.cleanup_expired()
        return 0
    
    def keys(self) -> list:
        """获取所有缓存键"""
        if self._current_backend == CacheBackend.MEMORY:
            return self._memory_cache.keys()
        return []  # Redis 不支持 keys 操作


# 全局缓存实例
_cache: Optional[CacheManager] = None


def get_cache() -> CacheManager:
    """获取全局缓存实例"""
    global _cache
    if _cache is None:
        # 从配置读取
        from app.core.config import settings
        
        backend = CacheBackend.MEMORY
        if settings.REDIS_URL:
            backend = CacheBackend.REDIS
        
        _cache = CacheManager(
            backend=backend,
            redis_url=settings.REDIS_URL if hasattr(settings, 'REDIS_URL') else None
        )
    
    return _cache


# ============ 便捷函数 ============

def get(key: str, default: Any = None) -> Any:
    """获取缓存值"""
    cache = get_cache()
    return cache.get(key, default)


def set(key: str, value: Any, ttl: int = 300) -> None:
    """设置缓存值"""
    cache = get_cache()
    cache.set(key, value, ttl)


def delete(key: str) -> bool:
    """删除缓存"""
    cache = get_cache()
    return cache.delete(key)


def clear() -> None:
    """清空缓存"""
    cache = get_cache()
    cache.clear()


def get_stats() -> Dict[str, Any]:
    """获取缓存统计"""
    cache = get_cache()
    return cache.get_stats()


# ============ 特定用途的缓存函数 ============

# 热门物品缓存
ITEMS_CACHE_TTL = 600  # 10 分钟
ITEMS_CACHE_KEY = "popular_items"

# 价格数据缓存
PRICE_CACHE_TTL = 300  # 5 分钟
PRICE_CACHE_PREFIX = "price:"


def get_popular_items() -> Optional[Any]:
    """获取热门物品缓存"""
    return get(ITEMS_CACHE_KEY)


def set_popular_items(items: list, ttl: int = ITEMS_CACHE_TTL) -> None:
    """设置热门物品缓存"""
    set(ITEMS_CACHE_KEY, items, ttl)


def get_cached_price(item_id: str) -> Optional[Any]:
    """获取物品价格缓存"""
    return get(f"{PRICE_CACHE_PREFIX}{item_id}")


def set_cached_price(item_id: str, price: Any, ttl: int = PRICE_CACHE_TTL) -> None:
    """设置物品价格缓存"""
    set(f"{PRICE_CACHE_PREFIX}{item_id}", price, ttl)


# ============ 兼容旧接口 ============

class Cache:
    """兼容旧接口的包装类"""
    
    @staticmethod
    def get(key: str, default: Any = None) -> Any:
        return get(key, default)
    
    @staticmethod
    def set(key: str, value: Any, ttl: int = 300) -> None:
        set(key, value, ttl)
    
    @staticmethod
    def delete(key: str) -> bool:
        return delete(key)
    
    @staticmethod
    def clear() -> None:
        clear()
    
    @staticmethod
    def get_stats() -> Dict[str, Any]:
        return get_stats()
