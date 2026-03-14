# -*- coding: utf-8 -*-
"""
Steam API 服务
"""
import asyncio
import hashlib
import hmac
import logging
import json
import time
from typing import Optional, Dict, List, Any, Set
from contextlib import asynccontextmanager

import aiohttp

from app.core.config import settings
from app.core.circuit_breaker import circuit_breaker, CircuitBreakerOpen, CircuitBreaker
from app.core.anti_crawler import get_anti_crawler
# 导入统一超时管理
from app.core.timeout import TimeoutCategory, get_timeout

logger = logging.getLogger(__name__)

# 使用统一超时配置
DEFAULT_TIMEOUT_CONFIG = get_timeout(TimeoutCategory.EXTERNAL_SERVICE)

# Steam Market API 配置
STEAM_MARKET_API_DELAY = 0.5  # 请求间隔（秒），避免触发反爬虫


class SteamAPIError(Exception):
    """Steam API 通用错误"""
    pass


class SteamAPICircuitOpen(SteamAPIError):
    """Steam API 熔断器开启"""
    pass


class SteamAPI:
    """Steam API 客户端"""
    
    # 默认超时配置 - 缩短为10秒以提高响应速度
    DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=10, connect=5)
    # 分类超时配置
    PRICE_TIMEOUT = aiohttp.ClientTimeout(total=5, connect=3)    # 价格查询：5秒
    INVENTORY_TIMEOUT = aiohttp.ClientTimeout(total=10, connect=5)  # 库存查询：10秒
    
    def __init__(self, api_key: Optional[str] = None, timeout: Optional[aiohttp.ClientTimeout] = None):
        self.api_key = api_key or settings.STEAM_API_KEY
        self.base_url = "https://api.steampowered.com"
        self.market_url = "https://steamcommunity.com/market"
        self._session: Optional[aiohttp.ClientSession] = None
        # 保存传入的timeout参数，用于创建session时使用
        self._timeout = timeout or self.DEFAULT_TIMEOUT
        # 集成反爬虫管理器
        self._anti_crawler = get_anti_crawler()
    
    async def health_check(self) -> bool:
        """
        检查 Session 健康状态
        
        Returns:
            是否健康
        """
        if self._session is None:
            return False
        
        # 检查 session 是否已关闭
        if self._session.closed:
            return False
        
        # 尝试发送一个轻量级请求来验证连接
        try:
            # 使用一个简单且快速的 API 端点来检查连接
            test_url = f"{self.base_url}/ISteamUser/GetPlayerSummaries/v0002/"
            params = {"key": self.api_key, "steamids": "76561197960435530"}  # 一个测试ID
            
            async with self._session.get(
                test_url,
                params=params,
                timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                # 检查响应状态码是否合理
                return response.status in (200, 400, 401)  # 400/401 表示API有效但参数问题，session本身是健康的
        except asyncio.TimeoutError:
            logger.warning("Steam API 健康检查超时")
            return False
        except aiohttp.ClientError as e:
            logger.warning(f"Steam API 健康检查失败: {e}")
            return False
        except Exception as e:
            logger.warning(f"Steam API 健康检查异常: {e}")
            return False
    
    async def ensure_healthy_session(self):
        """
        确保 Session 处于健康状态，必要时重新创建
        """
        if not await self.health_check():
            logger.info("Steam API Session 不健康，重新创建...")
            await self.close()
            # 重新创建 session，使用实例的timeout配置
            self._session = aiohttp.ClientSession(timeout=self._timeout)
    
    @property
    def session(self) -> aiohttp.ClientSession:
        """获取或创建 session（延迟初始化）"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self._timeout)
        return self._session
    
    async def close(self):
        """关闭会话"""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
    
    async def cleanup(self):
        """清理资源"""
        await self.close()
    
    async def __aenter__(self):
        """异步上下文管理器入口"""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        await self.close()
    
    async def _request(
        self,
        url: str,
        params: Optional[Dict] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """发送请求"""
        # 从URL提取endpoint用于反爬虫统计
        endpoint = url.split("/")[-1] if url else "unknown"
        
        # 使用反爬虫管理器
        await self._anti_crawler.wait_if_needed(url)
        
        headers = kwargs.pop("headers", {})
        headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        })
        # 合并反爬虫headers
        headers.update(self._anti_crawler.get_headers())
        
        timeout = kwargs.pop("timeout", None)
        start_time = time.time()
        
        try:
            async with self.session.get(
                url, 
                params=params, 
                headers=headers, 
                timeout=timeout or self.DEFAULT_TIMEOUT,
                **kwargs
            ) as response:
                response_time = time.time() - start_time
                status_code = response.status
                
                # 请求后处理（统计、更新模式识别等）
                await self._anti_crawler.after_request(
                    endpoint,
                    success=response.status == 200,
                    response_time=response_time,
                    status_code=status_code
                )
                
                if response.status != 200:
                    logger.error(f"Steam API Error: {response.status}")
                    raise Exception(f"Steam API Error: {response.status}")
                
                return await response.json()
        except asyncio.TimeoutError:
            await self._anti_crawler.after_request(endpoint, success=False, status_code=408)
            logger.error(f"Steam API 请求超时: {url}")
            raise SteamAPIError(f"请求超时: {url}")
        except CircuitBreakerOpen as e:
            await self._anti_crawler.after_request(endpoint, success=False, status_code=503)
            logger.warning(f"Steam API 熔断器开启: {e}")
            raise SteamAPICircuitOpen(str(e))
        except aiohttp.ClientError as e:
            await self._anti_crawler.after_request(endpoint, success=False, status_code=503)
            logger.error(f"Steam API 连接错误: {e}")
            raise SteamAPIError(f"连接错误: {e}")
        except Exception as e:
            await self._anti_crawler.after_request(endpoint, success=False, status_code=500)
            raise
    
    @circuit_breaker(name="steam_api", failure_threshold=5, recovery_timeout=30)
    async def get_player_summaries(self, steam_ids: List[str]) -> List[Dict[str, Any]]:
        """获取玩家基本信息"""
        if not self.api_key:
            raise Exception("需要 Steam API Key")
        
        params = {
            "key": self.api_key,
            "steamids": ",".join(steam_ids),
        }
        
        url = f"{self.base_url}/ISteamUser/GetPlayerSummaries/v0002/"
        data = await self._request(url, params=params)
        
        return data.get("response", {}).get("players", [])
    
    @circuit_breaker(name="steam_price", failure_threshold=5, recovery_timeout=30)
    async def get_price_overview(
        self,
        market_hash_name: str,
        app_id: int = 730,
        currency: int = 1  # 1=USD, 2=GBP, 3=...
    ) -> Optional[Dict[str, Any]]:
        """获取市场价格概览"""
        params = {
            "appid": app_id,
            "market_hash_name": market_hash_name,
            "currency": currency,
        }
        
        url = f"{self.market_url}/priceoverview/"
        
        try:
            # 使用价格专用超时 (5秒)
            data = await self._request(url, params=params, timeout=self.PRICE_TIMEOUT)
            return data
        except Exception as e:
            logger.warning(f"获取价格概览失败: {market_hash_name}, 错误: {e}")
            return None
    
    @circuit_breaker(name="steam_listings", failure_threshold=5, recovery_timeout=30)
    async def get_listings(
        self,
        market_hash_name: str,
        app_id: int = 730,
        start: int = 0,
        count: int = 10
    ) -> Optional[Dict[str, Any]]:
        """获取市场挂单"""
        params = {
            "appid": app_id,
            "market_hash_name": market_hash_name,
            "start": start,
            "count": count,
        }
        
        url = f"{self.market_url}/itemorders/"
        
        try:
            # 使用价格专用超时 (5秒)
            data = await self._request(url, params=params, timeout=self.PRICE_TIMEOUT)
            return data
        except Exception as e:
            logger.warning(f"获取市场挂单失败: {market_hash_name}, 错误: {e}")
            return None
    
    @circuit_breaker(name="steam_histogram", failure_threshold=5, recovery_timeout=30)
    async def get_price_histogram(
        self,
        market_hash_name: str,
        app_id: int = 730,
        currency: int = 1
    ) -> Optional[Dict[str, Any]]:
        """获取价格直方图 (历史数据)"""
        params = {
            "appid": app_id,
            "market_hash_name": market_hash_name,
            "currency": currency,
        }
        
        url = f"{self.market_url}/pricehistogram/"
        
        try:
            # 使用价格专用超时 (5秒)
            data = await self._request(url, params=params, timeout=self.PRICE_TIMEOUT)
            return data
        except Exception as e:
            logger.warning(f"获取价格直方图失败: {market_hash_name}, 错误: {e}")
            return None
    
    # ========== Steam卖出功能实现 ==========
    
    async def get_inventory(
        self,
        steam_id: str = None,
        app_id: int = 730,
        context_id: int = 2
    ) -> Dict[str, Any]:
        """
        获取Steam库存 - Steam卖出功能支持
        
        Args:
            steam_id: Steam用户ID（自己的库存可以不传）
            app_id: Steam App ID (730 = CS2/CSGO)
            context_id: 库存上下文ID (2 = 市场库存)
            
        Returns:
            库存数据
        """
        # 使用API获取库存（无需认证的公开库存）
        url = f"{self.base_url}/IEconItems_730/GetPlayerItems/v0001/"
        params = {
            "key": self.api_key,
        }
        
        if steam_id:
            params["steamid"] = steam_id
        
        try:
            # 使用库存专用超时 (10秒)
            data = await self._request(url, params=params, timeout=self.INVENTORY_TIMEOUT)
            return {
                "success": True,
                "assets": data.get("result", {}).get("items", [])
            }
        except Exception as e:
            logger.warning(f"获取Steam库存失败: {e}")
            return {"success": False, "assets": [], "error": str(e)}
    
    async def create_market_listing(
        self,
        asset_id: str,
        context_id: str = "2",
        price: float = None,
        session_token: str = None
    ) -> Dict[str, Any]:
        """
        创建Steam市场挂单 - Steam卖出功能
        
        注意：此功能需要完整的Cookie认证，请使用 SteamTrade 类
        
        Args:
            asset_id: 资产ID
            context_id: 上下文ID
            price: 价格（可选）
            session_token: Session Token（可选）
            
        Returns:
            创建结果
        """
        # 检查是否有session_token，如果有则使用完整创建流程
        if session_token:
            # 创建临时的SteamTrade实例来执行操作
            trade = SteamTrade(
                steam_id="",
                session_token=session_token
            )
            return await trade.create_listing(
                asset_id=asset_id,
                price=price or 0,
                app_id=730,
                quantity=1
            )
        
        # 如果没有认证信息，返回提示信息
        logger.warning("创建市场挂单需要完整的Session认证")
        return {
            "success": False,
            "error": "需要Steam登录认证信息",
            "message": "请配置steam_login和webcookie以使用卖出功能"
        }


class SteamTrade:
    """Steam 交易服务 (基于 SteamKit2 概念的实现)"""
    
    def __init__(
        self,
        steam_id: str,
        session_token: str,
        ma_file: Optional[Dict] = None
    ):
        self.steam_id = steam_id
        self.session_token = session_token
        self.ma_file = ma_file
        self.is_logged_in = False
        self._anti_crawler = get_anti_crawler()
    
    async def login(self) -> bool:
        """登录 Steam"""
        # 这里需要实现 SteamKit2 的登录逻辑
        # 实际实现需要使用 steamkit2 库
        self.is_logged_in = True
        return True
    
    async def get_inventory(
        self,
        app_id: int = 730,
        context_id: int = 2
    ) -> List[Dict[str, Any]]:
        """
        获取库存
        
        注意：此功能需要完整的 Steam 认证（SteamKit2）
        
        Args:
            app_id: Steam App ID
            context_id: 库存上下文 ID
            
        Returns:
            库存物品列表
            
        Raises:
            NotImplementedError: 尚未实现，需要集成 SteamKit2
        """
        # 实际实现需要使用 SteamKit2 库进行认证
        raise NotImplementedError(
            "获取库存功能需要完整的 Steam 认证支持。"
            "请使用 steam_market_service.get_my_inventory() 或集成 SteamKit2 库。"
        )
    
    async def get_trade_offers(
        self,
        get_received: bool = True,
        get_sent: bool = False
    ) -> List[Dict[str, Any]]:
        """
        获取交易报价
        
        注意：此功能需要完整的 Steam 认证（SteamKit2）
        
        Args:
            get_received: 是否获取收到的报价
            get_sent: 是否获取发送的报价
            
        Returns:
            交易报价列表
            
        Raises:
            NotImplementedError: 尚未实现，需要集成 SteamKit2
        """
        # 实际实现需要调用 Steam API / IEconService/GetTradeOffers
        raise NotImplementedError(
            "获取交易报价功能需要完整的 Steam 认证支持。"
            "请集成 SteamKit2 库。"
        )
    
    async def create_trade_offer(
        self,
        partner_steam_id: str,
        items_to_give: List[Dict] = None,
        items_to_receive: List[Dict] = None,
        message: str = ""
    ) -> Optional[str]:
        """
        创建交易报价
        
        注意：此功能需要完整的 Steam 认证（SteamKit2）
        
        Args:
            partner_steam_id: 交易对方 Steam ID
            items_to_give: 要给出的物品
            items_to_receive: 要接收的物品
            message: 留言
            
        Returns:
            交易报价 ID
            
        Raises:
            NotImplementedError: 尚未实现，需要集成 SteamKit2
        """
        # 实际实现需要调用 Steam API / IEconService/SendTradeOffer
        raise NotImplementedError(
            "创建交易报价功能需要完整的 Steam 认证支持。"
            "请集成 SteamKit2 库。"
        )
    
    async def accept_trade_offer(self, trade_offer_id: str) -> bool:
        """
        接受交易报价
        
        注意：此功能需要完整的 Steam 认证（SteamKit2）
        
        Args:
            trade_offer_id: 交易报价 ID
            
        Returns:
            是否成功
            
        Raises:
            NotImplementedError: 尚未实现，需要集成 SteamKit2
        """
        # 实际实现需要调用 Steam API
        raise NotImplementedError(
            "接受交易报价功能需要完整的 Steam 认证支持。"
            "请集成 SteamKit2 库。"
        )
    
    async def decline_trade_offer(self, trade_offer_id: str) -> bool:
        """
        拒绝交易报价
        
        注意：此功能需要完整的 Steam 认证（SteamKit2）
        
        Args:
            trade_offer_id: 交易报价 ID
            
        Returns:
            是否成功
            
        Raises:
            NotImplementedError: 尚未实现，需要集成 SteamKit2
        """
        # 实际实现需要调用 Steam API
        raise NotImplementedError(
            "拒绝交易报价功能需要完整的 Steam 认证支持。"
            "请集成 SteamKit2 库。"
        )

    # ========== Steam 市场挂单功能 ==========
    
    async def _get_market_session(self) -> aiohttp.ClientSession:
        """获取用于市场操作的 Session（需要 Cookie 认证）"""
        # 创建带有 Cookie 的 session
        if not hasattr(self, '_market_session') or self._market_session.closed:
            self._market_session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30, connect=10)
            )
        return self._market_session
    
    async def _build_market_headers(self) -> Dict[str, str]:
        """构建市场API请求头"""
        return {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/javascript, */*; charset=utf-8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://steamcommunity.com/market/",
            "Origin": "https://steamcommunity.com",
        }
    
    @circuit_breaker(name="steam_market_listings", failure_threshold=3, recovery_timeout=60)
    async def get_my_listings(
        self,
        app_id: int = 730,
        start: int = 0,
        count: int = 100
    ) -> Dict[str, Any]:
        """
        获取我的市场挂单列表
        
        Args:
            app_id: Steam App ID (730 = CS2)
            start: 起始位置
            count: 获取数量
            
        Returns:
            挂单列表数据
        """
        if not self.session_token:
            raise Exception("需要 session_token 才能访问市场")
        
        # 使用反爬虫管理器
        await self._anti_crawler.wait_if_needed(self.market_url)
        
        session = await self._get_market_session()
        
        # 构建请求
        url = f"{self.market_url}/mylistings/"
        params = {
            "start": start,
            "count": count,
            "l": "schinese",
            "cc": "CN"
        }
        
        # 添加 Cookie
        cookies = {
            "sessionid": self._generate_session_id(),
            "steamLoginSecure": self.session_token,
            "steamCurrencyId": "3"  # 人民币
        }
        
        headers = await self._build_market_headers()
        
        try:
            async with session.get(
                url,
                params=params,
                cookies=cookies,
                headers=headers
            ) as response:
                if response.status != 200:
                    logger.error(f"获取挂单列表失败: {response.status}")
                    return {"success": False, "error": f"HTTP {response.status}"}
                
                data = await response.json()
                return {
                    "success": True,
                    "listings": data.get("listings", []),
                    "total_count": data.get("total_count", 0),
                    "start": start,
                    "count": count
                }
        except Exception as e:
            logger.error(f"获取挂单列表异常: {e}")
            return {"success": False, "error": str(e)}
    
    @circuit_breaker(name="steam_market_create", failure_threshold=3, recovery_timeout=60)
    async def create_listing(
        self,
        asset_id: str,
        price: float,
        app_id: int = 730,
        quantity: int = 1
    ) -> Dict[str, Any]:
        """
        创建市场挂单
        
        Args:
            asset_id: Steam 资产 ID
            app_id: Steam App ID (730 = CS2)
            price: 单价（分）
            quantity: 数量
            
        Returns:
            创建结果
        """
        if not self.session_token:
            raise Exception("需要 session_token 才能创建挂单")
        
        # 使用反爬虫管理器
        await self._anti_crawler.wait_if_needed(self.market_url)
        
        session = await self._get_market_session()
        
        # 构建请求
        url = f"{self.market_url}/sellitem/"
        
        # 构造 form 数据
        data = {
            "sessionid": self._generate_session_id(),
            "appid": app_id,
            "assetid": asset_id,
            "contextid": 2,  # CS2 库存 context
            "amount": quantity,
            "price": int(price * 100)  # 转换为分
        }
        
        cookies = {
            "sessionid": self._generate_session_id(),
            "steamLoginSecure": self.session_token,
            "steamCurrencyId": "3"
        }
        
        headers = await self._build_market_headers()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        
        try:
            async with session.post(
                url,
                data=data,
                cookies=cookies,
                headers=headers
            ) as response:
                result = await response.json()
                
                if result.get("success", False):
                    return {
                        "success": True,
                        "listing_id": result.get("listingid", ""),
                        "price": price,
                        "asset_id": asset_id
                    }
                else:
                    error_msg = result.get("message", "未知错误")
                    logger.error(f"创建挂单失败: {error_msg}")
                    return {
                        "success": False,
                        "error": error_msg
                    }
        except Exception as e:
            logger.error(f"创建挂单异常: {e}")
            return {"success": False, "error": str(e)}
    
    @circuit_breaker(name="steam_market_cancel", failure_threshold=3, recovery_timeout=60)
    async def cancel_listing(
        self,
        listing_id: str,
        app_id: int = 730
    ) -> Dict[str, Any]:
        """
        取消市场挂单
        
        Args:
            listing_id: 挂单 ID
            app_id: Steam App ID
            
        Returns:
            取消结果
        """
        if not self.session_token:
            raise Exception("需要 session_token 才能取消挂单")
        
        # 使用反爬虫管理器
        await self._anti_crawler.wait_if_needed(self.market_url)
        
        session = await self._get_market_session()
        
        # 构建请求
        url = f"{self.market_url}/removelisting/"
        
        data = {
            "sessionid": self._generate_session_id(),
            "listingid": listing_id
        }
        
        cookies = {
            "sessionid": self._generate_session_id(),
            "steamLoginSecure": self.session_token,
        }
        
        headers = await self._build_market_headers()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        
        try:
            async with session.post(
                url,
                data=data,
                cookies=cookies,
                headers=headers
            ) as response:
                result = await response.json()
                
                if result.get("success", False):
                    return {
                        "success": True,
                        "listing_id": listing_id
                    }
                else:
                    error_msg = result.get("message", "未知错误")
                    logger.error(f"取消挂单失败: {error_msg}")
                    return {
                        "success": False,
                        "error": error_msg
                    }
        except Exception as e:
            logger.error(f"取消挂单异常: {e}")
            return {"success": False, "error": str(e)}
    
    def _generate_session_id(self) -> str:
        """生成 Session ID（用于市场操作）"""
        if not hasattr(self, '_cached_session_id'):
            # 使用 steam_id + 时间戳生成 session id
            import uuid
            self._cached_session_id = hashlib.md5(
                f"{self.steam_id}{uuid.uuid4()}".encode()
            ).hexdigest()
        return self._cached_session_id
    
    async def get_sell_history(
        self,
        app_id: int = 730,
        start: int = 0,
        count: int = 50
    ) -> Dict[str, Any]:
        """
        获取卖出历史
        
        Args:
            app_id: Steam App ID
            start: 起始位置
            count: 获取数量
            
        Returns:
            卖出历史
        """
        if not self.session_token:
            raise Exception("需要 session_token 才能查看卖出历史")
        
        await asyncio.sleep(STEAM_MARKET_API_DELAY)
        
        session = await self._get_market_session()
        
        url = f"{self.market_url}/myhistory/"
        params = {
            "start": start,
            "count": count,
            "l": "schinese",
            "cc": "CN"
        }
        
        cookies = {
            "sessionid": self._generate_session_id(),
            "steamLoginSecure": self.session_token,
        }
        
        headers = await self._build_market_headers()
        
        try:
            async with session.get(
                url,
                params=params,
                cookies=cookies,
                headers=headers
            ) as response:
                if response.status != 200:
                    return {"success": False, "error": f"HTTP {response.status}"}
                
                data = await response.json()
                return {
                    "success": True,
                    "sales": data.get("sales", []),
                    "total_count": data.get("total_count", 0)
                }
        except Exception as e:
            logger.error(f"获取卖出历史异常: {e}")
            return {"success": False, "error": str(e)}


# 全局 API 实例
_steam_api: Optional[SteamAPI] = None


def get_steam_api() -> SteamAPI:
    """获取 Steam API 实例"""
    global _steam_api
    if _steam_api is None:
        _steam_api = SteamAPI()
    return _steam_api


# 别名兼容
SteamService = SteamAPI
