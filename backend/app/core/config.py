# -*- coding: utf-8 -*-
"""
应用配置
"""
import os
from functools import lru_cache
from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import Field, ConfigDict


class Settings(BaseSettings):
    """应用配置类"""

    # 应用基础配置
    APP_NAME: str = "CS2 Trade Platform"
    DEBUG: bool = Field(default=False, description="调试模式，生产环境必须设为 False")
    API_V1_PREFIX: str = "/api/v1"

    # 数据库配置
    DATABASE_URL: str = "sqlite+aiosqlite:///./cs2trade.db"

    # Redis 配置
    REDIS_URL: str = "redis://localhost:6379/0"

    # CORS 配置
    ALLOWED_ORIGINS: str = "http://localhost:5173,http://localhost:3000"
    
    # JWT 配置 - 必须从环境变量读取
    SECRET_KEY: str = Field(default="", description="JWT 密钥，必须在环境变量中设置")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24小时

    # 加密密钥 - 用于敏感信息加密
    ENCRYPTION_KEY: str = Field(default="", description="加密密钥，必须在环境变量中设置")

    # Steam 配置
    STEAM_API_KEY: Optional[str] = None
    STEAM_LOGIN: Optional[str] = Field(default=None, description="Steam 登录用户名")
    STEAM_SESSION_TOKEN: Optional[str] = Field(default=None, description="Steam 会话令牌")
    STEAM_WEBCOOKIE: Optional[str] = Field(default=None, description="Steam Web Cookie")

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

    # 登录限制配置
    LOGIN_MAX_ATTEMPTS: int = 5  # 最大登录尝试次数
    LOGIN_LOCKOUT_MINUTES: int = 15  # 锁定时间（分钟）

    # Rate Limiting 配置
    RATE_LIMIT_ENABLED: bool = Field(default=True)  # 是否启用限流
    RATE_LIMIT_DEFAULT_REQUESTS: int = 60  # 默认每分钟请求数
    RATE_LIMIT_DEFAULT_WINDOW: int = 60  # 默认窗口（秒）
    RATE_LIMIT_DEFAULT_BURST: int = 10  # 默认突发限制
    TESTING: bool = Field(default=False)  # 测试模式标志
    
    # 限流端点配置（JSON格式字符串）
    RATE_LIMIT_ENDPOINTS: str = """{
        "/api/v1/auth/login": {"requests": 5, "window": 60, "burst": 3},
        "/api/v1/auth/register": {"requests": 3, "window": 300, "burst": 1},
        "/api/v1/orders": {"requests": 120, "window": 60, "burst": 20},
        "/api/v1/monitoring": {"requests": 300, "window": 60, "burst": 50},
        "/api/v1/bots": {"requests": 100, "window": 60, "burst": 15}
    }"""

    model_config = ConfigDict(env_file=".env", case_sensitive=True, extra="allow")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # 验证必需的配置
        if not self.DEBUG and not self.SECRET_KEY:
            raise ValueError("生产环境必须设置 SECRET_KEY 环境变量")
        if not self.ENCRYPTION_KEY:
            import warnings
            warnings.warn("未设置 ENCRYPTION_KEY，敏感数据将使用临时密钥加密")


@lru_cache()
def get_settings() -> Settings:
    """获取配置单例"""
    return Settings()


settings = get_settings()
