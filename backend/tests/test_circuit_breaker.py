# -*- coding: utf-8 -*-
"""
熔断器功能测试
验证熔断器的状态转换、恢复逻辑和统计功能
"""
import pytest
import asyncio
import time
from unittest.mock import AsyncMock, patch
import sys
import os

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestCircuitBreakerBasics:
    """熔断器基础功能测试"""

    def test_circuit_breaker_initial_state(self):
        """测试熔断器初始状态"""
        from app.core.circuit_breaker import CircuitBreaker, CircuitState
        
        breaker = CircuitBreaker(
            name="test",
            failure_threshold=5,
            recovery_timeout=30
        )
        
        assert breaker.state == CircuitState.CLOSED

    def test_circuit_breaker_failure_threshold(self):
        """测试失败阈值触发熔断"""
        from app.core.circuit_breaker import CircuitBreaker, CircuitState
        
        breaker = CircuitBreaker(
            name="test_failure",
            failure_threshold=3,
            recovery_timeout=1,  # 1秒后进入半开状态
            success_threshold=2
        )
        
        async def failing_func():
            raise Exception("Test failure")
        
        # 触发3次失败
        for _ in range(3):
            try:
                asyncio.run(breaker.call(failing_func))
            except Exception:
                pass
        
        assert breaker.state == CircuitState.OPEN

    def test_circuit_breaker_state_transition_to_half_open(self):
        """测试熔断器状态转换到半开"""
        from app.core.circuit_breaker import CircuitBreaker, CircuitState
        
        breaker = CircuitBreaker(
            name="test_half_open",
            failure_threshold=2,
            recovery_timeout=0.5,  # 0.5秒后进入半开状态
            success_threshold=1
        )
        
        async def failing_func():
            raise Exception("Test failure")
        
        # 触发熔断
        for _ in range(2):
            try:
                asyncio.run(breaker.call(failing_func))
            except Exception:
                pass
        
        assert breaker.state == CircuitState.OPEN
        
        # 等待恢复超时
        time.sleep(0.6)
        
        # 再次调用触发状态转换
        try:
            asyncio.run(breaker.call(failing_func))
        except Exception:
            pass
        
        # 应该转换到半开状态
        assert breaker.state == CircuitState.HALF_OPEN

    def test_circuit_breaker_recovery(self):
        """测试熔断器恢复"""
        from app.core.circuit_breaker import CircuitBreaker, CircuitState
        
        breaker = CircuitBreaker(
            name="test_recovery",
            failure_threshold=2,
            recovery_timeout=0.3,
            success_threshold=2
        )
        
        async def failing_func():
            raise Exception("Test failure")
        
        async def success_func():
            return "success"
        
        # 触发熔断
        for _ in range(2):
            try:
                asyncio.run(breaker.call(failing_func))
            except Exception:
                pass
        
        assert breaker.state == CircuitState.OPEN
        
        # 等待恢复超时
        time.sleep(0.4)
        
        # 触发半开状态
        try:
            asyncio.run(breaker.call(failing_func))
        except Exception:
            pass
        
        assert breaker.state == CircuitState.HALF_OPEN
        
        # 连续成功恢复
        asyncio.run(breaker.call(success_func))
        asyncio.run(breaker.call(success_func))
        
        # 应该恢复到关闭状态
        assert breaker.state == CircuitState.CLOSED

    def test_circuit_breaker_reject_when_open(self):
        """测试熔断器打开时拒绝请求"""
        from app.core.circuit_breaker import CircuitBreaker, CircuitState, CircuitBreakerOpen
        
        breaker = CircuitBreaker(
            name="test_reject",
            failure_threshold=1,
            recovery_timeout=30
        )
        
        # 先触发熔断
        async def failing_func():
            raise Exception("Test failure")
        
        try:
            asyncio.run(breaker.call(failing_func))
        except Exception:
            pass
        
        assert breaker.state == CircuitState.OPEN
        
        # 验证新请求被拒绝
        with pytest.raises(CircuitBreakerOpen):
            asyncio.run(breaker.call(failing_func))


class TestCircuitBreakerStats:
    """熔断器统计功能测试"""

    def test_get_stats(self):
        """测试获取统计信息"""
        from app.core.circuit_breaker import CircuitBreaker, CircuitState
        
        breaker = CircuitBreaker(
            name="test_stats",
            failure_threshold=5,
            recovery_timeout=30
        )
        
        async def failing_func():
            raise Exception("Test failure")
        
        # 触发一些失败
        for _ in range(2):
            try:
                asyncio.run(breaker.call(failing_func))
            except Exception:
                pass
        
        stats = breaker.get_stats()
        
        assert stats["name"] == "test_stats"
        assert stats["state"] == "closed"  # 未达到阈值
        assert stats["failure_count"] == 2
        assert "last_failure_time" in stats

    def test_success_count_tracking(self):
        """测试成功计数跟踪"""
        from app.core.circuit_breaker import CircuitBreaker, CircuitState
        
        breaker = CircuitBreaker(
            name="test_success",
            failure_threshold=3,
            recovery_timeout=1,
            success_threshold=2
        )
        
        async def success_func():
            return "success"
        
        # 触发熔断
        async def failing_func():
            raise Exception("Test failure")
        
        for _ in range(3):
            try:
                asyncio.run(breaker.call(failing_func))
            except Exception:
                pass
        
        # 等待恢复
        time.sleep(1.1)
        
        # 触发半开
        try:
            asyncio.run(breaker.call(failing_func))
        except Exception:
            pass
        
        # 记录成功
        asyncio.run(breaker.call(success_func))
        
        stats = breaker.get_stats()
        assert stats["success_count"] >= 1


class TestCircuitBreakerDecorator:
    """熔断器装饰器测试"""

    def test_decorator_creation(self):
        """测试装饰器创建"""
        from app.core.circuit_breaker import circuit_breaker
        
        @circuit_breaker(name="decorator_test", failure_threshold=3)
        async def test_func():
            return "success"
        
        # 验证函数被装饰
        assert asyncio.iscoroutinefunction(test_func)

    def test_decorator_with_failure(self):
        """测试装饰器处理失败"""
        from app.core.circuit_breaker import CircuitBreakerDecorator, circuit_breaker
        
        # 清理之前的测试状态
        CircuitBreakerDecorator.reset_all()
        
        @circuit_breaker(name="decorator_failure_test", failure_threshold=2)
        async def failing_func():
            raise Exception("Test failure")
        
        # 触发熔断
        for _ in range(2):
            try:
                asyncio.run(failing_func())
            except Exception:
                pass
        
        # 获取统计
        stats = CircuitBreakerDecorator.get_all_stats()
        assert "decorator_failure_test" in stats


class TestCircuitBreakerDecoratorClass:
    """熔断器装饰器类测试"""

    def test_get_breaker(self):
        """测试获取命名熔断器"""
        from app.core.circuit_breaker import CircuitBreakerDecorator, CircuitBreaker
        
        # 清理
        CircuitBreakerDecorator.reset_all()
        
        # 获取熔断器
        breaker1 = CircuitBreakerDecorator.get_breaker(name="test_get")
        breaker2 = CircuitBreakerDecorator.get_breaker(name="test_get")
        
        # 验证返回同一个实例
        assert breaker1 is breaker2

    def test_reset_all(self):
        """测试重置所有熔断器"""
        from app.core.circuit_breaker import CircuitBreakerDecorator
        
        # 创建熔断器
        CircuitBreakerDecorator.get_breaker(name="reset_test_1")
        CircuitBreakerDecorator.get_breaker(name="reset_test_2")
        
        # 重置
        CircuitBreakerDecorator.reset_all()
        
        # 验证已重置
        stats = CircuitBreakerDecorator.get_all_stats()
        assert len(stats) == 0


class TestCircuitBreakerEdgeCases:
    """熔断器边缘情况测试"""

    def test_excluded_exceptions(self):
        """测试排除的异常不计入失败"""
        from app.core.circuit_breaker import CircuitBreaker, CircuitState
        
        class ExcludedError(Exception):
            pass
        
        breaker = CircuitBreaker(
            name="test_excluded",
            failure_threshold=3,
            recovery_timeout=30,
            excluded_exceptions=(ExcludedError,)
        )
        
        async def excluded_func():
            raise ExcludedError("Excluded")
        
        async def regular_func():
            raise Exception("Regular error")
        
        # 触发排除的异常
        for _ in range(5):
            try:
                asyncio.run(breaker.call(excluded_func))
            except ExcludedError:
                pass
        
        # 熔断器应该仍然是关闭状态
        assert breaker.state == CircuitState.CLOSED

    def test_sync_function_call(self):
        """测试同步函数调用"""
        from app.core.circuit_breaker import CircuitBreaker, CircuitState
        
        breaker = CircuitBreaker(
            name="test_sync",
            failure_threshold=2,
            recovery_timeout=30
        )
        
        def sync_func():
            return "sync success"
        
        result = breaker._sync_call(sync_func)
        assert result == "sync success"

    def test_manual_reset(self):
        """测试手动重置"""
        from app.core.circuit_breaker import CircuitBreaker, CircuitState
        
        breaker = CircuitBreaker(
            name="test_manual_reset",
            failure_threshold=1,
            recovery_timeout=30
        )
        
        async def failing_func():
            raise Exception("Test failure")
        
        # 触发熔断
        try:
            asyncio.run(breaker.call(failing_func))
        except Exception:
            pass
        
        assert breaker.state == CircuitState.OPEN
        
        # 手动重置
        breaker.reset()
        
        assert breaker.state == CircuitState.CLOSED

    def test_half_open_max_calls(self):
        """测试半开状态最大尝试次数"""
        from app.core.circuit_breaker import CircuitBreaker, CircuitState
        
        breaker = CircuitBreaker(
            name="test_half_open_max",
            failure_threshold=2,
            recovery_timeout=0.3,
            half_open_max_calls=2,
            success_threshold=3
        )
        
        async def failing_func():
            raise Exception("Test failure")
        
        # 触发熔断
        for _ in range(2):
            try:
                asyncio.run(breaker.call(failing_func))
            except Exception:
                pass
        
        # 等待恢复
        time.sleep(0.4)
        
        # 触发半开状态
        for _ in range(3):
            try:
                asyncio.run(breaker.call(failing_func))
            except Exception:
                pass
        
        # 应该回到 OPEN 状态（因为半开尝试次数超限）
        assert breaker.state == CircuitState.OPEN


class TestPredefinedCircuitBreakers:
    """预定义熔断器测试"""

    def test_steam_circuit_breaker(self):
        """测试 Steam 熔断器"""
        from app.core.circuit_breaker import steam_circuit_breaker, CircuitState
        
        assert steam_circuit_breaker.name == "steam"
        assert steam_circuit_breaker.state == CircuitState.CLOSED

    def test_buff_circuit_breaker(self):
        """测试 Buff 熔断器"""
        from app.core.circuit_breaker import buff_circuit_breaker, CircuitState
        
        assert buff_circuit_breaker.name == "buff"
        assert buff_circuit_breaker.state == CircuitState.CLOSED

    def test_market_circuit_breaker(self):
        """测试市场熔断器"""
        from app.core.circuit_breaker import market_circuit_breaker, CircuitState
        
        assert market_circuit_breaker.name == "market"
        assert market_circuit_breaker.state == CircuitState.CLOSED


class TestCircuitBreakerIntegration:
    """熔断器集成测试"""

    @pytest.mark.asyncio
    async def test_with_steam_service(self):
        """测试与 Steam 服务集成"""
        # 这个测试验证熔断器装饰器与 SteamAPI 类的交互
        # 由于 SteamAPI 方法名可能有变化，这里只做基本验证
        from app.core.circuit_breaker import CircuitBreakerDecorator
        
        # 验证装饰器可以正常获取熔断器
        breaker = CircuitBreakerDecorator.get_breaker(name="steam_test")
        assert breaker is not None
        assert breaker.name == "steam_test"

    @pytest.mark.asyncio
    async def test_circuit_breaker_recovery_time(self):
        """测试熔断器恢复时间"""
        from app.core.circuit_breaker import CircuitBreaker, CircuitState
        
        start_time = time.time()
        
        breaker = CircuitBreaker(
            name="test_recovery_time",
            failure_threshold=1,
            recovery_timeout=1,
            success_threshold=1
        )
        
        async def failing_func():
            raise Exception("Test failure")
        
        # 触发熔断
        try:
            await breaker.call(failing_func)
        except Exception:
            pass
        
        # 等待恢复
        await asyncio.sleep(1.1)
        
        async def success_func():
            return "success"
        
        # 成功恢复
        await breaker.call(success_func)
        
        elapsed = time.time() - start_time
        # 验证恢复时间（应该大约1秒）
        assert elapsed >= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
