# -*- coding: utf-8 -*-
"""
BUFF API 服务
"""
import asyncio
import hashlib
import time
import logging
import random
from typing import Optional, Dict, List, Any
from datetime import datetime

import aiohttp

from app.core.config import settings
from app.core.circuit_breaker import circuit_breaker, CircuitBreakerOpen
from app.core.anti_crawler import get_anti_crawler


class BuffAPIError(Exception):
    """BUFF API 通用错误"""
    pass


class BuffAPICircuitOpen(BuffAPIError):
    """BUFF API 熔断器开启"""
    pass


class RetryState:
    """重试状态追踪 - 问题8：缺乏请求重试状态追踪"""
    
    def __init__(self, endpoint: str):
        self.endpoint = endpoint
        self.total_attempts = 0
        self.successful_attempts = 0
        self.failed_attempts = 0
        self.last_error: Optional[str] = None
        self.last_attempt_time: Optional[datetime] = None


async def _exponential_backoff_with_jitter(
    retry_count: int, 
    base_delay: float = 5.0, 
    max_delay: float = 60.0
) -> float:
    """
    指数退避+随机抖动算法
    
    Args:
        retry_count: 重试次数
        base_delay: 基础延迟（秒）
        max_delay: 最大延迟（秒）
    
    Returns:
        实际等待时间（秒）
    """
    delay = min(base_delay * (2 ** retry_count), max_delay)
    jitter = delay * (0.5 + random.random())
    return jitter

logger = logging.getLogger(__name__)


from aiohttp import TCPConnector

class BuffAPI:
    """BUFF API 客户端"""
    
    # 类级别的默认超时配置
    DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=30, connect=10)
    MAX_RETRIES = 3
    RETRY_DELAY = 5  # 429 重试延迟（秒）
    
    def __init__(self, cookie: Optional[str] = None, timeout: Optional[aiohttp.ClientTimeout] = None):
        self.base_url = settings.BUFF_BASE_URL
        # 配置连接池
        connector = TCPConnector(
            limit=10,                    # 连接池最大连接数
            limit_per_host=5,            # 单主机最大连接数
            ttl_dns_cache=300,          # DNS缓存TTL（秒）
            enable_cleanup_closed=True   # 清理已关闭的连接
        )
        self.session = aiohttp.ClientSession(
            timeout=timeout or self.DEFAULT_TIMEOUT,
            connector=connector
        )
        self.cookie = cookie
        self.last_request_time = 0
        self.min_interval = settings.BUFF_API_INTERVAL
        # 问题8：重试状态追踪
        self._retry_states: Dict[str, RetryState] = {}
        # 集成反爬虫管理器
        self._anti_crawler = get_anti_crawler()
    
    def _get_retry_state(self, endpoint: str) -> RetryState:
        """获取或创建重试状态"""
        if endpoint not in self._retry_states:
            self._retry_states[endpoint] = RetryState(endpoint)
        return self._retry_states[endpoint]
    
    def get_retry_stats(self) -> Dict[str, Any]:
        """获取重试统计 - 问题8"""
        return {
            endpoint: {
                "total": state.total_attempts,
                "success": state.successful_attempts,
                "failed": state.failed_attempts,
                "success_rate": state.successful_attempts / state.total_attempts * 100
                    if state.total_attempts > 0 else 0,
                "last_error": state.last_error,
                "last_attempt": state.last_attempt_time.isoformat() if state.last_attempt_time else None
            }
            for endpoint, state in self._retry_states.items()
        }
    
    async def close(self):
        """关闭会话"""
        await self.session.close()
    
    async def cleanup(self):
        """清理资源"""
        await self.close()
    
    @circuit_breaker(name="buff_api", failure_threshold=5, recovery_timeout=30)
    async def _request(
        self,
        method: str,
        url: str,
        max_retries: int = None,
        **kwargs
    ) -> Dict[str, Any]:
        """发送请求 (带频率控制和重试机制) - 问题8：添加重试状态追踪"""
        max_retries = max_retries or self.MAX_RETRIES
        retry_count = 0
        # 提取endpoint用于追踪
        endpoint = url.split('/api')[-1] if '/api' in url else url
        retry_state = self._get_retry_state(endpoint)
        
        while retry_count < max_retries:
            try:
                # 使用反爬虫管理器
                await self._anti_crawler.wait_if_needed(url)
                
                # 频率控制
                elapsed = time.time() - self.last_request_time
                if elapsed < self.min_interval:
                    await asyncio.sleep(self.min_interval - elapsed)
                
                # 设置默认 headers
                headers = kwargs.pop("headers", {})
                headers.update({
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Referer": self.base_url,
                })
                # 合并反爬虫headers
                headers.update(self._anti_crawler.get_headers())
                if self.cookie:
                    headers["Cookie"] = self.cookie
                
                kwargs["headers"] = headers
                
                start_time = time.time()
                
                # 发送请求
                async with self.session.request(method, url, **kwargs) as response:
                    self.last_request_time = time.time()
                    response_time = time.time() - start_time
                    status_code = response.status
                    
                    # 请求后处理（统计、更新模式识别等）
                    await self._anti_crawler.after_request(
                        endpoint,
                        success=response.status == 200,
                        response_time=response_time,
                        status_code=status_code
                    )
                    
                    if response.status == 429:
                        # 请求过于频繁，使用指数退避+抖动后重试
                        retry_count += 1
                        retry_state.total_attempts += 1
                        retry_state.failed_attempts += 1
                        retry_state.last_error = "429 Too Many Requests"
                        retry_state.last_attempt_time = datetime.utcnow()
                        
                        if retry_count > max_retries:
                            raise Exception(f"BUFF API 429 错误: 超过最大重试次数 {max_retries}")
                        delay = await _exponential_backoff_with_jitter(retry_count)
                        logger.warning(f"BUFF API 429 错误，第 {retry_count} 次重试，等待 {delay:.2f} 秒...")
                        await asyncio.sleep(delay)
                        continue
                    
                    if response.status != 200:
                        raise Exception(f"BUFF API Error: {response.status}")
                    
                    data = await response.json()
                    
                    if data.get("code") != "OK":
                        raise Exception(f"BUFF API Error: {data.get('message', 'Unknown error')}")
                    
                    # 问题8：记录成功
                    retry_state.total_attempts += 1
                    retry_state.successful_attempts += 1
                    retry_state.last_attempt_time = datetime.utcnow()
                    
                    return data.get("data", {})
                    
            except asyncio.TimeoutError:
                retry_count += 1
                retry_state.total_attempts += 1
                retry_state.failed_attempts += 1
                retry_state.last_error = "Timeout"
                retry_state.last_attempt_time = datetime.utcnow()
                
                if retry_count > max_retries:
                    raise BuffAPIError(f"BUFF API 请求超时: 超过最大重试次数 {max_retries}")
                delay = await _exponential_backoff_with_jitter(retry_count)
                logger.warning(f"BUFF API 请求超时，第 {retry_count} 次重试，等待 {delay:.2f} 秒...")
                await asyncio.sleep(delay)
                continue
            except CircuitBreakerOpen as e:
                # 熔断器开启，不再重试，直接抛出异常
                retry_state.total_attempts += 1
                retry_state.failed_attempts += 1
                retry_state.last_error = f"Circuit breaker open: {e}"
                retry_state.last_attempt_time = datetime.utcnow()
                logger.warning(f"BUFF API 熔断器开启: {e}")
                raise BuffAPICircuitOpen(str(e))
            except aiohttp.ClientError as e:
                retry_count += 1
                retry_state.total_attempts += 1
                retry_state.failed_attempts += 1
                retry_state.last_error = str(e)
                retry_state.last_attempt_time = datetime.utcnow()
                
                if retry_count > max_retries:
                    raise Exception(f"BUFF API 连接错误: {e}")
                delay = await _exponential_backoff_with_jitter(retry_count)
                logger.warning(f"BUFF API 连接错误: {e}，第 {retry_count} 次重试，等待 {delay:.2f} 秒...")
                await asyncio.sleep(delay)
                continue
            except Exception as e:
                # 其他异常也记录
                retry_state.total_attempts += 1
                retry_state.failed_attempts += 1
                retry_state.last_error = str(e)
                retry_state.last_attempt_time = datetime.utcnow()
                raise
        
        raise Exception("BUFF API 请求失败: 达到最大重试次数")
    
    async def get_goods_list(
        self,
        page: int = 1,
        page_size: int=20,
        category: Optional[str] = None,
        search: Optional[str] = None,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """获取商品列表"""
        params = {
            "page": page,
            "page_num": page_size,
            "app": "csgo",
        }
        
        if category:
            params["category"] = category
        if search:
            params["search"] = search
        if min_price is not None:
            params["min_price"] = min_price
        if max_price is not None:
            params["max_price"] = max_price
        
        url = f"{self.base_url}/api/market/goods"
        data = await self._request("GET", url, params=params)
        
        return data.get("items", [])
    
    async def get_goods_detail(self, goods_id: int) -> Dict[str, Any]:
        """获取商品详情"""
        params = {"id": goods_id}
        url = f"{self.base_url}/api/market/goods/detail"
        data = await self._request("GET", url, params=params)
        return data
    
    async def get_price_overview(
        self,
        market_hash_name: str,
        app_id: int = 730
    ) -> Optional[Dict[str, Any]]:
        """获取价格概览"""
        params = {
            "market_hash_name": market_hash_name,
            "appid": app_id,
        }
        
        url = f"{self.base_url}/api/market/price_overview/csgo"
        
        try:
            data = await self._request("GET", url, params=params)
            return data
        except Exception as e:
            logger.error(f"Failed to get price overview for {market_hash_name}: {e}")
            return None
    
    async def create_order(
        self,
        goods_id: int,
        price: float,
        num: int = 1
    ) -> Dict[str, Any]:
        """创建订单"""
        if not self.cookie:
            raise Exception("需要登录 BUFF 账户")
        
        data = {
            "goods_id": goods_id,
            "price": price,
            "num": num,
        }
        
        url = f"{self.base_url}/api/market/order/create"
        logger.info(f"尝试创建订单: goods_id={goods_id}, price={price}, num={num}")
        
        try:
            result = await self._request("POST", url, json=data)
            logger.info(f"订单创建成功: goods_id={goods_id}, result={result}")
            return result
        except Exception as e:
            logger.error(f"订单创建失败: goods_id={goods_id}, error={e}")
            raise
    
    async def cancel_order(self, order_id: int) -> Dict[str, Any]:
        """取消订单"""
        data = {"id": order_id}
        url = f"{self.base_url}/api/market/order/cancel"
        logger.info(f"尝试取消订单: order_id={order_id}")
        
        try:
            result = await self._request("POST", url, json=data)
            logger.info(f"订单取消成功: order_id={order_id}")
            return result
        except Exception as e:
            logger.error(f"订单取消失败: order_id={order_id}, error={e}")
            raise
    
    async def get_my_orders(
        self,
        side: str = "sell",  # buy / sell
        page: int = 1,
        page_size: int = 20
    ) -> Dict[str, Any]:
        """获取我的订单"""
        if not self.cookie:
            raise Exception("需要登录 BUFF 账户")
        
        params = {
            "side": side,
            "page": page,
            "page_num": page_size,
        }
        
        url = f"{self.base_url}/api/market/my_order"
        data = await self._request("GET", url, params=params)
        return data
    
    async def get_balance(self) -> Optional[float]:
        """获取账户余额"""
        if not self.cookie:
            return None
        
        url = f"{self.base_url}/api/user/balance"
        logger.info("获取BUFF账户余额")
        
        try:
            data = await self._request("GET", url)
            balance = float(data.get("data", {}).get("balance", 0))
            logger.info(f"获取余额成功: {balance}")
            return balance
        except Exception as e:
            logger.error(f"获取余额失败: {e}")
            return None
    
    async def add_to_cart(self, goods_id: int, price: float) -> Dict[str, Any]:
        """添加到购物车"""
        if not self.cookie:
            raise Exception("需要登录 BUFF 账户")
        
        data = {
            "goods_id": goods_id,
            "price": price,
        }
        
        url = f"{self.base_url}/api/market/cart/add"
        result = await self._request("POST", url, json=data)
        return result
    
    async def purchase_cart(self) -> Dict[str, Any]:
        """购买购物车中的商品"""
        if not self.cookie:
            raise Exception("需要登录 BUFF 账户")
        
        url = f"{self.base_url}/api/market/cart/purchase"
        result = await self._request("POST", url)
        return result


# 全局客户端实例 - LRU 缓存
_buff_clients: Dict[str, BuffAPI] = {}
_buff_clients_order: List[str] = []  # 记录访问顺序
MAX_CLIENTS = 10  # 最大客户端数量


def _evict_oldest_client():
    """驱逐最旧的客户端"""
    global _buff_clients, _buff_clients_order
    if _buff_clients_order:
        oldest_key = _buff_clients_order.pop(0)
        if oldest_key in _buff_clients:
            # 关闭旧的客户端连接
            old_client = _buff_clients.pop(oldest_key)
            asyncio.create_task(old_client.close())


def get_buff_client(cookie: Optional[str] = None) -> BuffAPI:
    """获取 BUFF 客户端"""
    global _buff_clients, _buff_clients_order
    
    if cookie:
        # 根据 cookie 哈希创建唯一实例
        key = hashlib.md5(cookie.encode()).hexdigest()
        if key in _buff_clients:
            # 移动到末尾（表示最近使用）
            _buff_clients_order.remove(key)
            _buff_clients_order.append(key)
        else:
            # 检查是否需要驱逐旧客户端
            if len(_buff_clients) >= MAX_CLIENTS:
                _evict_oldest_client()
            _buff_clients[key] = BuffAPI(cookie)
            _buff_clients_order.append(key)
        return _buff_clients[key]
    
    return BuffAPI()
