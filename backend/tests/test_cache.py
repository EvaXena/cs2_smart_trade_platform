# -*- coding: utf-8 -*-
"""
缓存服务测试
"""
import pytest
import time
from app.services.cache import (
    MemoryCache,
    get,
    set,
    delete,
    clear,
    get_stats,
    get_popular_items,
    set_popular_items,
    get_cached_price,
    set_cached_price,
)


class TestMemoryCache:
    """内存缓存测试"""
    
    def test_set_and_get(self):
        """测试设置和获取"""
        cache = MemoryCache()
        cache.set("key1", "value1", ttl=60)
        assert cache.get("key1") == "value1"
    
    def test_get_nonexistent(self):
        """测试获取不存在的键"""
        cache = MemoryCache()
        assert cache.get("nonexistent") is None
    
    def test_get_with_default(self):
        """测试获取不存在的键返回默认值"""
        cache = MemoryCache()
        result = cache.get("nonexistent")
        assert result is None
    
    def test_expired_entry(self):
        """测试过期条目"""
        cache = MemoryCache()
        # 使用较长TTL避免雪崩保护抖动导致的测试不稳定
        cache.set("key1", "value1", ttl=2)
        time.sleep(2.5)
        assert cache.get("key1") is None
    
    def test_delete(self):
        """测试删除"""
        cache = MemoryCache()
        cache.set("key1", "value1")
        assert cache.delete("key1") is True
        assert cache.get("key1") is None
    
    def test_delete_nonexistent(self):
        """测试删除不存在的键"""
        cache = MemoryCache()
        assert cache.delete("nonexistent") is False
    
    def test_clear(self):
        """测试清空"""
        cache = MemoryCache()
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.clear()
        assert cache.get("key1") is None
        assert cache.get("key2") is None
    
    def test_cleanup_expired(self):
        """测试清理过期条目"""
        cache = MemoryCache()
        # 使用较长TTL避免雪崩保护抖动导致的测试不稳定
        cache.set("key1", "value1", ttl=2)
        time.sleep(2.5)
        cache.set("key2", "value2", ttl=2)
        time.sleep(2.5)
        cleaned = cache.cleanup_expired()
        assert cleaned >= 1
    
    def test_stats(self):
        """测试统计信息"""
        cache = MemoryCache()
        cache.set("key1", "value1")
        cache.get("key1")  # hit
        cache.get("key2")  # miss
        
        stats = cache.get_stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["hit_rate"] == 50.0


class TestCacheFunctions:
    """缓存便捷函数测试"""
    
    def test_get_set_functions(self):
        """测试便捷函数"""
        clear()  # 先清空
        set("test_key", "test_value", ttl=60)
        assert get("test_key") == "test_value"
        assert get("nonexistent") is None
        assert get("nonexistent", "default") == "default"
    
    def test_delete_function(self):
        """测试删除函数"""
        clear()
        set("key1", "value1")
        assert delete("key1") is True
        assert get("key1") is None
    
    def test_popular_items_cache(self):
        """测试热门物品缓存"""
        clear()
        items = [{"id": 1, "name": "AK-47"}, {"id": 2, "name": "M4A4"}]
        set_popular_items(items)
        cached = get_popular_items()
        assert cached == items
    
    def test_price_cache(self):
        """测试价格缓存"""
        clear()
        set_cached_price("item_123", 100.5)
        assert get_cached_price("item_123") == 100.5
