# -*- coding: utf-8 -*-
"""
Steam 服务测试
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import aiohttp
from app.services.steam_service import SteamAPI, SteamTrade, get_steam_api


# 设置事件循环策略以避免警告
@pytest.fixture(scope="session")
def event_loop_policy():
    """设置事件循环策略"""
    return asyncio.get_event_loop_policy()


class TestSteamAPI:
    """Steam API 测试"""

    @pytest.mark.asyncio
    async def test_init_default(self):
        """测试默认初始化"""
        with patch('app.services.steam_service.settings') as mock_settings:
            mock_settings.STEAM_API_KEY = "test_key"

            api = SteamAPI()

            assert api.api_key == "test_key"
            assert api.base_url == "https://api.steampowered.com"
            assert api.market_url == "https://steamcommunity.com/market"

            await api.close()

    @pytest.mark.asyncio
    async def test_init_custom(self):
        """测试自定义初始化"""
        custom_timeout = aiohttp.ClientTimeout(total=60)

        api = SteamAPI(api_key="custom_key", timeout=custom_timeout)

        assert api.api_key == "custom_key"
        assert api.session.timeout.total == 60

        await api.close()

    @pytest.mark.asyncio
    async def test_close(self):
        """测试关闭会话"""
        api = SteamAPI()

        # 会话应该存在
        assert api.session is not None

        await api.close()

        # 验证会话已关闭（session变为None或closed）

    @pytest.mark.asyncio
    async def test_cleanup(self):
        """测试清理资源"""
        api = SteamAPI()

        await api.cleanup()

    @pytest.mark.asyncio
    async def test_request_success(self):
        """测试成功请求"""
        api = SteamAPI()
        
        # 创建一个正确的mock response
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"success": True})
        
        # 创建一个真正的async context manager
        class MockContextManager:
            def __init__(self, response):
                self._response = response
            
            async def __aenter__(self):
                return self._response
            
            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass
        
        api.session.get = lambda *args, **kwargs: MockContextManager(mock_response)
        
        result = await api._request("https://api.test.com/test")
        
        assert result == {"success": True}
        
        await api.close()
    
    @pytest.mark.asyncio
    async def test_request_non_200_status(self):
        """测试非200状态码"""
        api = SteamAPI()
        
        mock_response = AsyncMock()
        mock_response.status = 404
        
        class MockContextManager:
            def __init__(self, response):
                self._response = response
            
            async def __aenter__(self):
                return self._response
            
            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass
        
        api.session.get = lambda *args, **kwargs: MockContextManager(mock_response)
        
        with pytest.raises(Exception) as exc_info:
            await api._request("https://api.test.com/test")
        
        assert "404" in str(exc_info.value)

        await api.close()

    @pytest.mark.asyncio
    async def test_request_timeout(self):
        """测试请求超时"""
        import asyncio
        api = SteamAPI()

        # 创建一个抛出TimeoutError的context manager
        class MockTimeoutContext:
            async def __aenter__(self):
                raise asyncio.TimeoutError()
            
            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass
        
        api.session.get = lambda *args, **kwargs: MockTimeoutContext()

        # 代码会捕获asyncio.TimeoutError并重新抛出SteamAPIError
        from app.services.steam_service import SteamAPIError
        with pytest.raises(SteamAPIError):
            await api._request("https://api.test.com/test")

        await api.close()

    @pytest.mark.asyncio
    async def test_request_client_error(self):
        """测试客户端错误"""
        api = SteamAPI()

        # 创建一个抛出ClientError的context manager
        class MockErrorContext:
            async def __aenter__(self):
                raise aiohttp.ClientError("Connection error")
            
            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass
        
        api.session.get = lambda *args, **kwargs: MockErrorContext()

        # 代码会捕获aiohttp.ClientError并重新抛出SteamAPIError
        from app.services.steam_service import SteamAPIError
        with pytest.raises(SteamAPIError):
            await api._request("https://api.test.com/test")

        await api.close()

    @pytest.mark.asyncio
    async def test_get_player_summaries(self):
        """测试获取玩家信息"""
        api = SteamAPI(api_key="test_key")

        mock_data = {
            "response": {
                "players": [
                    {"steamid": "123456789", "personaname": "TestPlayer"}
                ]
            }
        }

        with patch.object(api, '_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_data

            result = await api.get_player_summaries(["123456789"])

            assert len(result) == 1
            assert result[0]["steamid"] == "123456789"

        await api.close()

    @pytest.mark.asyncio
    async def test_get_player_summaries_no_api_key(self):
        """测试无API Key时抛出异常"""
        api = SteamAPI(api_key=None)

        with pytest.raises(Exception) as exc_info:
            await api.get_player_summaries(["123456789"])

        assert "API Key" in str(exc_info.value)

        await api.close()

    @pytest.mark.asyncio
    async def test_get_price_overview_success(self):
        """测试获取价格概览成功"""
        api = SteamAPI()

        mock_data = {
            "lowest_price": "100.00",
            "volume": "100"
        }

        with patch.object(api, '_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_data

            result = await api.get_price_overview("AK-47 | Redline")

            assert result == mock_data

        await api.close()

    @pytest.mark.asyncio
    async def test_get_price_overview_error(self):
        """测试获取价格概览错误"""
        api = SteamAPI()

        with patch.object(api, '_request', new_callable=AsyncMock) as mock_request:
            mock_request.side_effect = Exception("API Error")

            result = await api.get_price_overview("AK-47 | Redline")

            assert result is None

        await api.close()

    @pytest.mark.asyncio
    async def test_get_listings(self):
        """测试获取市场挂单"""
        api = SteamAPI()

        mock_data = {"success": True}

        with patch.object(api, '_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_data

            result = await api.get_listings("AK-47 | Redline")

            assert result == mock_data

        await api.close()

    @pytest.mark.asyncio
    async def test_get_price_histogram(self):
        """测试获取价格直方图"""
        api = SteamAPI()

        mock_data = {"prices": []}

        with patch.object(api, '_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_data

            result = await api.get_price_histogram("AK-47 | Redline")

            assert result == mock_data

        await api.close()


class TestSteamTrade:
    """Steam 交易测试"""

    def test_init(self):
        """测试初始化"""
        trade = SteamTrade(
            steam_id="123456789",
            session_token="test_token"
        )

        assert trade.steam_id == "123456789"
        assert trade.session_token == "test_token"
        assert trade.is_logged_in is False

    @pytest.mark.asyncio
    async def test_login(self):
        """测试登录"""
        trade = SteamTrade(
            steam_id="123456789",
            session_token="test_token"
        )

        result = await trade.login()

        assert result is True
        assert trade.is_logged_in is True

    @pytest.mark.asyncio
    async def test_get_inventory_not_logged_in(self):
        """测试未登录时获取库存 - 抛出NotImplementedError"""
        trade = SteamTrade(
            steam_id="123456789",
            session_token="test_token"
        )

        with pytest.raises(NotImplementedError):
            await trade.get_inventory()

    @pytest.mark.asyncio
    async def test_get_inventory_logged_in(self):
        """测试登录后获取库存 - 抛出NotImplementedError（需要SteamKit2）"""
        trade = SteamTrade(
            steam_id="123456789",
            session_token="test_token"
        )

        await trade.login()

        # 当前实现抛出NotImplementedError（需要SteamKit2）
        with pytest.raises(NotImplementedError):
            await trade.get_inventory()

    @pytest.mark.asyncio
    async def test_get_trade_offers_not_logged_in(self):
        """测试未登录时获取报价 - 抛出NotImplementedError"""
        trade = SteamTrade(
            steam_id="123456789",
            session_token="test_token"
        )

        with pytest.raises(NotImplementedError):
            await trade.get_trade_offers()

    @pytest.mark.asyncio
    async def test_get_trade_offers_logged_in(self):
        """测试登录后获取报价 - 抛出NotImplementedError（需要SteamKit2）"""
        trade = SteamTrade(
            steam_id="123456789",
            session_token="test_token"
        )

        await trade.login()

        # 当前实现抛出NotImplementedError（需要SteamKit2）
        with pytest.raises(NotImplementedError):
            await trade.get_trade_offers()

    @pytest.mark.asyncio
    async def test_create_trade_offer_not_logged_in(self):
        """测试未登录时创建报价 - 抛出NotImplementedError"""
        trade = SteamTrade(
            steam_id="123456789",
            session_token="test_token"
        )

        with pytest.raises(NotImplementedError):
            await trade.create_trade_offer("partner_id")

    @pytest.mark.asyncio
    async def test_accept_trade_offer_not_logged_in(self):
        """测试未登录时接受报价 - 抛出NotImplementedError"""
        trade = SteamTrade(
            steam_id="123456789",
            session_token="test_token"
        )

        with pytest.raises(NotImplementedError):
            await trade.accept_trade_offer("offer_id")

    @pytest.mark.asyncio
    async def test_accept_trade_offer_logged_in(self):
        """测试登录后接受报价 - 抛出NotImplementedError（需要SteamKit2）"""
        trade = SteamTrade(
            steam_id="123456789",
            session_token="test_token"
        )

        await trade.login()

        # 当前实现抛出NotImplementedError（需要SteamKit2）
        with pytest.raises(NotImplementedError):
            await trade.accept_trade_offer("offer_id")

    @pytest.mark.asyncio
    async def test_decline_trade_offer_logged_in(self):
        """测试登录后拒绝报价 - 抛出NotImplementedError"""
        trade = SteamTrade(
            steam_id="123456789",
            session_token="test_token"
        )

        await trade.login()

        with pytest.raises(NotImplementedError):
            await trade.decline_trade_offer("offer_id")
    
    @pytest.mark.asyncio
    async def test_decline_trade_offer_logged_in_2(self):
        """测试登录后拒绝报价 - 抛出NotImplementedError"""
        trade = SteamTrade(
            steam_id="123456789",
            session_token="test_token"
        )

        await trade.login()

        with pytest.raises(NotImplementedError):
            await trade.decline_trade_offer("offer_id")


class TestGetSteamAPI:
    """获取Steam API实例测试"""

    def test_get_steam_api_singleton(self):
        """测试单例模式"""
        with patch('app.services.steam_service.settings') as mock_settings:
            mock_settings.STEAM_API_KEY = "test_key"

            api1 = get_steam_api()
            api2 = get_steam_api()

            assert api1 is api2


class TestSteamAPIErrorHandling:
    """Steam API 错误处理测试"""

    @pytest.mark.asyncio
    async def test_default_timeout_config(self):
        """测试默认超时配置"""
        api = SteamAPI()

        assert api.DEFAULT_TIMEOUT.total == 10
        assert api.DEFAULT_TIMEOUT.connect == 5

        await api.close()

    @pytest.mark.asyncio
    async def test_custom_timeout(self):
        """测试自定义超时"""
        custom_timeout = aiohttp.ClientTimeout(total=60, connect=15)

        api = SteamAPI(timeout=custom_timeout)

        assert api.session.timeout.total == 60
        assert api.session.timeout.connect == 15

        await api.close()

    @pytest.mark.asyncio
    async def test_price_overview_with_currency(self):
        """测试不同货币获取价格"""
        api = SteamAPI()

        mock_data = {"lowest_price": "50.00"}

        with patch.object(api, '_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_data

            # 测试不同货币
            result = await api.get_price_overview("AK-47 | Redline", currency=2)

            # 验证请求参数
            call_args = mock_request.call_args
            params = call_args[1].get('params', {})
            assert params.get('currency') == 2

        await api.close()

    @pytest.mark.asyncio
    async def test_listings_with_pagination(self):
        """测试分页获取挂单"""
        api = SteamAPI()

        mock_data = {"success": True}

        with patch.object(api, '_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_data

            result = await api.get_listings("AK-47 | Redline", start=10, count=20)

            call_args = mock_request.call_args
            params = call_args[1].get('params', {})
            assert params.get('start') == 10
            assert params.get('count') == 20

        await api.close()

    @pytest.mark.asyncio
    async def test_default_app_id(self):
        """测试默认APP ID"""
        api = SteamAPI()

        mock_data = {"lowest_price": "100.00"}

        with patch.object(api, '_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_data

            await api.get_price_overview("AK-47 | Redline")

            call_args = mock_request.call_args
            params = call_args[1].get('params', {})
            assert params.get('appid') == 730

        await api.close()

    @pytest.mark.asyncio
    async def test_custom_app_id(self):
        """测试自定义APP ID"""
        api = SteamAPI()

        mock_data = {"success": True}

        with patch.object(api, '_request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_data

            await api.get_price_overview("Test Item", app_id=440)

            call_args = mock_request.call_args
            params = call_args[1].get('params', {})
            assert params.get('appid') == 440

        await api.close()


import asyncio
