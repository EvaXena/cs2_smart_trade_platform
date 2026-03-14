# -*- coding: utf-8 -*-
"""
缓存服务 - 支持内存缓存和 Redis 缓存的抽象层
"""
import time
import json
import logging
import random
import sys
from typing import Any, Dict, Optional, Callable, List
from threading import Lock
from collections import OrderedDict
from enum import Enum
import asyncio

# ============ Prometheus 监控指标 (已优化为内联初始化) ============
try:
    from prometheus_client import Counter, Gauge, Histogram
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False

# 指标容器类（延迟初始化）
class _CacheMetrics:
    """缓存监控指标管理器"""
    _instance = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        
        if PROMETHEUS_AVAILABLE:
            from prometheus_client import Counter, Gauge, Histogram
            self.operations = Counter(
                'cache_operations_total',
                'Total cache operations',
                ['operation', 'backend', 'result']
            )
            self.cleanup_status = Gauge(
                'cache_cleanup_status',
                'Cache cleanup task status (0=idle, 1=running, 2=error)',
                ['backend']
            )
            self.cleanup_total = Counter(
                'cache_cleanup_total',
                'Total number of cache cleanup runs',
                ['backend', 'result']
            )
            self.entries_cleaned = Gauge(
                'cache_entries_cleaned',
                'Number of cache entries cleaned',
                ['backend']
            )
            self.expired_entries = Gauge(
                'cache_expired_entries',
                'Number of expired cache entries',
                ['backend']
            )
            self.size = Gauge(
                'cache_size',
                'Current number of cache entries',
                ['backend']
            )
            self.cleanup_duration = Histogram(
                'cache_cleanup_duration_seconds',
                'Cache cleanup duration in seconds',
                ['backend']
            )
        else:
            # 空指标实现
            class _DummyMetric:
                def labels(self, **kwargs): return self
                def inc(self, n=1): pass
                def dec(self, n=1): pass
                def set(self, n): pass
                def observe(self, n): pass
            
            class _DummyCounter:
                def labels(self, **kwargs): return self
                def inc(self, n=1): pass
            
            self.operations = _DummyCounter()
            self.cleanup_status = _DummyMetric()
            self.cleanup_total = _DummyCounter()
            self.entries_cleaned = _DummyMetric()
            self.expired_entries = _DummyMetric()
            self.size = _DummyMetric()
            self.cleanup_duration = _DummyMetric()

# 全局指标实例
_metrics = _CacheMetrics()

# 便捷访问（保持向后兼容）
cache_operations_total = _metrics.operations
cache_cleanup_status = _metrics.cleanup_status
cache_cleanup_total = _metrics.cleanup_total
cache_entries_cleaned = _metrics.entries_cleaned
cache_expired_entries = _metrics.expired_entries
cache_size = _metrics.size
cache_cleanup_duration = _metrics.cleanup_duration

logger = logging.getLogger(__name__)


def _log_with_context(logger, level: str, msg: str, **context):
    """增强日志上下文辅助函数"""
    if context:
        context_str = " | ".join(f"{k}={v}" for k, v in context.items())
        msg = f"{msg} | context: {context_str}"
    getattr(logger, level)(msg)


class CacheBackend(str, Enum):
    """缓存后端类型"""
    MEMORY = "memory"
    REDIS = "redis"


class CacheEntry:
    """缓存条目（用于内存缓存）"""
    
    # 雪崩保护抖动范围
    AVALANCHE_JITTER_MIN = 0.9
    AVALANCHE_JITTER_MAX = 1.1
    
    def __init__(self, value: Any, ttl: int, enable_avalanche_protection: bool = True):
        self.value = value
        # 缓存雪崩保护：为 TTL 添加随机抖动
        if enable_avalanche_protection and ttl > 0:
            jitter = random.uniform(self.AVALANCHE_JITTER_MIN, self.AVALANCHE_JITTER_MAX)
            actual_ttl = int(ttl * jitter)
            # 确保TTL至少为1秒，避免因抖动导致永不过期
            actual_ttl = max(1, actual_ttl)
        else:
            actual_ttl = ttl
        self.expire_at = time.time() + actual_ttl if actual_ttl > 0 else float('inf')
        self.original_ttl = ttl  # 记录原始 TTL
    
    def is_expired(self) -> bool:
        return time.time() > self.expire_at
    
    def get_remaining_ttl(self) -> int:
        """获取剩余 TTL（秒）"""
        remaining = self.expire_at - time.time()
        return max(0, int(remaining))


class MemoryCache:
    """
    简单的内存缓存实现
    
    特性:
    - 支持 TTL（生存时间）
    - 线程安全 + 异步安全
    - 自动清理过期条目
    - 支持 LRU 淘汰策略
    - 支持多节点集群（分布式通知）
    - 支持内存限制（使用cachetools风格）
    """
    
    # 默认最大内存使用（100MB）
    DEFAULT_MAX_MEMORY_BYTES = 100 * 1024 * 1024
    
    def __init__(self, node_id: str = None, max_size: int = 1000, max_memory_bytes: int = None):
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = Lock()
        self._async_lock = asyncio.Lock()  # 异步锁，用于异步操作
        self._max_size = max_size  # 最大缓存条目数
        self._max_memory_bytes = max_memory_bytes or self.DEFAULT_MAX_MEMORY_BYTES  # 最大内存使用
        self._current_memory_bytes = 0  # 当前内存使用
        # 统计信息
        self._hits = 0
        self._misses = 0
        # 集群支持
        self._node_id = node_id or f"node-{id(self)}"
        # _subscriptions: 当前节点订阅的其他节点（当这些节点更新时，我们收到通知）
        self._subscriptions: Dict[str, 'MemoryCache'] = {}
        # _subscribers: 订阅当前节点的 other nodes（当当前节点更新时，通知它们）
        self._subscribers: Dict[str, 'MemoryCache'] = {}
    
    def set_node_id(self, node_id: str) -> None:
        """设置节点ID"""
        self._node_id = node_id
    
    def get_node_id(self) -> str:
        """获取节点ID"""
        return self._node_id
    
    def subscribe(self, other_cache: 'MemoryCache') -> None:
        """订阅另一个缓存节点的更新"""
        # 记录我们订阅了哪个节点
        self._subscriptions[other_cache._node_id] = other_cache
        # 注册到对方的订阅者列表，这样对方更新时会通知我们
        other_cache._subscribers[self._node_id] = self
    
    def unsubscribe(self, node_id: str) -> None:
        """取消订阅"""
        # 从我们的订阅列表中移除
        if node_id in self._subscriptions:
            other_cache = self._subscriptions[node_id]
            del self._subscriptions[node_id]
            # 从对方的订阅者列表中移除我们
            if self._node_id in other_cache._subscribers:
                del other_cache._subscribers[self._node_id]
    
    def _notify_subscribers(self, operation: str, key: str, value: Any = None) -> None:
        """通知订阅者缓存变更"""
        for node_id, subscriber in self._subscribers.items():
            try:
                if operation == "delete":
                    subscriber._handle_remote_delete(key)
                elif operation == "clear":
                    subscriber._handle_remote_clear()
                elif operation == "set":
                    subscriber._handle_remote_set(key, value)
                elif operation == "invalidate":
                    subscriber._handle_remote_invalidate(key)
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
    
    def _handle_remote_invalidate(self, key: str) -> None:
        """处理远程失效通知（不清除本地，只是标记失效）"""
        # 不做任何操作，只是通知
        # 订阅者可以自行决定如何处理（例如重新从数据源获取）
        pass
    
    def _handle_remote_set(self, key: str, value: Any) -> None:
        """处理远程设置通知"""
        with self._lock:
            # 直接设置值，保持原 TTL
            if key in self._cache:
                old_entry = self._cache[key]
                self._cache[key] = CacheEntry(value, old_entry.ttl)
            else:
                self._cache[key] = CacheEntry(value, 300)  # 默认 TTL
    
    def _estimate_value_size(self, value: Any) -> int:
        """
        估算值的大小（字节）
        
        使用 sys.getsizeof 估算，对字符串和字典进行更精确的计算
        """
        try:
            # 对于字符串，计算实际字节数
            if isinstance(value, str):
                return len(value.encode('utf-8'))
            # 对于字典/列表，序列化为JSON后计算大小
            elif isinstance(value, (dict, list)):
                return len(json.dumps(value).encode('utf-8'))
            # 其他类型使用 getsizeof
            else:
                return sys.getsizeof(value)
        except Exception:
            # 出错时返回保守估计
            return 1024
    
    def _evict_if_needed(self) -> None:
        """当缓存满时淘汰最旧的条目（LRU），同时检查内存限制"""
        # 检查条目数限制
        while len(self._cache) >= self._max_size:
            # 弹出最旧的条目（OrderedDict 头部）
            key, entry = self._cache.popitem(last=False)
            self._current_memory_bytes -= self._estimate_value_size(entry.value)
        
        # 检查内存限制
        while self._current_memory_bytes > self._max_memory_bytes and self._cache:
            # 弹出最旧的条目
            key, entry = self._cache.popitem(last=False)
            self._current_memory_bytes -= self._estimate_value_size(entry.value)
        
        # 确保内存计数不会为负
        self._current_memory_bytes = max(0, self._current_memory_bytes)
    
    def get(self, key: str, default: Any = None) -> Optional[Any]:
        """获取缓存值"""
        with self._lock:
            if key not in self._cache:
                self._misses += 1
                logger.debug("Cache miss | key=%s | backend=memory", key)
                return default
            
            entry = self._cache[key]
            if entry.is_expired():
                del self._cache[key]
                self._misses += 1
                # Handle infinite TTL case
                remaining_ttl = entry.get_remaining_ttl() if entry.expire_at != float('inf') else -1
                logger.debug("Cache expired | key=%s | backend=memory | ttl_remaining=%d", 
                           key, remaining_ttl)
                return default
            
            # 移动到末尾（表示最近使用）
            self._cache.move_to_end(key)
            self._hits += 1
            # Handle infinite TTL case
            remaining_ttl = entry.get_remaining_ttl() if entry.expire_at != float('inf') else -1
            logger.debug("Cache hit | key=%s | backend=memory | remaining_ttl=%d", 
                        key, remaining_ttl)
            return entry.value
    
    def set(self, key: str, value: Any, ttl: int = 300) -> None:
        """设置缓存值"""
        value_size = 0
        is_update = False
        with self._lock:
            # 如果key已存在，先删除（更新位置）
            if key in self._cache:
                old_entry = self._cache[key]
                self._current_memory_bytes -= self._estimate_value_size(old_entry.value)
                del self._cache[key]
                is_update = True
            
            # 估算新值的大小
            value_size = self._estimate_value_size(value)
            
            # 检查是否需要淘汰
            self._evict_if_needed()
            
            # 再次检查内存（如果单个值就超过限制，强制设置）
            while value_size > self._max_memory_bytes and self._cache:
                # 淘汰多个条目
                _, old_entry = self._cache.popitem(last=False)
                self._current_memory_bytes -= self._estimate_value_size(old_entry.value)
            
            self._cache[key] = CacheEntry(value, ttl)
            self._current_memory_bytes += value_size
            # 移动到末尾（最新）
            self._cache.move_to_end(key)
        
        # 在锁外通知订阅者，避免死锁
        self._notify_subscribers("set", key, value)
        
        logger.info("Cache set | key=%s | ttl=%d | size_bytes=%d | update=%s | backend=memory",
                   key, ttl, value_size, is_update)
    
    def delete(self, key: str) -> bool:
        """删除缓存"""
        deleted = False
        with self._lock:
            if key in self._cache:
                entry = self._cache[key]
                self._current_memory_bytes -= self._estimate_value_size(entry.value)
                del self._cache[key]
                deleted = True
                # 在锁外通知订阅者
                self._notify_subscribers("delete", key)
        
        if deleted:
            logger.info("Cache delete | key=%s | backend=memory", key)
        return deleted
    
    def clear(self) -> None:
        """清空所有缓存"""
        with self._lock:
            item_count = len(self._cache)
            self._cache.clear()
            self._current_memory_bytes = 0
            self._hits = 0
            self._misses = 0
        # 在锁外通知订阅者
        self._notify_subscribers("clear", "")
        logger.info("Cache clear | items_cleared=%d | backend=memory", item_count)
    
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
                "memory_bytes": self._current_memory_bytes,
                "memory_mb": round(self._current_memory_bytes / (1024 * 1024), 2),
                "max_memory_bytes": self._max_memory_bytes,
                "max_memory_mb": round(self._max_memory_bytes / (1024 * 1024), 2),
                "memory_usage_percent": round(self._current_memory_bytes / self._max_memory_bytes * 100, 2) if self._max_memory_bytes > 0 else 0,
            }
    
    def keys(self) -> list:
        """获取所有缓存键"""
        with self._lock:
            return list(self._cache.keys())
    
    # ============ 异步安全方法 ============
    
    async def aget(self, key: str, default: Any = None) -> Optional[Any]:
        """异步获取缓存值（线程安全 + 异步安全）"""
        async with self._async_lock:
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
    
    async def aset(self, key: str, value: Any, ttl: int = 300) -> None:
        """异步设置缓存值（线程安全 + 异步安全）"""
        async with self._async_lock:
            # 如果key已存在，先删除（更新位置）
            if key in self._cache:
                del self._cache[key]
            
            # 检查是否需要淘汰
            self._evict_if_needed()
            
            self._cache[key] = CacheEntry(value, ttl)
            # 移动到末尾（最新）
            self._cache.move_to_end(key)
    
    async def adelete(self, key: str) -> bool:
        """异步删除缓存（线程安全 + 异步安全）"""
        async with self._async_lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False


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
    
    async def acquire_lock(
        self, 
        key: str, 
        timeout: int = 10,
        expire: int = 30
    ) -> bool:
        """
        获取分布式锁（用于缓存击穿保护）
        
        Args:
            key: 锁的键
            timeout: 获取锁的超时时间（秒）
            expire: 锁的过期时间（秒）
            
        Returns:
            是否成功获取锁
        """
        if not self._connected:
            return False
        
        try:
            redis = self._get_redis()
            if redis is None:
                return False
            
            lock_key = f"lock:{key}"
            # 使用 SETNX 实现分布式锁
            acquired = await redis.set(
                lock_key,
                "1",
                nx=True,
                ex=expire
            )
            return bool(acquired)
        except Exception as e:
            logger.error(f"Failed to acquire distributed lock: {e}")
            return False
    
    async def release_lock(self, key: str) -> bool:
        """
        释放分布式锁
        
        Args:
            key: 锁的键
            
        Returns:
            是否成功释放锁
        """
        if not self._connected:
            return False
        
        try:
            redis = self._get_redis()
            if redis is None:
                return False
            
            lock_key = f"lock:{key}"
            await redis.delete(lock_key)
            return True
        except Exception as e:
            logger.error(f"Failed to release distributed lock: {e}")
            return False
    
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
        
        # Redis 重连定时器
        self._redis_reconnect_task = None
        self._redis_reconnect_interval = 60  # 60秒
        
        # 缓存击穿保护 - 异步锁字典（每个key一个锁）
        self._cache_locks: Dict[str, asyncio.Lock] = {}
        self._locks_lock = asyncio.Lock()
    
    async def _get_cache_lock(self, key: str) -> asyncio.Lock:
        """获取指定key的锁（缓存击穿保护）"""
        async with self._locks_lock:
            if key not in self._cache_locks:
                self._cache_locks[key] = asyncio.Lock()
            return self._cache_locks[key]
    
    async def aget_with_protection(
        self, 
        key: str, 
        default: Any = None,
        fetch_callback: Optional[Callable] = None,
        ttl: int = 300
    ) -> Any:
        """
        带击穿保护的异步获取缓存值
        
        当缓存不存在时，使用互斥锁防止缓存击穿（大量请求同时访问不存在的缓存键）
        
        Args:
            key: 缓存键
            default: 默认值
            fetch_callback: 获取数据的回调函数（可选），用于缓存不存在时加载数据
            ttl: 缓存过期时间（秒）
            
        Returns:
            缓存值或默认值
        """
        # 先尝试直接获取缓存
        cached_value = await self.aget(key)
        if cached_value is not None:
            return cached_value
        
        # 缓存不存在，获取锁并防止击穿
        lock = await self._get_cache_lock(key)
        async with lock:
            # 双重检查：获取锁后再检查一次缓存（可能其他请求已经加载了）
            cached_value = await self.aget(key)
            if cached_value is not None:
                return cached_value
            
            # 缓存确实不存在，如果提供了回调函数，则加载数据
            if fetch_callback:
                try:
                    value = await fetch_callback()
                    # 设置缓存
                    await self.aset(key, value, ttl)
                    return value
                except Exception as e:
                    logger.error(f"Failed to fetch data for cache key {key}: {e}")
                    return default
            
            return default
    
    async def initialize(self, max_retries: int = 3, retry_delay: float = 1.0) -> None:
        """
        初始化缓存（带重试机制）
        
        Args:
            max_retries: 最大重试次数
            retry_delay: 重试延迟（秒），支持指数退避
        """
        connected = False
        
        if self._backend == CacheBackend.REDIS:
            last_error = None
            
            for attempt in range(max_retries):
                try:
                    self._redis_cache = RedisCache(self._redis_url)
                    connected = await self._redis_cache.connect()
                    
                    if connected:
                        self._current_backend = CacheBackend.REDIS
                        logger.info(f"Cache initialized with Redis (attempt {attempt + 1})")
                        break
                    else:
                        last_error = "Connection failed"
                except Exception as e:
                    last_error = str(e)
                    logger.warning(f"Redis initialization attempt {attempt + 1} failed: {e}")
                
                # 等待后重试（指数退避）
                if attempt < max_retries - 1:
                    delay = retry_delay * (2 ** attempt)  # 1s, 2s, 4s
                    logger.info(f"Retrying in {delay}s...")
                    await asyncio.sleep(delay)
            
            # 所有重试都失败，回退到内存缓存
            if not connected:
                if self._fallback_to_memory:
                    logger.warning(f"Redis connection failed after {max_retries} attempts, falling back to memory cache")
                    self._current_backend = CacheBackend.MEMORY
                else:
                    raise RuntimeError(f"Failed to connect to Redis after {max_retries} attempts and fallback is disabled")
        
        logger.info(f"Cache initialized with backend: {self._current_backend.value}")
        
        # 启动自动清理任务（仅内存缓存）
        await self._start_cleanup_task()
        
        # 启动 Redis 重连任务
        await self._start_redis_reconnect_task()
        
        # 预热缓存
        await self.warmup_cache()
    
    async def _start_redis_reconnect_task(self) -> None:
        """启动 Redis 定时重连任务"""
        if self._backend != CacheBackend.REDIS:
            return
        
        async def reconnect_loop():
            while True:
                await asyncio.sleep(self._redis_reconnect_interval)
                reconnect_start = time.time()
                
                # 检查 Redis 连接状态
                if self._current_backend == CacheBackend.MEMORY:
                    # 如果当前使用的是内存缓存，尝试重连
                    try:
                        logger.info("Attempting to reconnect to Redis | url=%s", self._redis_url.replace(self._redis_url.split('@')[-1] if '@' in self._redis_url else '', '***'))
                        self._redis_cache = RedisCache(self._redis_url)
                        connected = await self._redis_cache.connect()
                        
                        if connected:
                            self._current_backend = CacheBackend.REDIS
                            logger.info("Redis reconnected successfully | backend=redis | attempt_time=%.2fs", 
                                       time.time() - reconnect_start)
                            # 重置缓存统计
                            self._memory_cache.clear()
                        else:
                            logger.warning("Redis reconnection failed, will retry next interval")
                    except Exception as e:
                        logger.error("Redis reconnection error | error=%s", str(e))
                else:
                    # 如果当前使用的是 Redis，检查连接是否正常
                    if self._redis_cache and not await self._check_redis_health():
                        logger.warning("Redis connection lost, falling back to memory cache")
                        self._current_backend = CacheBackend.MEMORY
                        if self._redis_cache:
                            await self._redis_cache.disconnect()
        
        # 创建后台任务
        asyncio.create_task(reconnect_loop())
        logger.info(f"Redis reconnect task started (interval: {self._redis_reconnect_interval}s)")
    
    async def _check_redis_health(self) -> bool:
        """检查 Redis 连接健康状态"""
        try:
            if self._redis_cache:
                return await self._redis_cache.connect()
        except Exception:
            pass
        return False
    
    async def reconnect_redis(self) -> bool:
        """
        手动触发 Redis 重连
        
        Returns:
            是否重连成功
        """
        if self._backend != CacheBackend.REDIS:
            logger.info("Backend is not Redis, skipping reconnection")
            return False
        
        try:
            if self._redis_cache:
                await self._redis_cache.disconnect()
            
            self._redis_cache = RedisCache(self._redis_url)
            connected = await self._redis_cache.connect()
            
            if connected:
                self._current_backend = CacheBackend.REDIS
                logger.info("Manual Redis reconnection successful")
                return True
            else:
                logger.warning("Manual Redis reconnection failed")
                return False
        except Exception as e:
            logger.error(f"Manual Redis reconnection error: {e}")
            return False
    
    def _get_ttl_with_jitter(self, ttl: int) -> int:
        """
        获取带随机抖动的 TTL，防止缓存雪崩
        
        为 TTL 添加 ±10% 的随机抖动，防止大量缓存在同一时间过期
        
        Args:
            ttl: 原始 TTL（秒）
            
        Returns:
            带抖动的 TTL（秒）
        """
        jitter = random.uniform(0.9, 1.1)
        return int(ttl * jitter)
    
    async def warmup_cache(self) -> None:
        """
        预热缓存 - 启动时加载热门数据
        
        在服务启动时预热热门物品和价格数据缓存，减少冷启动影响
        """
        logger.info("Starting cache warmup...")
        
        try:
            from app.core.database import engine
            from sqlalchemy import select, text
            from app.models.item import Item
            
            # 先检查 items 表是否存在
            async with engine.connect() as conn:
                try:
                    # 尝试执行一个简单查询来验证表是否存在
                    await conn.execute(text("SELECT 1 FROM items LIMIT 1"))
                except Exception:
                    # 表不存在，跳过预热
                    logger.info("Items table not found, skipping cache warmup")
                    return
            
            async with engine.connect() as conn:
                # 预热热门物品缓存（按交易量排序的前20个）
                popular_items_query = select(Item).order_by(Item.volume_24h.desc()).limit(20)
                result = await conn.execute(popular_items_query)
                popular_items = result.scalars().all()
                
                if popular_items:
                    # 设置热门物品缓存，带随机抖动
                    items_data = [
                        {
                            "id": item.id,
                            "name": item.name,
                            "current_price": item.current_price,
                            "volume_24h": item.volume_24h
                        }
                        for item in popular_items
                    ]
                    ttl_with_jitter = self._get_ttl_with_jitter(ITEMS_CACHE_TTL)
                    self.set(ITEMS_CACHE_KEY, items_data, ttl_with_jitter)
                    logger.info(f"Warmed up popular items cache with {len(items_data)} items")
                
                # 预热价格数据缓存（热门物品的价格）
                price_items_query = select(Item).order_by(Item.volume_24h.desc()).limit(50)
                result = await conn.execute(price_items_query)
                price_items = result.scalars().all()
                
                if price_items:
                    price_data = {}
                    for item in price_items:
                        price_data[item.id] = {
                            "price": item.current_price,
                            "steam_price": item.steam_lowest_price,
                            "updated_at": item.updated_at.isoformat() if item.updated_at else None
                        }
                    
                    ttl_with_jitter = self._get_ttl_with_jitter(PRICE_CACHE_TTL)
                    self.set("price:warmup", price_data, ttl_with_jitter)
                    logger.info(f"Warmed up price cache with {len(price_data)} items")
            
            logger.info("Cache warmup completed")
            
        except Exception as e:
            logger.warning(f"Cache warmup failed: {e}")
        
    async def _start_cleanup_task(self) -> None:
        """启动后台清理任务（带重试机制）"""
        if self._current_backend == CacheBackend.MEMORY:
            import asyncio
            
            # 清理任务配置
            cleanup_config = {
                "interval": 300,  # 5分钟
                "max_retries": 3,
                "retry_delay": 5,  # 重试延迟（秒）
            }
            
            async def cleanup_loop():
                while True:
                    await asyncio.sleep(cleanup_config["interval"])
                    await self._execute_cleanup_with_retry(cleanup_config["max_retries"], cleanup_config["retry_delay"])
            
            # 创建后台任务（不阻塞启动）
            asyncio.create_task(cleanup_loop())
    
    async def _execute_cleanup_with_retry(self, max_retries: int = 3, retry_delay: int = 5) -> None:
        """执行清理任务（带重试机制）"""
        backend_name = self._current_backend.value
        
        for attempt in range(max_retries):
            try:
                cache_cleanup_status.labels(backend=backend_name).set(1)  # running
                
                start_time = time.time()
                
                # 执行清理
                cleaned = self._memory_cache.cleanup_expired()
                duration = time.time() - start_time
                
                # 更新指标
                cache_cleanup_duration.labels(backend=backend_name).observe(duration)
                cache_entries_cleaned.labels(backend=backend_name).set(cleaned)
                cache_cleanup_total.labels(backend=backend_name, result="success").inc()
                cache_cleanup_status.labels(backend=backend_name).set(0)  # idle
                
                # 更新过期条目计数
                cache_expired_entries.labels(backend=backend_name).set(0)
                
                logger.info("Cache cleanup completed | backend=%s | cleaned=%d | duration=%.2fs | attempt=%d",
                           backend_name, cleaned, duration, attempt + 1)
                
                return  # 成功退出
                
            except Exception as e:
                logger.error(f"Cache cleanup attempt {attempt + 1} failed: {e}")
                cache_cleanup_total.labels(backend=backend_name, result="error").inc()
                
                if attempt < max_retries - 1:
                    # 指数退避
                    delay = retry_delay * (2 ** attempt)
                    logger.info(f"Retrying cleanup in {delay}s...")
                    await asyncio.sleep(delay)
        
        # 所有重试都失败
        cache_cleanup_status.labels(backend=backend_name).set(2)  # error
        logger.error(f"Cache cleanup failed after {max_retries} attempts")

    def get_cleanup_status(self) -> Dict[str, Any]:
        """获取清理任务状态"""
        backend_name = self._current_backend.value
        status_value = cache_cleanup_status.labels(backend=backend_name)._value if PROMETHEUS_AVAILABLE else 0
        
        status_map = {
            0: "idle",
            1: "running",
            2: "error"
        }
        
        return {
            "backend": backend_name,
            "status": status_map.get(status_value, "unknown"),
            "status_code": status_value,
            "prometheus_available": PROMETHEUS_AVAILABLE
        }
    
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
        # 添加 TTL 抖动防止缓存雪崩
        ttl_with_jitter = self._get_ttl_with_jitter(ttl)
        
        if self._current_backend == CacheBackend.REDIS and self._redis_cache:
            try:
                self._redis_cache.set(key, value, ttl_with_jitter)
                return
            except Exception as e:
                logger.error(f"Redis set failed, falling back to memory: {e}")
                if self._fallback_to_memory:
                    pass  # 继续使用内存缓存
                else:
                    raise
        
        self._memory_cache.set(key, value, ttl_with_jitter)
    
    async def aset(self, key: str, value: Any, ttl: int = 300) -> None:
        """异步设置缓存值"""
        # 添加 TTL 抖动防止缓存雪崩
        ttl_with_jitter = self._get_ttl_with_jitter(ttl)
        
        if self._current_backend == CacheBackend.REDIS and self._redis_cache:
            try:
                await self._redis_cache.aset(key, value, ttl_with_jitter)
                return
            except Exception as e:
                logger.error(f"Redis async set failed, falling back to memory: {e}")
                if self._fallback_to_memory:
                    pass
                else:
                    raise
        
        self._memory_cache.set(key, value, ttl_with_jitter)
    
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
            stats["cleanup_status"] = self.get_cleanup_status()
            return stats
        
        stats = self._memory_cache.get_stats()
        stats["backend"] = self._current_backend.value
        stats["cleanup_status"] = self.get_cleanup_status()
        
        # 更新 Prometheus 缓存大小指标
        if PROMETHEUS_AVAILABLE:
            cache_size.labels(backend=self._current_backend.value).set(stats["total_keys"])
        
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
            # 双向订阅：双方都订阅对方的更新
            self._memory_cache.subscribe(other_cache._memory_cache)
            other_cache._memory_cache.subscribe(self._memory_cache)
            logger.info(f"Registered to cluster with node: {other_cache.get_node_id()}")
    
    def broadcast_invalidation(self, key: str) -> None:
        """广播缓存失效通知到集群"""
        if self._current_backend == CacheBackend.MEMORY:
            # 使用 invalidate 操作，通知订阅者但不清除本地
            self._memory_cache._notify_subscribers("invalidate", key)
            logger.debug(f"Broadcast cache invalidation for key: {key}")
    
    def broadcast_clear(self) -> None:
        """广播缓存清空通知到集群"""
        if self._current_backend == CacheBackend.MEMORY:
            # 清空本地
            self._memory_cache.clear()
            # 通知订阅者
            self._memory_cache._notify_subscribers("clear", "")
            logger.debug("Broadcast cache clear to cluster")


# 全局缓存实例
_cache: Optional[CacheManager] = None
_cache_initialized: bool = False


def is_cache_initialized() -> bool:
    """检查缓存是否已初始化"""
    global _cache_initialized
    return _cache_initialized


async def init_cache() -> CacheManager:
    """
    初始化缓存实例（异步安全）
    
    使用双重检查锁定模式确保:
    1. 只有一个协程执行初始化
    2. 其他协程在初始化完成前等待
    3. 初始化完成后直接返回已初始化的实例
    """
    global _cache, _cache_initialized
    
    # 快速路径：如果已初始化，直接返回
    if _cache_initialized and _cache is not None:
        return _cache
    
    from app.core.config import settings
    
    backend = CacheBackend.MEMORY
    if settings.REDIS_URL:
        backend = CacheBackend.REDIS
    
    _cache = CacheManager(
        backend=backend,
        redis_url=settings.REDIS_URL if hasattr(settings, 'REDIS_URL') else None
    )
    await _cache.initialize()
    _cache_initialized = True
    logger.info("Cache initialized via init_cache()")

    return _cache


async def ensure_cache_initialized() -> CacheManager:
    """
    确保缓存已初始化，如未初始化则初始化（异步安全）
    
    这是获取缓存实例的推荐方式，确保在异步上下文中安全使用
    """
    global _cache_initialized
    if not _cache_initialized:
        return await init_cache()
    return get_cache()


def get_cache() -> CacheManager:
    """
    获取全局缓存实例
    
    注意：在异步环境中，建议使用 await ensure_cache_initialized() 代替
    此函数仅用于保持向后兼容性和非异步环境
    """
    global _cache
    if _cache is None:
        import warnings
        warnings.warn(
            "get_cache() called without prior initialization. "
            "Consider using 'await ensure_cache_initialized()' instead.",
            DeprecationWarning,
            stacklevel=2
        )
        
        # 从配置读取
        from app.core.config import settings
        
        backend = CacheBackend.MEMORY
        if settings.REDIS_URL:
            backend = CacheBackend.REDIS
        
        _cache = CacheManager(
            backend=backend,
            redis_url=settings.REDIS_URL if hasattr(settings, 'REDIS_URL') else None
        )
        # 尝试同步初始化（仅在没有运行中事件循环时使用）
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            # 在异步环境中使用 ensure_cache_initialized
            # 这里不做任何操作，让调用者使用 ensure_cache_initialized
            logger.warning("get_cache() called in async context without initialization")
        except RuntimeError:
            # 没有运行中的事件循环，可以安全创建新的
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(_cache.initialize())
                loop.close()
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
    # 规范化键
    normalized_key = normalize_cache_key(key)
    cache = get_cache()
    return cache.get(normalized_key, default)


def set(key: str, value: Any, ttl: int = 300) -> None:
    """设置缓存值"""
    # 规范化键
    normalized_key = normalize_cache_key(key)
    cache = get_cache()
    cache.set(normalized_key, value, ttl)


async def aset(key: str, value: Any, ttl: int = 300) -> None:
    """异步设置缓存值"""
    # 规范化键
    normalized_key = normalize_cache_key(key)
    cache = get_cache()
    await cache.aset(normalized_key, value, ttl)


def delete(key: str) -> bool:
    """删除缓存"""
    # 规范化键
    normalized_key = normalize_cache_key(key)
    cache = get_cache()
    return cache.delete(normalized_key)


async def adelete(key: str) -> bool:
    """异步删除缓存"""
    # 规范化键
    normalized_key = normalize_cache_key(key)
    cache = get_cache()
    return await cache.adelete(normalized_key)


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


# ============ 缓存键规范化 ============

# 缓存键前缀
CACHE_KEY_PREFIX = "cs2:"

# 缓存键正则（只允许字母、数字、下划线和冒号）
import re
_CACHE_KEY_PATTERN = re.compile(r'^[a-zA-Z0-9_:]+$')


def normalize_cache_key(key: str) -> str:
    """
    规范化缓存键
    
    - 添加前缀以避免键冲突
    - 验证键格式
    
    Args:
        key: 原始缓存键
        
    Returns:
        规范化后的缓存键
        
    Raises:
        ValueError: 键格式不正确
    """
    if not key:
        raise ValueError("Cache key cannot be empty")
    
    # 验证键格式
    if not _CACHE_KEY_PATTERN.match(key):
        raise ValueError(f"Invalid cache key format: {key}")
    
    # 如果没有前缀，添加前缀
    if not key.startswith(CACHE_KEY_PREFIX):
        return f"{CACHE_KEY_PREFIX}{key}"
    
    return key


def validate_cache_key(key: str) -> bool:
    """
    验证缓存键是否有效
    
    Args:
        key: 缓存键
        
    Returns:
        是否有效
    """
    if not key:
        return False
    return _CACHE_KEY_PATTERN.match(key) is not None


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
