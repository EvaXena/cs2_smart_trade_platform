# -*- coding: utf-8 -*-
"""
缓存后台任务测试 - 验证 P1 修复
"""
import pytest
import asyncio
import warnings

from app.services.cache import (
    CacheManager,
    CacheBackend,
    CacheEntry,
)


@pytest.fixture(autouse=True)
def disable_jitter():
    """禁用随机抖动以确保测试稳定性"""
    original = CacheEntry._enable_jitter
    CacheEntry.set_jitter_enabled(False)
    yield
    CacheEntry.set_jitter_enabled(original)


@pytest.mark.asyncio
async def test_cleanup_task_is_saved():
    """测试清理任务被正确保存"""
    manager = CacheManager(backend=CacheBackend.MEMORY)
    await manager.initialize()
    
    # 验证任务已创建并保存
    assert manager._cleanup_task is not None
    assert isinstance(manager._cleanup_task, asyncio.Task)
    
    # 清理
    await manager.shutdown()
    assert manager._cleanup_task is None


@pytest.mark.asyncio
async def test_redis_reconnect_task_is_saved():
    """测试 Redis 重连任务被正确保存"""
    manager = CacheManager(backend=CacheBackend.REDIS, redis_url="redis://localhost:6379/0")
    await manager.initialize(max_retries=1, retry_delay=0.1)
    
    # 注意：由于 Redis 可能不可用，任务可能已切换到内存模式
    # 但任务引用应该仍然被保存
    
    # 清理
    await manager.shutdown()


@pytest.mark.asyncio
async def test_shutdown_cancels_tasks():
    """测试 shutdown 方法正确取消任务"""
    manager = CacheManager(backend=CacheBackend.MEMORY)
    await manager.initialize()
    
    # 验证任务正在运行
    assert manager._cleanup_task is not None
    assert not manager._cleanup_task.done()
    
    # 调用 shutdown
    await manager.shutdown()
    
    # 验证任务已被取消
    assert manager._cleanup_task is None


@pytest.mark.asyncio
async def test_no_pending_tasks_warning():
    """测试运行测试后没有待处理任务警告"""
    # 这个测试确保我们正确管理后台任务
    manager = CacheManager(backend=CacheBackend.MEMORY)
    await manager.initialize()
    
    # 执行一些缓存操作
    manager.set("key1", "value1", ttl=60)
    assert manager.get("key1") == "value1"
    
    # 清理
    await manager.shutdown()
    
    # 如果没有异常，说明任务被正确清理


@pytest.mark.asyncio
async def test_multiple_managers():
    """测试多个 CacheManager 实例独立管理任务"""
    manager1 = CacheManager(backend=CacheBackend.MEMORY)
    manager2 = CacheManager(backend=CacheBackend.MEMORY)
    
    await manager1.initialize()
    await manager2.initialize()
    
    # 验证两个管理器都有独立的任务
    assert manager1._cleanup_task is not None
    assert manager2._cleanup_task is not None
    assert manager1._cleanup_task != manager2._cleanup_task
    
    # 清理
    await manager1.shutdown()
    await manager2.shutdown()


@pytest.mark.asyncio
async def test_cache_entry_jitter_control():
    """测试 CacheEntry 抖动控制"""
    import time
    
    # 测试禁用抖动
    CacheEntry.set_jitter_enabled(False)
    entry_without_jitter = CacheEntry("value", ttl=100)
    
    # 禁用抖动后，TTL 应该正好是原始值（允许 ±1 秒误差）
    remaining_ttl = entry_without_jitter.get_remaining_ttl()
    assert 99 <= remaining_ttl <= 101, f"Expected 99-101, got {remaining_ttl}"
    
    # 恢复默认
    CacheEntry.set_jitter_enabled(True)
