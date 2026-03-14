# -*- coding: utf-8 -*-
"""
缓存服务单元测试
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
import time

from app.services.cache import (
    CacheManager,
    CacheBackend,
    MemoryCache,
    RedisCache,
    init_cache,
    get_cache,
    is_cache_initialized,
    ensure_cache_initialized,
)


class TestMemoryCache:
    """内存缓存测试"""
    
    @pytest.fixture
    def cache(self):
        """创建内存缓存实例"""
        # 禁用随机抖动以确保测试稳定性
        from app.services.cache import CacheEntry
        original_jitter = CacheEntry._enable_jitter
        CacheEntry.set_jitter_enabled(False)
        
        cache = MemoryCache(max_size=100)
        
        # 测试完成后恢复原始设置
        yield cache
        CacheEntry.set_jitter_enabled(original_jitter)
    
    def test_set_and_get(self, cache):
        """测试设置和获取缓存"""
        cache.set("key1", "value1", ttl=60)
        result = cache.get("key1")
        
        assert result == "value1"
    
    def test_get_default(self, cache):
        """测试获取不存在的键返回默认值"""
        result = cache.get("nonexistent", default="default_value")
        
        assert result == "default_value"
    
    def test_delete(self, cache):
        """测试删除缓存"""
        cache.set("key1", "value1")
        
        result = cache.delete("key1")
        assert result is True
        
        result = cache.get("key1")
        assert result is None
    
    def test_ttl_expiration(self, cache):
        """测试TTL过期"""
        cache.set("key1", "value1", ttl=1)
        
        # 立即获取应该存在
        assert cache.get("key1") == "value1"
        
        # 等待过期
        time.sleep(1.1)
        
        # 过期后应该返回None
        assert cache.get("key1") is None
    
    def test_lru_eviction(self, cache):
        """测试LRU淘汰"""
        # 创建一个小缓存
        cache = MemoryCache(max_size=3)
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        
        # 触发淘汰
        cache.set("key3", "value3")
        cache.set("key4", "value4")
        
        # 最旧的键应该被淘汰
        assert cache.get("key1") is None
        assert cache.get("key2") is not None
    
    def test_get_stats(self, cache):
        """测试获取统计信息"""
        cache.set("key1", "value1")
        cache.get("key1")  # hit
        cache.get("key2")  # miss
        
        stats = cache.get_stats()
        
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["total_keys"] == 1
    
    def test_clear(self, cache):
        """测试清空缓存"""
        cache.set("key1", "value1")
        cache.clear()
        
        # 获取stats在get()之前，确保测试clear()重置了统计
        stats = cache.get_stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        
        # 然后验证get返回None
        assert cache.get("key1") is None


class TestCacheManager:
    """缓存管理器测试"""
    
    @pytest.mark.asyncio
    async def test_initialize_memory_backend(self):
        """测试初始化内存缓存后端"""
        manager = CacheManager(backend=CacheBackend.MEMORY)
        await manager.initialize()
        
        assert manager.backend == CacheBackend.MEMORY
        # 清理后台任务
        await manager.shutdown()
    
    @pytest.mark.asyncio
    async def test_set_and_get(self):
        """测试设置和获取"""
        manager = CacheManager(backend=CacheBackend.MEMORY)
        await manager.initialize()
        
        manager.set("key1", "value1", ttl=60)
        result = manager.get("key1")
        
        assert result == "value1"
        # 清理后台任务
        await manager.shutdown()
    
    @pytest.mark.asyncio
    async def test_delete(self):
        """测试删除"""
        manager = CacheManager(backend=CacheBackend.MEMORY)
        await manager.initialize()
        
        manager.set("key1", "value1")
        result = manager.delete("key1")
        
        assert result is True
        assert manager.get("key1") is None
        # 清理后台任务
        await manager.shutdown()
    
    @pytest.mark.asyncio
    async def test_get_stats(self):
        """测试获取统计信息"""
        manager = CacheManager(backend=CacheBackend.MEMORY)
        await manager.initialize()
        
        manager.set("key1", "value1")
        manager.get("key1")
        
        stats = manager.get_stats()
        
        assert stats["backend"] == "memory"
        assert stats["total_keys"] == 1
        # 清理后台任务
        await manager.shutdown()


class TestCacheInitialization:
    """缓存初始化测试"""
    
    def test_is_cache_initialized_false(self):
        """测试初始状态未初始化"""
        import app.services.cache as cache_module
        cache_module._cache_initialized = False
        
        assert is_cache_initialized() is False
    
    @pytest.mark.asyncio
    async def test_init_cache_creates_instance(self):
        """测试init_cache创建缓存实例"""
        import app.services.cache as cache_module
        
        cache_module._cache = None
        cache_module._cache_initialized = False
        
        cache = await init_cache()
        
        assert cache is not None
        assert is_cache_initialized() is True
        # 清理后台任务
        await cache.shutdown()
    
    @pytest.mark.asyncio
    async def test_ensure_cache_initialized(self):
        """测试ensure_cache_initialized确保初始化"""
        import app.services.cache as cache_module
        
        cache_module._cache = None
        cache_module._cache_initialized = False
        
        cache = await ensure_cache_initialized()
        
        assert cache is not None
        assert is_cache_initialized() is True
        # 清理后台任务
        await cache.shutdown()
    
    def test_get_cache_returns_same_instance(self):
        """测试get_cache返回同一实例"""
        # 先禁用随机抖动以确保测试稳定性
        from app.services.cache import CacheEntry
        original_jitter = CacheEntry._enable_jitter
        CacheEntry.set_jitter_enabled(False)
        
        cache1 = get_cache()
        cache2 = get_cache()
        
        assert cache1 is cache2
        
        # 恢复原始设置
        CacheEntry.set_jitter_enabled(original_jitter)


@pytest.fixture(scope="session", autouse=True)
def cleanup_global_cache():
    """在测试会话结束时清理全局缓存"""
    yield
    # 测试结束后清理全局缓存的后台任务
    import app.services.cache as cache_module
    if cache_module._cache is not None:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(cache_module._cache.shutdown())
            else:
                asyncio.run(cache_module._cache.shutdown())
        except Exception:
            pass
        CacheEntry.set_jitter_enabled(original_jitter)
