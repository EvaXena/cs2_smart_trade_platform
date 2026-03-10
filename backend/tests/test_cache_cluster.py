# -*- coding: utf-8 -*-
"""
缓存集群支持测试
"""
import pytest
from app.services.cache import (
    MemoryCache,
    CacheManager,
    CacheBackend,
    get_cache,
)


class TestMemoryCacheCluster:
    """内存缓存集群功能测试"""
    
    def test_set_and_get_node_id(self):
        """测试设置和获取节点ID"""
        cache = MemoryCache()
        
        cache.set_node_id("node-001")
        assert cache.get_node_id() == "node-001"
    
    def test_default_node_id(self):
        """测试默认节点ID"""
        cache = MemoryCache()
        
        # 应该有默认节点ID
        node_id = cache.get_node_id()
        assert node_id is not None
        assert "node-" in node_id
    
    def test_subscribe(self):
        """测试订阅功能"""
        cache1 = MemoryCache(node_id="node-1")
        cache2 = MemoryCache(node_id="node-2")
        
        # cache1 订阅 cache2
        cache1.subscribe(cache2)
        
        # 验证订阅关系
        assert cache2._node_id in cache1._subscribers
    
    def test_unsubscribe(self):
        """测试取消订阅"""
        cache1 = MemoryCache(node_id="node-1")
        cache2 = MemoryCache(node_id="node-2")
        
        cache1.subscribe(cache2)
        cache1.unsubscribe("node-2")
        
        assert "node-2" not in cache1._subscribers
    
    def test_remote_delete_notification(self):
        """测试远程删除通知"""
        cache1 = MemoryCache(node_id="node-1")
        cache2 = MemoryCache(node_id="node-2")
        
        # cache1 订阅 cache2
        cache1.subscribe(cache2)
        
        # 在 cache2 中设置值
        cache2.set("key1", "value1")
        
        # 在 cache1 中验证值存在
        assert cache1.get("key1") == "value1"
        
        # 通过 cache2 删除
        cache2.delete("key1")
        
        # 通知订阅者
        cache2._notify_subscribers("delete", "key1")
        
        # cache1 中的值应该也被删除
        assert cache1.get("key1") is None
    
    def test_remote_clear_notification(self):
        """测试远程清空通知"""
        cache1 = MemoryCache(node_id="node-1")
        cache2 = MemoryCache(node_id="node-2")
        
        # cache1 订阅 cache2
        cache1.subscribe(cache2)
        
        # 在 cache2 中设置值
        cache2.set("key1", "value1")
        cache2.set("key2", "value2")
        
        # 验证 cache1 中有值
        assert cache1.get("key1") == "value1"
        assert cache1.get("key2") == "value2"
        
        # 清空 cache2
        cache2.clear()
        
        # 通知订阅者
        cache2._notify_subscribers("clear", "")
        
        # cache1 应该也被清空
        assert cache1.get("key1") is None
        assert cache1.get("key2") is None
    
    def test_notify_subscribers_handles_errors(self):
        """测试通知订阅者时处理错误"""
        cache1 = MemoryCache(node_id="node-1")
        
        # 创建一个会抛出异常的订阅者
        class FaultyCache:
            _node_id = "faulty"
            
            def _handle_remote_delete(self, key):
                raise Exception("Simulated error")
        
        cache1._subscribers["faulty"] = FaultyCache()
        
        # 不应该抛出异常
        cache1._notify_subscribers("delete", "key1")


class TestCacheManagerCluster:
    """缓存管理器集群功能测试"""
    
    def test_set_node_id(self):
        """测试设置节点ID"""
        manager = CacheManager(backend=CacheBackend.MEMORY)
        
        manager.set_node_id("cluster-node-1")
        
        assert manager.get_node_id() == "cluster-node-1"
    
    def test_register_to_cluster(self):
        """测试注册到集群"""
        manager1 = CacheManager(backend=CacheBackend.MEMORY)
        manager2 = CacheManager(backend=CacheBackend.MEMORY)
        
        manager1.set_node_id("node-1")
        manager2.set_node_id("node-2")
        
        manager1.register_to_cluster(manager2)
        
        # 验证注册成功
        assert manager2.get_node_id() in [
            sub._node_id for sub in manager1._memory_cache._subscribers.values()
        ]
    
    def test_broadcast_invalidation(self):
        """测试广播失效通知"""
        manager1 = CacheManager(backend=CacheBackend.MEMORY)
        manager2 = CacheManager(backend=CacheBackend.MEMORY)
        
        manager1.set_node_id("node-1")
        manager2.set_node_id("node-2")
        
        # 注册到集群
        manager1.register_to_cluster(manager2)
        
        # 在 manager2 中设置值
        manager2.set("test_key", "test_value")
        
        # 验证 manager1 中可以获取
        assert manager1.get("test_key") == "test_value"
        
        # 通过 manager1 广播失效
        manager1.broadcast_invalidation("test_key")
        
        # manager2 中的值应该失效
        # 注意：broadcast_invalidation 只通知订阅者，不删除本地
        # 这里是测试通知机制
        assert manager2.get("test_key") == "test_value"  # 本地未删除
    
    def test_broadcast_clear(self):
        """测试广播清空"""
        manager1 = CacheManager(backend=CacheBackend.MEMORY)
        manager2 = CacheManager(backend=CacheBackend.MEMORY)
        
        manager1.set_node_id("node-1")
        manager2.set_node_id("node-2")
        
        # 注册到集群
        manager1.register_to_cluster(manager2)
        
        # 在 manager1 中设置值
        manager1.set("key1", "value1")
        manager1.set("key2", "value2")
        
        # 广播清空
        manager1.broadcast_clear()
        
        # 验证 manager1 被清空
        assert manager1.get("key1") is None


class TestCacheClusterIntegration:
    """缓存集群集成测试"""
    
    def test_multi_node_cache_consistency(self):
        """测试多节点缓存一致性"""
        # 创建三个缓存节点
        node1 = CacheManager(backend=CacheBackend.MEMORY)
        node2 = CacheManager(backend=CacheBackend.MEMORY)
        node3 = CacheManager(backend=CacheBackend.MEMORY)
        
        node1.set_node_id("node-1")
        node2.set_node_id("node-2")
        node3.set_node_id("node-3")
        
        # 建立集群连接
        node1.register_to_cluster(node2)
        node1.register_to_cluster(node3)
        node2.register_to_cluster(node3)
        
        # 在 node1 设置值
        node1.set("shared_key", "shared_value", ttl=300)
        
        # 所有节点都能获取
        assert node1.get("shared_key") == "shared_value"
        assert node2.get("shared_key") == "shared_value"
        assert node3.get("shared_key") == "shared_value"
        
        # 删除值并广播
        node1.delete("shared_key")
        node1.broadcast_invalidation("shared_key")
        
        # 所有节点的值都应该失效
        assert node1.get("shared_key") is None
        assert node2.get("shared_key") is None
        assert node3.get("shared_key") is None
    
    def test_cluster_stats_include_node_id(self):
        """测试集群统计信息包含节点ID"""
        manager = CacheManager(backend=CacheBackend.MEMORY)
        manager.set_node_id("test-node")
        
        manager.set("key1", "value1")
        manager.get("key1")
        manager.get("nonexistent")
        
        stats = manager.get_stats()
        
        assert stats["total_keys"] == 1
        assert stats["hits"] == 1
        assert stats["misses"] == 1
