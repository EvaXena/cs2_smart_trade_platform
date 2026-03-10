# -*- coding: utf-8 -*-
"""
应用配置
"""
from functools import lru_cache
from typing import Optional
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """应用配置类"""

    # 应用基础配置
    APP_NAME: str = "CS2 Trade Platform"
    DEBUG: bool = True
    API_V1_PREFIX: str = "/api/v1"

    # 数据库配置
    DATABASE_URL: str = "sqlite+aiosqlite:///./cs2trade.db"

    # Redis 配置
    REDIS_URL: str = "redis://localhost:6379/0"

    # JWT 配置
    SECRET_KEY: str = "your-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24小时

    # Steam 配置
    STEAM_API_KEY: Optional[str] = None

    # BUFF 配置
    BUFF_BASE_URL: str = "https://buff.163.com"
    BUFF_API_INTERVAL: float = 1.0  # 最小请求间隔（秒）
    BUFF_MAX_RETRIES: int = 3

    # 交易配置
    MIN_PROFIT: float = 1.0  # 最小利润（元）
    MAX_SINGLE_TRADE: float = 10000  # 单笔最大交易金额
    AUTO_CONFIRM: bool = True

    # 监控配置
    PRICE_UPDATE_INTERVAL_HIGH: int = 5    # 热门饰品 5秒
    PRICE_UPDATE_INTERVAL_MEDIUM: int = 30  # 一般饰品 30秒
    PRICE_UPDATE_INTERVAL_LOW: int = 300    # 冷门饰品 5分钟

    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    """获取配置单例"""
    return Settings()


settings = get_settings()
