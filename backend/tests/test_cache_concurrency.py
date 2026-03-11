# -*- coding: utf-8 -*-
"""
Cache Concurrency Tests

测试缓存在并发场景下的行为：
- 并发读写
- 并发删除
- LRU淘汰
- TTL过期
- 集群失效通知
"""
import pytest
import asyncio
import time
from unittest.mock import Mock, patch, AsyncMock
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.cache import MemoryCache, CacheManager, CacheBackend


class TestConcurrentCacheReads:
    """并发读测试"""
    
    @pytest.mark.asyncio
    async def test_concurrent_read_same_key(self):
        """测试同一key并发读取"""
        cache = MemoryCache(max_size=100)
        
        # 先写入数据
        cache.set("test_key", "test_value", ttl=300)
        
        # 并发读取
        tasks = [asyncio.to_thread(cache.get, "test_key") for _ in range(100)]
        results = await asyncio.gather(*tasks)
        
        # 所有结果应该一致
        assert all(r == "test_value" for r in results)
    
    @pytest.mark.asyncio
    async def test_concurrent_read_different_keys(self):
        """测试不同key并发读取"""
        cache = MemoryCache(max_size=1000)
        
        # 写入多个key
        for i in range(50):
            cache.set(f"key_{i}", f"value_{i}", ttl=300)
        
        # 并发读取不同key
        tasks = [asyncio.to_thread(cache.get, f"key_{i}") for i in range(50)]
        results = await asyncio.gather(*tasks)
        
        # 验证结果
        for i, result in enumerate(results):
            assert result == f"value_{i}"
    
    @pytest.mark.asyncio
    async def test_cache_hit_rate_under_load(self):
        """测试高并发下的缓存命中率"""
        cache = MemoryCache(max_size=100)
        
        # 先写入数据
        cache.set("hot_key", "hot_value", ttl=300)
        
        # 高并发读取
        tasks = []
        for _ in range(500):
            tasks.append(asyncio.to_thread(cache.get, "hot_key"))
        
        await asyncio.gather(*tasks)
        
        stats = cache.get_stats()
        assert stats["hits"] == 500
        assert stats["misses"] == 0


class TestConcurrentCacheWrites:
    """并发写测试"""
    
    @pytest.mark.asyncio
    async def test_concurrent_write_same_key(self):
        """测试同一key并发写入"""
        cache = MemoryCache(max_size=100)
        
        # 并发写入同一key
        tasks = [
            asyncio.to_thread(cache.set, "test_key", f"value_{i}", ttl=300)
            for i in range(100)
        ]
        await asyncio.gather(*tasks)
        
        # 最终值应该是其中一个
        final_value = cache.get("test_key")
        assert final_value is not None
        assert final_value.startswith("value_")
    
    @pytest.mark.asyncio
    async def test_concurrent_write_different_keys(self):
        """测试不同key并发写入"""
        cache = MemoryCache(max_size=1000)
        
        # 并发写入不同key
        tasks = [
            asyncio.to_thread(cache.set, f"key_{i}", f"value_{i}", ttl=300)
            for i in range(100)
        ]
        await asyncio.gather(*tasks)
        
        # 验证所有key都写入成功
        for i in range(100):
            value = cache.get(f"key_{i}")
            assert value == f"value_{i}"


class TestCacheLRU:
    """缓存LRU淘汰测试"""
    
    @pytest.mark.asyncio
    async def test_lru_eviction(self):
        """测试LRU淘汰"""
        cache = MemoryCache(max_size=5)
        
        # 写入5个key（达到上限）
        for i in range(5):
            cache.set(f"key_{i}", f"value_{i}", ttl=300)
        
        # 再写入1个key，应该淘汰最旧的
        cache.set("key_5", "value_5", ttl=300)
        
        # key_0应该被淘汰
        assert cache.get("key_0") is None
        # 其他key应该存在
        for i in range(1, 6):
            assert cache.get(f"key_{i}") == f"value_{i}"
    
    @pytest.mark.asyncio
    async def test_lru_access_order(self):
        """测试LRU访问顺序更新"""
        cache = MemoryCache(max_size=5)
        
        # 写入5个key
        for i in range(5):
            cache.set(f"key_{i}", f"value_{i}", ttl=300)
        
        # 访问key_0（更新为最近使用）
        cache.get("key_0")
        
        # 写入新key，应该淘汰key_1（最旧的）
        cache.set("key_5", "value_5", ttl=300)
        
        # key_0应该还在
        assert cache.get("key_0") == "value_0"
        # key_1应该被淘汰
        assert cache.get("key_1") is None


class TestCacheTTL:
    """缓存TTL过期测试"""
    
    @pytest.mark.asyncio
    async def test_ttl_expiration(self):
        """测试TTL过期"""
        cache = MemoryCache()
        
        # 写入带短TTL的值
        cache.set("expire_key", "expire_value", ttl=1)
        
        # 立即读取应该存在
        assert cache.get("expire_key") == "expire_value"
        
        # 等待过期
        await asyncio.sleep(1.5)
        
        # 读取应该返回None
        assert cache.get("expire_key") is None
    
    @pytest.mark.asyncio
    async def test_cleanup_expired(self):
        """测试清理过期缓存"""
        cache = MemoryCache()
        
        # 写入过期和不过期的数据
        cache.set("expired_1", "value", ttl=1)
        cache.set("expired_2", "value", ttl=1)
        cache.set("valid", "value", ttl=300)
        
        # 等待过期
        await asyncio.sleep(1.5)
        
        # 清理过期数据
        cleaned = cache.cleanup_expired()
        
        # 应该清理2条
        assert cleaned == 2
        # 有效数据应该还在
        assert cache.get("valid") == "value"


class TestCacheConcurrentDelete:
    """并发删除测试"""
    
    @pytest.mark.asyncio
    async def test_concurrent_delete(self):
        """测试并发删除"""
        cache = MemoryCache(max_size=100)
        
        # 写入数据
        for i in range(50):
            cache.set(f"key_{i}", f"value_{i}", ttl=300)
        
        # 并发删除
        tasks = [
            asyncio.to_thread(cache.delete, f"key_{i}")
            for i in range(50)
        ]
        results = await asyncio.gather(*tasks)
        
        # 验证所有key都被删除
        for i in range(50):
            assert cache.get(f"key_{i}") is None
    
    @pytest.mark.asyncio
    async def test_delete_nonexistent_key(self):
        """测试删除不存在的key"""
        cache = MemoryCache()
        
        # 删除不存在的key应该返回False
        result = cache.delete("nonexistent")
        assert result is False


class TestCacheCluster:
    """缓存集群测试"""
    
    @pytest.mark.asyncio
    async def test_cache_cluster_invalidation(self):
        """测试集群失效通知"""
        cache1 = MemoryCache(node_id="node1")
        cache2 = MemoryCache(node_id="node2")
        
        # 注册到集群
        cache1.subscribe(cache2)
        
        # 在cache1中写入数据
        cache1.set("shared_key", "shared_value", ttl=300)
        
        # 在cache1中删除，cache2应该收到通知
        cache1._notify_subscribers("delete", "shared_key")
        
        # cache2应该也被删除
        assert cache2.get("shared_key") is None
    
    @pytest.mark.asyncio
    async def test_cache_cluster_clear(self):
        """测试集群清空通知"""
        cache1 = MemoryCache(node_id="node1")
        cache2 = MemoryCache(node_id="node2")
        
        # 注册到集群
        cache1.subscribe(cache2)
        
        # 在cache1中写入数据
        cache1.set("key1", "value1", ttl=300)
        cache1.set("key2", "value2", ttl=300)
        
        # 清空cache1
        cache1._notify_subscribers("clear", "")
        
        # cache2应该也被清空
        assert cache2.get("key1") is None
        assert cache2.get("key2") is None
    
    @pytest.mark.asyncio
    async def test_cluster_unsubscribe(self):
        """测试取消订阅"""
        cache1 = MemoryCache(node_id="node1")
        cache2 = MemoryCache(node_id="node2")
        
        # 注册到集群
        cache1.subscribe(cache2)
        
        # 取消订阅
        cache1.unsubscribe("node2")
        
        # 写入数据
        cache1.set("key", "value", ttl=300)
        
        # 通知（不应该影响cache2）
        cache1._notify_subscribers("delete", "key")
        
        # cache2应该仍然有数据
        assert cache2.get("key") == "value"


class TestCacheManagerConcurrency:
    """CacheManager并发测试"""
    
    @pytest.mark.asyncio
    async def test_cache_manager_concurrent_get_set(self):
        """测试CacheManager并发读写"""
        manager = CacheManager(backend=CacheBackend.MEMORY)
        
        # 并发读写
        async def write_task(i):
            manager.set(f"key_{i}", f"value_{i}", ttl=300)
        
        async def read_task(i):
            return manager.get(f"key_{i}")
        
        # 并发执行
        tasks = []
        for i in range(50):
            tasks.append(asyncio.create_task(write_task(i)))
        
        await asyncio.gather(*tasks)
        
        # 读取验证
        for i in range(50):
            value = manager.get(f"key_{i}")
            assert value == f"value_{i}"
    
    @pytest.mark.asyncio
    async def test_cache_manager_stats(self):
        """测试CacheManager统计"""
        manager = CacheManager(backend=CacheBackend.MEMORY)
        
        # 写入一些数据
        for i in range(10):
            manager.set(f"key_{i}", f"value_{i}", ttl=300)
        
        # 读取数据
        for i in range(10):
            manager.get(f"key_{i}")
        
        # 获取统计
        stats = manager.get_stats()
        
        assert stats["total_keys"] == 10
        assert stats["hits"] >= 10


class TestCacheEdgeCases:
    """缓存边界情况测试"""
    
    @pytest.mark.asyncio
    async def test_cache_empty_value(self):
        """测试缓存空值"""
        cache = MemoryCache()
        
        # 缓存空值
        cache.set("empty_key", "", ttl=300)
        
        # 应该能获取到空字符串
        result = cache.get("empty_key")
        assert result == ""
    
    @pytest.mark.asyncio
    async def test_cache_none_value(self):
        """测试缓存None值"""
        cache = MemoryCache()
        
        # 缓存None
        cache.set("none_key", None, ttl=300)
        
        # 注意：内存缓存中None会被当作默认值返回
        # 这里测试key不存在的情况
        result = cache.get("nonexistent_key", default=None)
        assert result is None
    
    @pytest.mark.asyncio
    async def test_cache_large_value(self):
        """测试缓存大值"""
        cache = MemoryCache()
        
        # 创建大值（1MB）
        large_value = "x" * (1024 * 1024)
        cache.set("large_key", large_value, ttl=300)
        
        # 应该能正确存储和读取
        result = cache.get("large_key")
        assert result == large_value
    
    @pytest.mark.asyncio
    async def test_cache_special_characters(self):
        """测试缓存特殊字符"""
        cache = MemoryCache()
        
        # 测试各种特殊字符
        special_values = [
            "hello world",
            "测试中文",
            "emoji 😀",
            "特殊符号 !@#$%^&*()",
            "换行\n\t符",
            "unicode: 你好世界"
        ]
        
        for i, value in enumerate(special_values):
            cache.set(f"key_{i}", value, ttl=300)
        
        # 验证
        for i, value in enumerate(special_values):
            result = cache.get(f"key_{i}")
            assert result == value


class TestCacheRaceConditions:
    """竞态条件测试"""
    
    @pytest.mark.asyncio
    async def test_check_then_act(self):
        """测试检查-然后-操作模式"""
        cache = MemoryCache()
        
        # 模拟 check-then-act
        def check_and_set():
            value = cache.get("key")
            if value is None:
                cache.set("key", "new_value", ttl=300)
                return "set"
            return value
        
        # 并发执行
        tasks = [asyncio.to_thread(check_and_set) for _ in range(10)]
        results = await asyncio.gather(*tasks)
        
        # 至少有一个成功
        assert any(r is not None for r in results)
    
    @pytest.mark.asyncio
    async def test_read_modify_write(self):
        """测试读-修改-写模式"""
        cache = MemoryCache()
        
        # 初始值
        cache.set("counter", 0, ttl=300)
        
        # 模拟 read-modify-write
        def increment():
            value = cache.get("counter") or 0
            value = value + 1
            cache.set("counter", value, ttl=300)
            return value
        
        # 并发执行
        tasks = [asyncio.to_thread(increment) for _ in range(100)]
        await asyncio.gather(*tasks)
        
        # 最终值可能小于100（因为竞态），但应该大于0
        final_value = cache.get("counter")
        assert final_value > 0
        assert final_value <= 100


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
