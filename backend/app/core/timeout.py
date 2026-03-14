# -*- coding: utf-8 -*-
"""
统一超时配置模块
提供各类超时配置的集中管理
"""
from dataclasses import dataclass
from typing import Dict, Optional
from enum import Enum


class TimeoutCategory(str, Enum):
    """超时类别"""
    TRADING = "trading"           # 交易操作
    API_REQUEST = "api_request"   # API请求
    DATABASE = "database"          # 数据库操作
    CACHE = "cache"               # 缓存操作
    WEBSOCKET = "websocket"       # WebSocket连接
    EXTERNAL_SERVICE = "external"   # 外部服务


@dataclass
class TimeoutConfig:
    """超时配置"""
    category: TimeoutCategory
    default: int          # 默认超时（秒）
    min: int             # 最小超时
    max: int             # 最大超时
    description: str     # 说明


# 超时配置表
TIMEOUT_CONFIGS: Dict[TimeoutCategory, TimeoutConfig] = {
    TimeoutCategory.TRADING: TimeoutConfig(
        category=TimeoutCategory.TRADING,
        default=30,
        min=5,
        max=300,
        description="交易操作超时（买入、卖出、确认）"
    ),
    TimeoutCategory.API_REQUEST: TimeoutConfig(
        category=TimeoutCategory.API_REQUEST,
        default=10,
        min=3,
        max=60,
        description="外部API请求超时"
    ),
    TimeoutCategory.DATABASE: TimeoutConfig(
        category=TimeoutCategory.DATABASE,
        default=5,
        min=1,
        max=30,
        description="数据库操作超时"
    ),
    TimeoutCategory.CACHE: TimeoutConfig(
        category=TimeoutCategory.CACHE,
        default=3,
        min=1,
        max=10,
        description="缓存操作超时"
    ),
    TimeoutCategory.WEBSOCKET: TimeoutConfig(
        category=TimeoutCategory.WEBSOCKET,
        default=30,
        min=10,
        max=120,
        description="WebSocket连接超时"
    ),
    TimeoutCategory.EXTERNAL_SERVICE: TimeoutConfig(
        category=TimeoutCategory.EXTERNAL_SERVICE,
        default=15,
        min=5,
        max=120,
        description="外部服务（Steam、BUFF等）超时"
    ),
}


class TimeoutManager:
    """超时管理器"""
    
    _instance: Optional['TimeoutManager'] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._custom_overrides: Dict[TimeoutCategory, int] = {}
        return cls._instance
    
    def get_timeout(self, category: TimeoutCategory, custom: Optional[int] = None) -> int:
        """
        获取超时时间
        
        Args:
            category: 超时类别
            custom: 自定义超时（可选）
            
        Returns:
            超时时间（秒）
        """
        config = TIMEOUT_CONFIGS.get(category)
        if not config:
            return 10  # 默认10秒
        
        # 优先使用自定义值
        if custom is not None:
            return max(config.min, min(config.max, custom))
        
        # 其次使用覆盖值
        if category in self._custom_overrides:
            return self._custom_overrides[category]
        
        return config.default
    
    def set_override(self, category: TimeoutCategory, timeout: int) -> None:
        """设置超时覆盖值"""
        config = TIMEOUT_CONFIGS.get(category)
        if config:
            self._custom_overrides[category] = max(config.min, min(config.max, timeout))
    
    def get_config(self, category: TimeoutCategory) -> TimeoutConfig:
        """获取超时配置"""
        return TIMEOUT_CONFIGS.get(category)
    
    def all_configs(self) -> Dict[TimeoutCategory, TimeoutConfig]:
        """获取所有超时配置"""
        return TIMEOUT_CONFIGS.copy()


# 全局实例
timeout_manager = TimeoutManager()


# 便捷函数
def get_timeout(category: TimeoutCategory, custom: Optional[int] = None) -> int:
    """获取超时时间"""
    return timeout_manager.get_timeout(category, custom)


async def with_timeout(coro, category: TimeoutCategory, custom_timeout: Optional[int] = None):
    """带超时的协程执行"""
    import asyncio
    timeout = get_timeout(category, custom_timeout)
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        # 超时时应返回 None 或抛出更明确的异常
        # 此处记录日志后返回 None，由调用方处理
        import logging
        logging.getLogger(__name__).warning(
            f"操作超时 (category={category.value}, timeout={timeout}s)"
        )
        return None
