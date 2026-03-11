# -*- coding: utf-8 -*-
"""
Steam 市场交易服务
提供Steam市场挂单功能：创建、取消、查询挂单
"""
import asyncio
import logging
from typing import Optional, Dict, List, Any
from datetime import datetime
from enum import Enum

import aiohttp

from app.core.config import settings
from app.core.circuit_breaker import circuit_breaker, CircuitBreakerOpen

logger = logging.getLogger(__name__)


class MarketListingStatus(str, Enum):
    """市场挂单状态"""
    ACTIVE = "active"
    SOLD = "sold"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class SteamMarketError(Exception):
    """Steam 市场通用错误"""
    pass


class SteamMarketAuthError(SteamMarketError):
    """Steam 市场认证错误"""
    pass


class SteamMarketService:
    """Steam 市场交易服务"""
    
    # Steam 市场 API 配置
    BASE_URL = "https://steamcommunity.com/market"
    API_VERSION = "/v1"
    
    # CS2 App ID
    APP_ID_CS2 = 730
    
    # 货币类型 (1=USD)
    CURRENCY_USD = 1
    
    def __init__(
        self,
        session: Optional[aiohttp.ClientSession] = None,
        timeout: Optional[aiohttp.ClientTimeout] = None
    ):
        self._session = session
        self.timeout = timeout or aiohttp.ClientTimeout(total=30, connect=10)
        
        # Steam Cookie 认证信息 (从 settings 获取)
        self.steam_login = getattr(settings, 'STEAM_LOGIN', None)
        self.session_token = getattr(settings, 'STEAM_SESSION_TOKEN', None)
        self.webcookie = getattr(settings, 'STEAM_WEBCOOKIE', None)
    
    @property
    def session(self) -> aiohttp.ClientSession:
        """获取或创建 session"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self.timeout)
        return self._session
    
    async def close(self):
        """关闭会话"""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
    
    def _get_headers(self) -> Dict[str, str]:
        """获取请求头"""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        if self.webcookie:
            headers["Cookie"] = f"webcookie={self.webcookie}"
        return headers
    
    async def _request(
        self,
        method: str,
        url: str,
        params: Optional[Dict] = None,
        data: Optional[Dict] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """发送请求"""
        headers = self._get_headers()
        
        try:
            async with self.session.request(
                method,
                url,
                params=params,
                json=data,
                headers=headers,
                timeout=self.timeout,
                **kwargs
            ) as response:
                if response.status == 403:
                    raise SteamMarketAuthError("Steam 市场认证失败，请检查登录状态")
                elif response.status == 429:
                    raise SteamMarketError("请求过于频繁，请稍后重试")
                
                # 尝试解析 JSON，失败则返回文本
                try:
                    result = await response.json()
                except:
                    text = await response.text()
                    logger.warning(f"Steam Market API 返回非JSON: {text[:200]}")
                    result = {"raw": text}
                
                # 检查 Steam 错误
                if isinstance(result, dict):
                    if result.get("success") is False:
                        error_msg = result.get("message", "未知错误")
                        raise SteamMarketError(f"Steam 市场错误: {error_msg}")
                
                return result
                
        except asyncio.TimeoutError:
            logger.error(f"Steam Market 请求超时: {url}")
            raise SteamMarketError(f"请求超时: {url}")
        except aiohttp.ClientError as e:
            logger.error(f"Steam Market 连接错误: {e}")
            raise SteamMarketError(f"连接错误: {e}")
    
    @circuit_breaker(name="steam_market_listings", failure_threshold=5, recovery_timeout=30)
    async def get_my_listings(
        self,
        app_id: int = APP_ID_CS2,
        start: int = 0,
        count: int = 100
    ) -> Dict[str, Any]:
        """
        获取我的市场挂单
        
        Args:
            app_id: Steam 应用ID (730=CS2)
            start: 起始位置
            count: 获取数量
            
        Returns:
            包含挂单列表的字典
        """
        if not self.session_token and not self.webcookie:
            raise SteamMarketAuthError("需要 Steam 会话令牌或 Web Cookie")
        
        url = f"{self.BASE_URL}/getmy listings{self.API_VERSION}/"
        
        params = {
            "appid": app_id,
            "start": start,
            "count": count,
        }
        
        result = await self._request("GET", url, params=params)
        
        # 解析挂单数据
        listings = []
        if result.get("success"):
            assets = result.get("assets", {})
            listings_data = result.get("listings", [])
            
            for listing in listings_data:
                listing_id = listing.get("listingid")
                price = listing.get("price", 0) / 100  # Steam 价格单位是分
                fee = listing.get("fee", 0) / 100
                
                # 获取物品信息
                item_name = listing.get("name", "Unknown")
                item_hash = listing.get("hash_name", "")
                
                listings.append({
                    "listing_id": listing_id,
                    "price": price,
                    "fee": fee,
                    "item_name": item_name,
                    "market_hash_name": item_hash,
                    "quantity": listing.get("quantity", 1),
                    "status": MarketListingStatus.ACTIVE.value,
                    "created_at": datetime.utcnow(),  # Steam 不返回创建时间
                })
        
        return {
            "success": True,
            "listings": listings,
            "total": result.get("total_count", len(listings)),
            "start": start,
            "count": count,
        }
    
    @circuit_breaker(name="steam_market_create", failure_threshold=3, recovery_timeout=60)
    async def create_listing(
        self,
        asset_id: str,
        app_id: int = APP_ID_CS2,
        price: float = None,
        market_hash_name: str = None,
        quantity: int = 1
    ) -> Dict[str, Any]:
        """
        创建市场挂单
        
        Args:
            asset_id: Steam 库存物品的 asset_id
            app_id: Steam 应用ID (730=CS2)
            price: 售价 (美元)
            market_hash_name: 物品的 market_hash_name
            quantity: 数量
            
        Returns:
            创建结果
        """
        if not self.session_token and not self.webcookie:
            raise SteamMarketAuthError("需要 Steam 会话令牌或 Web Cookie")
        
        if not price and not market_hash_name:
            raise SteamMarketError("需要提供价格或物品名称")
        
        # 定价 API
        url = f"{self.BASE_URL}/sellitem{self.API_VERSION}/"
        
        # 价格需要转换为分
        price_cents = int(price * 100) if price else 0
        
        data = {
            "appid": app_id,
            "assetid": asset_id,
            "contextid": 2,  # 市场交易上下文
            "amount": quantity,
            "price": price_cents,
        }
        
        result = await self._request("POST", url, data=data)
        
        if result.get("success"):
            return {
                "success": True,
                "listing_id": result.get("listingid"),
                "price": price,
                "message": "挂单创建成功"
            }
        else:
            error_msg = result.get("message", "创建挂单失败")
            raise SteamMarketError(f"创建挂单失败: {error_msg}")
    
    @circuit_breaker(name="steam_market_cancel", failure_threshold=3, recovery_timeout=60)
    async def cancel_listing(
        self,
        listing_id: str,
        app_id: int = APP_ID_CS2
    ) -> Dict[str, Any]:
        """
        取消市场挂单
        
        Args:
            listing_id: 挂单 ID
            app_id: Steam 应用ID
            
        Returns:
            取消结果
        """
        if not self.session_token and not self.webcookie:
            raise SteamMarketAuthError("需要 Steam 会话令牌或 Web Cookie")
        
        url = f"{self.BASE_URL}/cancelitemlisting{self.API_VERSION}/"
        
        data = {
            "appid": app_id,
            "listingid": listing_id,
        }
        
        result = await self._request("POST", url, data=data)
        
        if result.get("success"):
            return {
                "success": True,
                "listing_id": listing_id,
                "message": "挂单已取消"
            }
        else:
            error_msg = result.get("message", "取消挂单失败")
            raise SteamMarketError(f"取消挂单失败: {error_msg}")
    
    @circuit_breaker(name="steam_market_price", failure_threshold=5, recovery_timeout=30)
    async def get_item_price(
        self,
        market_hash_name: str,
        app_id: int = APP_ID_CS2,
        currency: int = CURRENCY_USD
    ) -> Optional[Dict[str, Any]]:
        """
        获取物品当前市场价格
        
        Args:
            market_hash_name: 物品的市场名称
            app_id: Steam 应用ID
            currency: 货币类型
            
        Returns:
            价格信息
        """
        url = f"{self.BASE_URL}/priceoverview/"
        
        params = {
            "appid": app_id,
            "market_hash_name": market_hash_name,
            "currency": currency,
        }
        
        try:
            result = await self._request("GET", url, params=params)
            
            if result.get("success"):
                return {
                    "success": True,
                    "lowest_price": result.get("lowest_price", ""),
                    "volume": result.get("volume", ""),
                    "median_price": result.get("median_price", ""),
                }
        except Exception as e:
            logger.warning(f"获取物品价格失败: {market_hash_name}, 错误: {e}")
        
        return None


# 全局实例
_steam_market: Optional[SteamMarketService] = None


def get_steam_market_service() -> SteamMarketService:
    """获取 Steam 市场服务实例"""
    global _steam_market
    if _steam_market is None:
        _steam_market = SteamMarketService()
    return _steam_market
