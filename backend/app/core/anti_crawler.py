# -*- coding: utf-8 -*-
"""
反爬虫管理器
用于管理请求频率、请求模式识别和自动降级
"""
import asyncio
import logging
import time
import random
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from collections import deque
from enum import Enum

logger = logging.getLogger(__name__)


class RequestPattern(Enum):
    """请求模式类型"""
    NORMAL = "normal"
    SUSPICIOUS = "suspicious"
    BLOCKED = "blocked"


@dataclass
class RequestRecord:
    """请求记录"""
    timestamp: float
    endpoint: str
    success: bool
    response_time: float


@dataclass
class AntiCrawlerConfig:
    """反爬虫配置"""
    enabled: bool = True
    min_request_interval: float = 0.5  # 最小请求间隔（秒）
    max_request_per_minute: int = 60    # 每分钟最大请求数
    suspicious_request_count: int = 30  # 可疑请求数阈值
    block_duration: int = 300           # 封禁时长（秒）
    enable_random_delay: bool = True    # 是否启用随机延迟
    min_delay: float = 0.1              # 最小随机延迟
    max_delay: float = 0.5              # 最大随机延迟


class AntiCrawlerManager:
    """
    反爬虫管理器
    
    功能：
    1. 请求频率控制
    2. 请求模式识别
    3. 自动降级处理
    4. 请求间隔随机化
    """
    
    def __init__(self, config: Optional[AntiCrawlerConfig] = None):
        self.config = config or AntiCrawlerConfig()
        
        # 请求历史（用于模式识别）
        self._request_history: deque = deque(maxlen=1000)
        
        # 被封禁的端点
        self._blocked_endpoints: Dict[str, float] = {}
        
        # 统计信息
        self._stats = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "blocked_requests": 0,
            "delayed_requests": 0,
        }
        
        # 最后请求时间
        self._last_request_time: Dict[str, float] = {}
    
    async def before_request(self, endpoint: str) -> bool:
        """
        请求前的检查和处理
        
        Args:
            endpoint: 请求端点
            
        Returns:
            是否允许请求
        """
        if not self.config.enabled:
            return True
        
        current_time = time.time()
        
        # 检查端点是否被封禁
        if endpoint in self._blocked_endpoints:
            block_until = self._blocked_endpoints[endpoint]
            if current_time < block_until:
                remaining = int(block_until - current_time)
                logger.warning(f"端点 {endpoint} 被封禁，剩余 {remaining} 秒")
                return False
            else:
                # 解除封禁
                del self._blocked_endpoints[endpoint]
                logger.info(f"端点 {endpoint} 解除封禁")
        
        # 计算请求间隔
        last_time = self._last_request_time.get(endpoint, 0)
        elapsed = current_time - last_time
        
        # 如果间隔太短，添加延迟
        if elapsed < self.config.min_request_interval:
            wait_time = self.config.min_request_interval - elapsed
            if self.config.enable_random_delay:
                wait_time += random.uniform(self.config.min_delay, self.config.max_delay)
            await asyncio.sleep(wait_time)
            self._stats["delayed_requests"] += 1
        
        # 随机延迟（模拟人类行为）
        if self.config.enable_random_delay:
            await asyncio.sleep(random.uniform(self.config.min_delay, self.config.max_delay))
        
        # 更新最后请求时间
        self._last_request_time[endpoint] = time.time()
        
        # 记录请求
        self._request_history.append(RequestRecord(
            timestamp=current_time,
            endpoint=endpoint,
            success=True,
            response_time=0
        ))
        
        self._stats["total_requests"] += 1
        
        return True
    
    async def after_request(
        self,
        endpoint: str,
        success: bool,
        response_time: float = 0,
        status_code: int = None
    ):
        """
        请求后的处理
        
        Args:
            endpoint: 请求端点
            success: 是否成功
            response_time: 响应时间
            status_code: HTTP状态码
        """
        if not self.config.enabled:
            return
        
        current_time = time.time()
        
        # 更新统计
        if success:
            self._stats["successful_requests"] += 1
        else:
            self._stats["failed_requests"] += 1
        
        # 检查是否被反爬（检查特定状态码）
        if status_code:
            if status_code == 429:  # Too Many Requests
                await self._handle_ratelimit(endpoint)
            elif status_code == 403:  # Forbidden
                await self._handle_blocked(endpoint)
            elif status_code == 503:  # Service Unavailable
                await self._handle_blocked(endpoint)
        
        # 记录请求结果
        self._request_history.append(RequestRecord(
            timestamp=current_time,
            endpoint=endpoint,
            success=success,
            response_time=response_time
        ))
        
        # 定期检查模式
        await self._check_pattern()
    
    async def _handle_ratelimit(self, endpoint: str):
        """处理限流响应 - 使用指数退避"""
        logger.warning(f"检测到限流: {endpoint}")
        
        # 获取当前连续429错误次数
        retry_count = getattr(self, '_429_retry_counts', {})
        count = retry_count.get(endpoint, 0) + 1
        retry_count[endpoint] = count
        self._429_retry_counts = retry_count
        
        # 指数退避：基础延迟 * 2^count，最大60秒
        base_delay = 1.0  # 1秒基础延迟
        max_delay = 60.0  # 最大60秒
        delay = min(base_delay * (2 ** count), max_delay)
        
        # 添加随机抖动
        import random
        delay += random.uniform(0, delay * 0.1)
        
        logger.info(f"429限流退避: {endpoint}, count={count}, delay={delay:.2f}秒")
        
        # 更新请求间隔
        self.config.min_request_interval = delay
        
        # 如果连续429次数过多，封禁端点
        if count >= 5:
            await self._handle_blocked(endpoint)
            # 重置计数
            retry_count[endpoint] = 0
            self._429_retry_counts = retry_count
    
    async def _handle_blocked(self, endpoint: str):
        """处理被封禁"""
        logger.warning(f"检测到被封禁: {endpoint}")
        self._blocked_endpoints[endpoint] = time.time() + self.config.block_duration
        self._stats["blocked_requests"] += 1
    
    async def _check_pattern(self):
        """检查请求模式"""
        if len(self._request_history) < 10:
            return
        
        # 获取最近N个请求
        recent = list(self._request_history)[-30:]
        
        # 计算失败率
        failed = sum(1 for r in recent if not r.success)
        fail_rate = failed / len(recent)
        
        # 如果失败率过高，认为是异常模式
        if fail_rate > 0.5:
            logger.warning(f"检测到异常请求模式，失败率: {fail_rate:.2%}")
            # 可以触发告警或自动降级
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            **self._stats,
            "blocked_endpoints": list(self._blocked_endpoints.keys()),
            "current_interval": self.config.min_request_interval,
        }
    
    def reset_stats(self):
        """重置统计"""
        self._stats = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "blocked_requests": 0,
            "delayed_requests": 0,
        }
    
    def get_pattern(self) -> RequestPattern:
        """获取当前请求模式"""
        if not self._request_history:
            return RequestPattern.NORMAL
        
        recent = list(self._request_history)[-30:]
        
        if len(recent) < 10:
            return RequestPattern.NORMAL
        
        # 计算失败率
        failed = sum(1 for r in recent if not r.success)
        fail_rate = failed / len(recent)
        
        if fail_rate > 0.7:
            return RequestPattern.BLOCKED
        elif fail_rate > 0.3:
            return RequestPattern.SUSPICIOUS
        
        return RequestPattern.NORMAL
    
    async def wait_if_needed(self, url: str):
        """
        如果需要，等待合适的请求时机
        
        Args:
            url: 请求URL
        """
        endpoint = url.split("/")[-1] if url else "unknown"
        await self.before_request(endpoint)
    
    def get_headers(self) -> Dict[str, str]:
        """
        获取请求headers（用于模拟浏览器）
        
        Returns:
            请求头字典
        """
        return {
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
        }
    
    def unblock_endpoint(self, endpoint: str):
        """手动解除端点封禁"""
        if endpoint in self._blocked_endpoints:
            del self._blocked_endpoints[endpoint]
            logger.info(f"手动解除封禁: {endpoint}")
    
    def set_interval(self, interval: float):
        """设置请求间隔"""
        self.config.min_request_interval = max(0.1, interval)


# 全局实例
_anti_crawler: Optional[AntiCrawlerManager] = None


def get_anti_crawler() -> AntiCrawlerManager:
    """获取反爬虫管理器实例"""
    global _anti_crawler
    if _anti_crawler is None:
        _anti_crawler = AntiCrawlerManager()
    return _anti_crawler
