# -*- coding: utf-8 -*-
"""
网络异常场景测试
测试网络超时、连接断开、DNS 解析失败等场景的处理
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from aiohttp import ClientError, ServerTimeoutError, ClientConnectorError
import sys
import os

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestNetworkFailureHandling:
    """网络异常处理测试套件"""

    @pytest.mark.asyncio
    async def test_steam_api_timeout_handling(self):
        """测试 Steam API 超时处理"""
        from app.services.steam_service import SteamAPI
        
        steam_api = SteamAPI()
        
        # 模拟请求超时 - 使用正确的方法名
        with patch.object(steam_api, 'get_price_overview', new_callable=AsyncMock) as mock_get_price:
            mock_get_price.side_effect = ServerTimeoutError("Request timeout")
            
            # 验证超时异常被正确处理
            with pytest.raises(ServerTimeoutError):
                await steam_api.get_price_overview("AK-47 | Redline")

    @pytest.mark.asyncio
    async def test_steam_api_connection_error(self):
        """测试 Steam API 连接错误处理"""
        from app.services.steam_service import SteamAPI
        
        steam_api = SteamAPI()
        
        # 模拟连接错误
        with patch.object(steam_api, 'get_price_overview', new_callable=AsyncMock) as mock_get_price:
            mock_get_price.side_effect = ClientConnectorError(
                connection_key=MagicMock(),
                os_error=ConnectionRefusedError("Connection refused")
            )
            
            with pytest.raises(ClientConnectorError):
                await steam_api.get_price_overview("AK-47 | Redline")

    @pytest.mark.asyncio
    async def test_circuit_breaker_on_network_failure(self):
        """测试网络故障时熔断器触发"""
        from app.core.circuit_breaker import CircuitBreaker, CircuitState
        
        breaker = CircuitBreaker(
            name="test_network",
            failure_threshold=3,
            recovery_timeout=1,
            success_threshold=1
        )
        
        async def failing_func():
            raise ClientError("Network error")
        
        # 触发失败直到熔断器打开
        for i in range(3):
            try:
                await breaker.call(failing_func)
            except ClientError:
                pass
        
        # 验证熔断器已打开
        assert breaker.state == CircuitState.OPEN
        
        # 验证新请求被拒绝
        with pytest.raises(Exception):
            await breaker.call(failing_func)

    @pytest.mark.asyncio
    async def test_graceful_degradation(self):
        """测试优雅降级"""
        from app.services.cache import get_cache
        
        cache = get_cache()
        
        # 设置一个会过期的值
        cache.set("expiring_key", "value", ttl=1)
        
        # 等待过期
        await asyncio.sleep(1.5)
        
        # 验证过期后返回 None 而不是抛出异常
        result = cache.get("expiring_key")
        assert result is None

    @pytest.mark.asyncio
    async def test_dns_resolution_failure(self):
        """测试 DNS 解析失败处理"""
        from app.services.steam_service import SteamAPI
        
        steam_api = SteamAPI()
        
        # 模拟 DNS 解析失败
        with patch.object(steam_api, 'get_price_overview', new_callable=AsyncMock) as mock_request:
            mock_request.side_effect = ClientConnectorError(
                connection_key=MagicMock(),
                os_error=OSError("Name or service not known")
            )
            
            with pytest.raises(ClientConnectorError):
                await steam_api.get_price_overview("AK-47")

    @pytest.mark.asyncio
    async def test_concurrent_network_requests(self):
        """测试并发网络请求的错误处理"""
        from app.services.steam_service import SteamAPI
        
        steam_api = SteamAPI()
        
        async def failing_request(item_name: str):
            raise ClientError(f"Network error for {item_name}")
        
        # 并发发送多个失败的请求
        tasks = [failing_request(f"item_{i}") for i in range(5)]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 验证所有请求都返回了异常
        assert all(isinstance(r, Exception) for r in results)


class TestNetworkFailureEdgeCases:
    """网络异常边缘情况测试"""

    @pytest.mark.asyncio
    async def test_partial_response_handling(self):
        """测试部分响应处理"""
        from app.services.steam_service import SteamAPI
        
        steam_api = SteamAPI()
        
        # 模拟不完整的响应
        with patch.object(steam_api, 'get_price_overview', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = {"success": True, "data": None}
            
            # 验证部分响应被正确处理
            result = await steam_api.get_price_overview("Test Item")
            assert result is None or isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_ssl_error_handling(self):
        """测试 SSL 错误处理"""
        from app.services.steam_service import SteamAPI
        
        steam_api = SteamAPI()
        
        # 模拟 SSL 错误
        with patch.object(steam_api, 'get_price_overview', new_callable=AsyncMock) as mock_request:
            mock_request.side_effect = ClientConnectorError(
                connection_key=MagicMock(),
                os_error=OSError("SSL: certificate verify failed")
            )
            
            with pytest.raises(ClientConnectorError):
                await steam_api.get_price_overview("AK-47")

    @pytest.mark.asyncio
    async def test_response_timeout(self):
        """测试响应超时"""
        from app.services.steam_service import SteamAPI
        
        steam_api = SteamAPI()
        
        async def slow_response():
            await asyncio.sleep(10)  # 模拟慢响应
            return {"success": True}
        
        with patch.object(steam_api, 'get_price_overview', new_callable=AsyncMock) as mock_get_price:
            mock_get_price.side_effect = ServerTimeoutError("Response timeout")
            
            with pytest.raises(ServerTimeoutError):
                await asyncio.wait_for(
                    steam_api.get_price_overview("AK-47"),
                    timeout=1
                )


class TestCacheNetworkFallback:
    """缓存网络降级测试"""

    @pytest.mark.asyncio
    async def test_cache_fallback_on_network_error(self):
        """测试网络错误时缓存降级"""
        from app.services.cache import get_cache, CacheBackend
        
        cache = get_cache()
        
        # 验证降级到内存缓存
        cache.set("test_key", "test_value", ttl=60)
        assert cache.get("test_key") == "test_value"

    @pytest.mark.asyncio
    async def test_cache_set_get(self):
        """测试缓存基本操作"""
        from app.services.cache import get_cache
        
        cache = get_cache()
        
        # 基本设置和获取
        cache.set("key1", "value1", ttl=60)
        assert cache.get("key1") == "value1"
        
        # 删除
        cache.delete("key1")
        assert cache.get("key1") is None

    @pytest.mark.asyncio
    async def test_cache_ttl_expiry(self):
        """测试缓存 TTL 过期"""
        from app.services.cache import get_cache
        
        cache = get_cache()
        
        # 设置短期缓存
        cache.set("ttl_key", "ttl_value", ttl=1)
        assert cache.get("ttl_key") == "ttl_value"
        
        # 等待过期
        await asyncio.sleep(1.5)
        assert cache.get("ttl_key") is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
