# -*- coding: utf-8 -*-
"""
缓存服务 - 支持内存缓存和 Redis 缓存的抽象层
"""
import time
import json
import logging
from typing import Any, Dict, Optional, Callable
from threading import Lock
from collections import OrderedDict
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
    - 支持 LRU 淘汰策略
    - 支持多节点集群（分布式通知）
    """
    
    def __init__(self, node_id: str = None, max_size: int = 1000):
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = Lock()
        self._max_size = max_size  # 最大缓存条目数
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
    
    def _evict_if_needed(self) -> None:
        """当缓存满时淘汰最旧的条目（LRU）"""
        while len(self._cache) >= self._max_size:
            # 弹出最旧的条目（OrderedDict 头部）
            self._cache.popitem(last=False)
    
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
            
            # 移动到末尾（表示最近使用）
            self._cache.move_to_end(key)
            self._hits += 1
            return entry.value
    
    def set(self, key: str, value: Any, ttl: int = 300) -> None:
        """设置缓存值"""
        with self._lock:
            # 如果key已存在，先删除（更新位置）
            if key in self._cache:
                del self._cache[key]
            
            # 检查是否需要淘汰
            self._evict_if_needed()
            
            self._cache[key] = CacheEntry(value, ttl)
            # 移动到末尾（最新）
            self._cache.move_to_end(key)
    
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
    
    async def aget(self, key: str, default: Any = None) -> Optional[Any]:
        """异步获取缓存值"""
        if not self._connected:
            return default
        
        try:
            redis = self._get_redis()
            if redis is None:
                return default
            
            value = await redis.get(key)
            
            if value is None:
                self._misses += 1
                return default
            
            self._hits += 1
            return json.loads(value)
            
        except Exception as e:
            logger.error(f"Redis async get error: {e}")
            self._misses += 1
            return default
    
    def get(self, key: str, default: Any = None) -> Optional[Any]:
        """获取缓存值（同步版本，用于非异步环境）"""
        if not self._connected:
            return default
        
        try:
            import asyncio
            try:
                loop = asyncio.get_running_loop()
                # 在异步环境中，使用同步 Redis 客户端（不创建新事件循环）
                return self._sync_get(key, default)
            except RuntimeError:
                # 没有运行中的事件循环，可以安全使用 asyncio.run
                return asyncio.run(self.aget(key, default))
            
        except Exception as e:
            logger.error(f"Redis get error: {e}")
            self._misses += 1
            return default
    
    def _sync_get(self, key: str, default: Any = None) -> Any:
        """使用同步 Redis 客户端获取缓存值（可在异步上下文中安全使用）"""
        try:
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
            logger.error(f"Redis sync get error: {e}")
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
    
    async def aset(self, key: str, value: Any, ttl: int = 300) -> None:
        """异步设置缓存值"""
        if not self._connected:
            return
        
        try:
            redis = self._get_redis()
            if redis:
                await redis.setex(key, ttl, json.dumps(value))
        except Exception as e:
            logger.error(f"Redis async set error: {e}")
    
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
    
    async def adelete(self, key: str) -> bool:
        """异步删除缓存"""
        if not self._connected:
            return False
        
        try:
            redis = self._get_redis()
            if redis:
                result = await redis.delete(key)
                return result > 0
        except Exception as e:
            logger.error(f"Redis async delete error: {e}")
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
    
    async def aclear(self) -> None:
        """异步清空所有缓存"""
        if not self._connected:
            return
        
        try:
            redis = self._get_redis()
            if redis:
                await redis.flushdb()
                self._hits = 0
                self._misses = 0
        except Exception as e:
            logger.error(f"Redis async clear error: {e}")
    
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
        
        # 自动清理定时器（仅内存缓存）
        self._cleanup_task = None
    
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
        
        # 启动自动清理任务（仅内存缓存）
        await self._start_cleanup_task()
    
    async def _start_cleanup_task(self) -> None:
        """启动后台清理任务"""
        if self._current_backend == CacheBackend.MEMORY:
            # 每5分钟清理一次过期缓存
            import asyncio
            
            async def cleanup_loop():
                while True:
                    await asyncio.sleep(300)  # 5分钟
                    try:
                        cleaned = self._memory_cache.cleanup_expired()
                        if cleaned > 0:
                            logger.debug(f"Cleaned up {cleaned} expired cache entries")
                    except Exception as e:
                        logger.error(f"Cache cleanup error: {e}")
            
            # 创建后台任务（不阻塞启动）
            asyncio.create_task(cleanup_loop())
    
    @property
    def backend(self) -> CacheBackend:
        """获取当前使用的后端"""
        return self._current_backend
    
    async def aget(self, key: str, default: Any = None) -> Any:
        """异步获取缓存值"""
        if self._current_backend == CacheBackend.REDIS and self._redis_cache:
            try:
                return await self._redis_cache.aget(key, default)
            except Exception as e:
                logger.error(f"Redis async get failed, falling back to memory: {e}")
                if self._fallback_to_memory:
                    return self._memory_cache.get(key, default)
                raise
        
        # 内存缓存的同步 get 方法在异步上下文中也可安全使用
        return self._memory_cache.get(key, default)
    
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
    
    async def aset(self, key: str, value: Any, ttl: int = 300) -> None:
        """异步设置缓存值"""
        if self._current_backend == CacheBackend.REDIS and self._redis_cache:
            try:
                await self._redis_cache.aset(key, value, ttl)
                return
            except Exception as e:
                logger.error(f"Redis async set failed, falling back to memory: {e}")
                if self._fallback_to_memory:
                    pass
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
    
    async def adelete(self, key: str) -> bool:
        """异步删除缓存"""
        deleted = False
        
        if self._current_backend == CacheBackend.REDIS and self._redis_cache:
            try:
                deleted = await self._redis_cache.adelete(key)
            except Exception as e:
                logger.error(f"Redis async delete failed: {e}")
        
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
    
    async def aclear(self) -> None:
        """异步清空所有缓存"""
        if self._current_backend == CacheBackend.REDIS and self._redis_cache:
            try:
                await self._redis_cache.aclear()
            except Exception as e:
                logger.error(f"Redis async clear failed: {e}")
        
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
    
    # ============ 集群支持方法 ============
    
    def set_node_id(self, node_id: str) -> None:
        """设置当前节点ID（用于集群环境）"""
        self._memory_cache.set_node_id(node_id)
        logger.info(f"Cache node ID set to: {node_id}")
    
    def get_node_id(self) -> str:
        """获取当前节点ID"""
        return self._memory_cache.get_node_id()
    
    def register_to_cluster(self, other_cache: 'CacheManager') -> None:
        """注册到集群（与其他缓存节点同步）"""
        if self._current_backend == CacheBackend.MEMORY and other_cache._current_backend == CacheBackend.MEMORY:
            self._memory_cache.subscribe(other_cache._memory_cache)
            logger.info(f"Registered to cluster with node: {other_cache.get_node_id()}")
    
    def broadcast_invalidation(self, key: str) -> None:
        """广播缓存失效通知到集群"""
        if self._current_backend == CacheBackend.MEMORY:
            self._memory_cache._notify_subscribers("delete", key)
            logger.debug(f"Broadcast cache invalidation for key: {key}")
    
    def broadcast_clear(self) -> None:
        """广播缓存清空通知到集群"""
        if self._current_backend == CacheBackend.MEMORY:
            self._memory_cache._notify_subscribers("clear", "")
            logger.debug("Broadcast cache clear to cluster")


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
        # 创建实例后自动调用 initialize()
        import asyncio
        try:
            try:
                loop = asyncio.get_running_loop()
                # 在异步环境中，使用 create_task 后台执行
                asyncio.create_task(_cache.initialize())
            except RuntimeError:
                # 没有运行中的事件循环
                asyncio.run(_cache.initialize())
        except Exception as e:
            logger.warning(f"Cache auto-initialize failed: {e}")
    
    return _cache


# ============ 便捷函数 ============

async def aget(key: str, default: Any = None) -> Any:
    """异步获取缓存值"""
    cache = get_cache()
    return await cache.aget(key, default)


def get(key: str, default: Any = None) -> Any:
    """获取缓存值"""
    cache = get_cache()
    return cache.get(key, default)


def set(key: str, value: Any, ttl: int = 300) -> None:
    """设置缓存值"""
    cache = get_cache()
    cache.set(key, value, ttl)


async def aset(key: str, value: Any, ttl: int = 300) -> None:
    """异步设置缓存值"""
    cache = get_cache()
    await cache.aset(key, value, ttl)


def delete(key: str) -> bool:
    """删除缓存"""
    cache = get_cache()
    return cache.delete(key)


async def adelete(key: str) -> bool:
    """异步删除缓存"""
    cache = get_cache()
    return await cache.adelete(key)


def clear() -> None:
    """清空缓存"""
    cache = get_cache()
    cache.clear()


async def aclear() -> None:
    """异步清空缓存"""
    cache = get_cache()
    await cache.aclear()


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
    async def aget(key: str, default: Any = None) -> Any:
        return await aget(key, default)
    
    @staticmethod
    def get(key: str, default: Any = None) -> Any:
        return get(key, default)
    
    @staticmethod
    async def aset(key: str, value: Any, ttl: int = 300) -> None:
        return await aset(key, value, ttl)
    
    @staticmethod
    def set(key: str, value: Any, ttl: int = 300) -> None:
        set(key, value, ttl)
    
    @staticmethod
    async def adelete(key: str) -> bool:
        return await adelete(key)
    
    @staticmethod
    def delete(key: str) -> bool:
        return delete(key)
    
    @staticmethod
    async def aclear() -> None:
        return await aclear()
    
    @staticmethod
    def clear() -> None:
        clear()
    
    @staticmethod
    def get_stats() -> Dict[str, Any]:
        return get_stats()
