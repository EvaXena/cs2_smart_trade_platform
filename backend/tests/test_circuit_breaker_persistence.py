# -*- coding: utf-8 -*-
"""
熔断器 Redis 持久化测试
验证熔断器状态的 Redis 持久化功能
"""
import pytest
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch
import sys
import os

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class MockRedis:
    """模拟 Redis 客户端"""
    
    def __init__(self):
        self._data = {}
        self._expire = {}
    
    async def hgetall(self, key: str):
        """获取 hash 所有字段"""
        return self._data.get(key, {})
    
    async def hset(self, key: str, mapping: dict = None, **kwargs):
        """设置 hash 字段"""
        if key not in self._data:
            self._data[key] = {}
        if mapping:
            self._data[key].update(mapping)
        self._data[key].update(kwargs)
        return True
    
    async def expire(self, key: str, seconds: int):
        """设置过期时间"""
        self._expire[key] = seconds
        return True
    
    async def delete(self, key: str):
        """删除 key"""
        if key in self._data:
            del self._data[key]
        return 1
    
    async def ping(self):
        return True


class TestCircuitBreakerRedisPersistence:
    """熔断器 Redis 持久化测试"""

    def test_circuit_breaker_with_redis_client(self):
        """测试带 Redis 客户端的熔断器初始化"""
        from app.core.circuit_breaker import CircuitBreaker, CircuitState
        
        mock_redis = MockRedis()
        breaker = CircuitBreaker(
            name="test_redis_init",
            failure_threshold=5,
            recovery_timeout=30,
            redis_client=mock_redis
        )
        
        assert breaker.name == "test_redis_init"
        assert breaker.state == CircuitState.CLOSED
        assert breaker.has_redis() is True

    def test_circuit_breaker_without_redis(self):
        """测试不带 Redis 客户端的熔断器（内存模式）"""
        from app.core.circuit_breaker import CircuitBreaker, CircuitState
        
        breaker = CircuitBreaker(
            name="test_memory",
            failure_threshold=5,
            recovery_timeout=30
        )
        
        assert breaker.name == "test_memory"
        assert breaker.state == CircuitState.CLOSED
        assert breaker.has_redis() is False

    @pytest.mark.asyncio
    async def test_save_state_to_redis(self):
        """测试保存状态到 Redis"""
        from app.core.circuit_breaker import CircuitBreaker, CircuitState
        
        mock_redis = MockRedis()
        
        # 创建一个熔断器并触发失败
        breaker = CircuitBreaker(
            name="test_save",
            failure_threshold=3,
            recovery_timeout=30,
            redis_client=mock_redis
        )
        
        async def failing_func():
            raise Exception("Test failure")
        
        # 触发失败
        for _ in range(3):
            try:
                await breaker.call(failing_func)
            except Exception:
                pass
        
        # 等待异步保存完成
        await asyncio.sleep(0.1)
        
        # 验证状态已保存到 Redis
        saved_data = mock_redis._data.get("circuit_breaker:test_save", {})
        
        assert saved_data["state"] == "open"
        assert int(saved_data["failure_count"]) == 3

    @pytest.mark.asyncio
    async def test_load_state_from_redis(self):
        """测试从 Redis 加载状态"""
        from app.core.circuit_breaker import CircuitBreaker, CircuitState
        
        mock_redis = MockRedis()
        
        # 预先在 Redis 中写入数据
        await mock_redis.hset("circuit_breaker:test_load", mapping={
            "state": "open",
            "failure_count": "5",
            "success_count": "0",
            "last_failure_time": str(time.time()),
            "opened_at": str(time.time()),
            "last_state_change_time": str(time.time()),
            "half_open_calls": "0",
        })
        
        # 创建新的熔断器实例，应该从 Redis 加载状态
        breaker = CircuitBreaker(
            name="test_load",
            failure_threshold=3,
            recovery_timeout=30,
            redis_client=mock_redis
        )
        
        # 等待异步加载完成
        await asyncio.sleep(0.1)
        
        assert breaker.state == CircuitState.OPEN
        assert breaker._failure_count == 5

    @pytest.mark.asyncio
    async def test_state_persistence_after_restart(self):
        """测试服务重启后状态恢复"""
        from app.core.circuit_breaker import CircuitBreaker, CircuitState
        
        mock_redis = MockRedis()
        
        # 第一次：创建熔断器并触发熔断
        breaker1 = CircuitBreaker(
            name="test_restart",
            failure_threshold=2,
            recovery_timeout=30,
            redis_client=mock_redis
        )
        
        async def failing_func():
            raise Exception("Test failure")
        
        for _ in range(2):
            try:
                await breaker1.call(failing_func)
            except Exception:
                pass
        
        # 等待异步保存完成
        await asyncio.sleep(0.1)
        
        assert breaker1.state == CircuitState.OPEN
        
        # 模拟服务重启：创建新的熔断器实例（使用同一个 Redis）
        breaker2 = CircuitBreaker(
            name="test_restart",
            failure_threshold=2,
            recovery_timeout=30,
            redis_client=mock_redis
        )
        
        # 等待异步加载完成
        await asyncio.sleep(0.1)
        
        # 验证状态已恢复
        assert breaker2.state == CircuitState.OPEN
        assert breaker2._failure_count >= 2

    @pytest.mark.asyncio
    async def test_reset_clears_redis(self):
        """测试重置时清除 Redis 状态"""
        from app.core.circuit_breaker import CircuitBreaker, CircuitState
        
        mock_redis = MockRedis()
        
        # 创建熔断器并触发熔断
        breaker = CircuitBreaker(
            name="test_reset",
            failure_threshold=1,
            recovery_timeout=30,
            redis_client=mock_redis
        )
        
        async def failing_func():
            raise Exception("Test failure")
        
        try:
            await breaker.call(failing_func)
        except Exception:
            pass
        
        assert breaker.state == CircuitState.OPEN
        
        # 重置
        breaker.reset()
        
        # 验证 Redis 中的数据已删除
        assert "circuit_breaker:test_reset" not in mock_redis._data

    @pytest.mark.asyncio
    async def test_half_open_state_persistence(self):
        """测试半开状态持久化"""
        from app.core.circuit_breaker import CircuitBreaker, CircuitState
        
        mock_redis = MockRedis()
        
        # 创建熔断器并触发熔断，然后等待进入半开状态
        breaker = CircuitBreaker(
            name="test_half_open",
            failure_threshold=2,
            recovery_timeout=0.5,
            success_threshold=1,
            redis_client=mock_redis
        )
        
        async def failing_func():
            raise Exception("Test failure")
        
        # 触发熔断
        for _ in range(2):
            try:
                await breaker.call(failing_func)
            except Exception:
                pass
        
        # 等待恢复超时
        await asyncio.sleep(0.6)
        
        # 触发状态转换到半开
        try:
            await breaker.call(failing_func)
        except Exception:
            pass
        
        # 等待异步保存完成
        await asyncio.sleep(0.1)
        
        assert breaker.state == CircuitState.HALF_OPEN
        
        # 验证状态已保存到 Redis
        saved_data = mock_redis._data.get("circuit_breaker:test_half_open", {})
        assert saved_data["state"] == "half_open"

    def test_set_redis_client_after_init(self):
        """测试初始化后设置 Redis 客户端"""
        from app.core.circuit_breaker import CircuitBreaker, CircuitState
        
        # 先创建不带 Redis 的熔断器
        breaker = CircuitBreaker(
            name="test_set_redis",
            failure_threshold=5,
            recovery_timeout=30
        )
        
        assert breaker.has_redis() is False
        
        # 后续设置 Redis 客户端
        mock_redis = MockRedis()
        breaker.set_redis_client(mock_redis)
        
        assert breaker.has_redis() is True

    @pytest.mark.asyncio
    async def test_backward_compatibility(self):
        """测试向后兼容性：无 Redis 时使用内存模式"""
        from app.core.circuit_breaker import CircuitBreaker, CircuitState
        
        # 不提供 Redis 客户端
        breaker = CircuitBreaker(
            name="test_compat",
            failure_threshold=2,
            recovery_timeout=30
        )
        
        async def failing_func():
            raise Exception("Test failure")
        
        # 触发熔断
        for _ in range(2):
            try:
                await breaker.call(failing_func)
            except Exception:
                pass
        
        # 应该正常工作
        assert breaker.state == CircuitState.OPEN
        
        # 重置也应该正常工作
        breaker.reset()
        assert breaker.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_success_count_persistence(self):
        """测试成功计数持久化"""
        from app.core.circuit_breaker import CircuitBreaker, CircuitState
        
        mock_redis = MockRedis()
        
        # 创建熔断器
        breaker = CircuitBreaker(
            name="test_success_count",
            failure_threshold=3,
            recovery_timeout=0.5,
            success_threshold=2,
            redis_client=mock_redis
        )
        
        async def success_func():
            return "success"
        
        # 触发熔断
        async def failing_func():
            raise Exception("Test failure")
        
        for _ in range(3):
            try:
                await breaker.call(failing_func)
            except Exception:
                pass
        
        # 等待进入半开
        await asyncio.sleep(0.6)
        
        try:
            await breaker.call(failing_func)
        except Exception:
            pass
        
        # 等待异步保存完成
        await asyncio.sleep(0.1)
        
        assert breaker.state == CircuitState.HALF_OPEN
        
        # 记录成功
        await breaker.call(success_func)
        
        # 等待异步保存完成
        await asyncio.sleep(0.1)
        
        # 验证成功计数已保存
        saved_data = mock_redis._data.get("circuit_breaker:test_success_count", {})
        assert int(saved_data["success_count"]) >= 1


class TestCircuitBreakerRedisKey:
    """熔断器 Redis Key 测试"""

    def test_redis_key_format(self):
        """测试 Redis key 格式"""
        from app.core.circuit_breaker import _get_redis_key, CIRCUIT_BREAKER_KEY_PREFIX
        
        key = _get_redis_key("test_service")
        assert key == f"{CIRCUIT_BREAKER_KEY_PREFIX}test_service"
        
        key2 = _get_redis_key("steam_api")
        assert key2 == f"{CIRCUIT_BREAKER_KEY_PREFIX}steam_api"


class TestCircuitBreakerOpenedAt:
    """熔断器打开时间测试"""

    @pytest.mark.asyncio
    async def test_opened_at_recorded(self):
        """测试打开时间被记录"""
        from app.core.circuit_breaker import CircuitBreaker, CircuitState
        
        mock_redis = MockRedis()
        
        breaker = CircuitBreaker(
            name="test_opened_at",
            failure_threshold=1,
            recovery_timeout=30,
            redis_client=mock_redis
        )
        
        async def failing_func():
            raise Exception("Test failure")
        
        before_call = time.time()
        try:
            await breaker.call(failing_func)
        except Exception:
            pass
        after_call = time.time()
        
        assert breaker.state == CircuitState.OPEN
        assert breaker._opened_at is not None
        assert before_call <= breaker._opened_at <= after_call
        
        # 验证 opened_at 已保存到 Redis
        saved_data = mock_redis._data.get("circuit_breaker:test_opened_at", {})
        assert saved_data.get("opened_at") != ""


class TestCircuitBreakerDecoratorWithRedis:
    """带 Redis 的熔断器装饰器测试"""

    def test_decorator_with_redis(self):
        """测试装饰器使用 Redis"""
        from app.core.circuit_breaker import CircuitBreakerDecorator, circuit_breaker
        
        # 清理
        CircuitBreakerDecorator.reset_all()
        
        mock_redis = MockRedis()
        
        # 使用 Redis 客户端创建熔断器
        breaker = CircuitBreakerDecorator.get_breaker(
            name="redis_test",
            failure_threshold=3,
            recovery_timeout=30,
            redis_client=mock_redis
        )
        
        assert breaker.has_redis() is True
        
        # 验证装饰器可以正常工作
        @circuit_breaker(name="redis_test", failure_threshold=2)
        async def test_func():
            return "success"
        
        result = asyncio.run(test_func())
        assert result == "success"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
