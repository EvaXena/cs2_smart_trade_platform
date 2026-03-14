# -*- coding: utf-8 -*-
"""
应用配置
"""
import os
import json
import logging
import threading
from functools import lru_cache
from typing import Optional, Dict, Callable, List
from pathlib import Path

from pydantic_settings import BaseSettings
from pydantic import Field, ConfigDict


logger = logging.getLogger(__name__)


class ConfigReloader:
    """配置热重载管理器（线程安全版本）"""
    
    def __init__(self, config_file: str = ".env"):
        self._config_file = config_file
        self._subscribers: List[Callable[[], None]] = []
        self._last_mtime: float = 0
        self._settings_instance: Optional['Settings'] = None
        # 线程锁，确保并发安全
        self._lock = threading.RLock()
    
    def watch(self, settings_instance: 'Settings'):
        """开始监听配置变化"""
        self._settings_instance = settings_instance
        config_path = Path(self._config_file)
        if config_path.exists():
            self._last_mtime = config_path.stat().st_mtime
    
    def check_and_reload(self) -> bool:
        """检查并重载配置（需手动调用或配合定时任务，线程安全）"""
        with self._lock:
            config_path = Path(self._config_file)
            if not config_path.exists():
                return False
            
            current_mtime = config_path.stat().st_mtime
            if current_mtime > self._last_mtime:
                logger.info(f"检测到配置文件变化: {self._config_file}")
                self._last_mtime = current_mtime
                
                # 清除缓存
                get_settings.cache_clear()
                
                # 重新加载
                new_settings = get_settings()
                
                # 通知订阅者
                for callback in self._subscribers:
                    try:
                        callback()
                    except Exception as e:
                        logger.error(f"配置变更回调错误: {e}")
                
                logger.info("配置已热重载")
                return True
            
            return False
    
    def subscribe(self, callback: Callable[[], None]):
        """订阅配置变更（线程安全）"""
        with self._lock:
            self._subscribers.append(callback)


# 全局配置重载器
_config_reloader = ConfigReloader()


class Settings(BaseSettings):
    """应用配置类"""

    # 应用基础配置
    APP_NAME: str = "CS2 Trade Platform"
    DEBUG: bool = Field(default=False, description="调试模式，生产环境必须设为 False")
    ENVIRONMENT: str = Field(default="development", description="运行环境: development, staging, production")
    API_V1_PREFIX: str = "/api/v1"
    
    @property
    def is_production(self) -> bool:
        """判断是否为生产环境"""
        # 优先使用 ENVIRONMENT 变量（明确设置时）
        env = os.environ.get("ENVIRONMENT", "")
        if env:
            return env.lower() == "production"
        # 向后兼容：没有 ENVIRONMENT 时使用 DEBUG
        return not self.DEBUG

    # 数据库配置
    DATABASE_URL: str = "sqlite+aiosqlite:///./cs2trade.db"

    # Redis 配置
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_PASSWORD: Optional[str] = Field(default=None, description="Redis 密码（可选）")

    # CORS 配置
    ALLOWED_ORIGINS: str = "http://localhost:5173,http://localhost:3000"
    
    # JWT 配置 - 必须从环境变量读取
    SECRET_KEY: str = Field(default="", description="JWT 密钥，必须在环境变量中设置")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24小时
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 10080  # 7天

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
    MAX_SINGLE_ORDER: float = 10000  # 单笔订单最大金额
    MAX_DAILY_LIMIT: float = 50000  # 每日累计最大交易金额
    STEAM_FEE_RATE: float = 0.85  # Steam出售手续费率（15%手续费）
    AUTO_CONFIRM: bool = True

    # 监控配置
    PRICE_UPDATE_INTERVAL_HIGH: int = 5    # 热门饰品 5秒
    PRICE_UPDATE_INTERVAL_MEDIUM: int = 30  # 一般饰品 30秒
    PRICE_UPDATE_INTERVAL_LOW: int = 300    # 冷门饰品 5分钟

    # 订单确认配置
    ORDER_CONFIRM_CHECK_INTERVAL: int = 5   # 订单确认检查间隔（秒）
    ORDER_CONFIRM_TIMEOUT: int = 300        # 订单确认超时（秒）
    ORDER_POLL_RETRIES: int = 10            # 订单轮询最大次数

    # 登录限制配置
    LOGIN_MAX_ATTEMPTS: int = 5  # 最大登录尝试次数
    LOGIN_LOCKOUT_MINUTES: int = 15  # 锁定时间（分钟）

    # Rate Limiting 配置
    RATE_LIMIT_ENABLED: bool = Field(default=True)  # 是否启用限流
    RATE_LIMIT_DEFAULT_REQUESTS: int = 60  # 默认每分钟请求数
    RATE_LIMIT_DEFAULT_WINDOW: int = 60  # 默认窗口（秒）
    RATE_LIMIT_DEFAULT_BURST: int = 10  # 默认突发限制
    TESTING: bool = Field(default=False)  # 测试模式标志

    # WebSocket 配置
    WS_HEARTBEAT_INTERVAL: int = Field(default=30, description="WebSocket 心跳间隔（秒）")
    WS_HEARTBEAT_TIMEOUT: int = Field(default=10, description="WebSocket 心跳超时（秒）")
    WS_MAX_FAILURES: int = Field(default=3, description="WebSocket 最大失败次数")
    WS_RECONNECT_DELAY: int = Field(default=5, description="WebSocket 重连延迟（秒）")
    WS_TOKEN_EXPIRY_WARNING: int = Field(default=300, description="Token 过期警告时间（秒）")

    # Steam 配置
    STEAM_APP_ID: int = Field(default=730, description="Steam 应用ID (CS2=730)")
    STEAM_CONTEXT_ID: int = Field(default=2, description="Steam 市场上下文ID")

    # 数据库配置
    DB_BUSY_TIMEOUT: int = Field(default=30000, description="SQLite busy_timeout（毫秒）")
    DB_POOL_RECYCLE: int = Field(default=3600, description="数据库连接池回收时间（秒）")
    DB_POOL_TIMEOUT: int = Field(default=30, description="数据库连接池超时（秒）")
    # ===== P2-B4: 生产环境连接池大小限制 =====
    DB_POOL_SIZE: int = Field(default=5, description="数据库连接池大小（开发环境默认）")
    DB_MAX_OVERFLOW: int = Field(default=10, description="数据库最大溢出连接数")
    
    @property
    def db_pool_config(self) -> Dict:
        """获取数据库连接池配置（根据环境自动调整）"""
        base_config = {
            "pool_recycle": self.DB_POOL_RECYCLE,
            "pool_timeout": self.DB_POOL_TIMEOUT,
            "pool_pre_ping": True,
        }
        
        if self.is_production:
            # 生产环境使用更大的连接池
            return {
                **base_config,
                "pool_size": 20,  # 生产环境固定20
                "max_overflow": 30,  # 生产环境最大30
            }
        else:
            # 开发环境使用配置的值
            return {
                **base_config,
                "pool_size": self.DB_POOL_SIZE,
                "max_overflow": self.DB_MAX_OVERFLOW,
            }

    # 缓存配置
    CACHE_CLEANUP_INTERVAL: int = Field(default=300, description="缓存清理间隔（秒）")
    RESPONSE_TIME_TTL: int = Field(default=300, description="响应时间缓存 TTL（秒）")
    
    # 限流端点配置（字典格式，支持热重载）
    RATE_LIMIT_ENDPOINTS: Dict = Field(default_factory=lambda: {
        "/api/v1/auth/login": {"requests": 5, "window": 60, "burst": 3},
        "/api/v1/auth/register": {"requests": 3, "window": 300, "burst": 1},
        "/api/v1/orders": {"requests": 120, "window": 60, "burst": 20},
        "/api/v1/monitoring": {"requests": 300, "window": 60, "burst": 50},
        "/api/v1/bots": {"requests": 100, "window": 60, "burst": 15}
    })

    # 搬砖流程配置
    ARBITRAGE_SETTLE_WAIT: int = Field(default=10, description="搬砖买入后等待到账时间(秒)")
    
    # 价格监控配置
    PRICE_CHANGE_THRESHOLD: float = Field(default=0.01, description="价格变化阈值(元)，低于此值不记录历史")
    
    # 配置热重载
    CONFIG_RELOAD_INTERVAL: int = Field(default=30, description="配置检查间隔(秒)")

    model_config = ConfigDict(env_file=".env", case_sensitive=True, extra="allow")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # ===== P1-S1: 强制校验密钥 - 启动时必须设置 =====
        # 所有环境都必须设置 SECRET_KEY
        if not self.SECRET_KEY:
            raise ValueError(
                "SECRET_KEY 环境变量未设置，拒绝启动。"
                "请设置 SECRET_KEY 环境变量后再启动应用。"
            )
        
        # 生产环境必须验证密钥长度
        if self.is_production:
            if len(self.SECRET_KEY) < 32:
                raise ValueError(
                    f"生产环境 SECRET_KEY 长度必须至少为32字符，当前长度: {len(self.SECRET_KEY)}"
                )
            # 生产环境强制要求 ENCRYPTION_KEY
            if not self.ENCRYPTION_KEY:
                raise ValueError(
                    "生产环境必须设置 ENCRYPTION_KEY 环境变量，拒绝启动。"
                    "请设置 ENCRYPTION_KEY 环境变量后再启动应用。"
                )
            if len(self.ENCRYPTION_KEY) < 32:
                raise ValueError(
                    f"生产环境 ENCRYPTION_KEY 长度必须至少为32字符，当前长度: {len(self.ENCRYPTION_KEY)}"
                )
        else:
            # 开发环境警告但允许启动
            if len(self.SECRET_KEY) < 16:
                import warnings
                warnings.warn(
                    f"SECRET_KEY 长度过短（{len(self.SECRET_KEY)}字符），建议至少32字符用于安全"
                )
            
            if not self.ENCRYPTION_KEY:
                import warnings
                warnings.warn(
                    "未设置 ENCRYPTION_KEY，敏感数据将使用临时密钥加密（仅限开发环境）"
                )
        # ===== 密钥校验结束 =====
    
    def get_rate_limit_config(self, endpoint: str) -> Dict:
        """获取特定端点的限流配置"""
        return self.RATE_LIMIT_ENDPOINTS.get(endpoint, {
            "requests": self.RATE_LIMIT_DEFAULT_REQUESTS,
            "window": self.RATE_LIMIT_DEFAULT_WINDOW,
            "burst": self.RATE_LIMIT_DEFAULT_BURST
        })


@lru_cache()
def get_settings() -> Settings:
    """获取配置单例"""
    settings_obj = Settings()
    # 初始化配置热重载
    _config_reloader.watch(settings_obj)
    return settings_obj


def reload_settings() -> Settings:
    """强制重载配置"""
    get_settings.cache_clear()
    return get_settings()


def subscribe_config_change(callback: Callable[[], None]):
    """订阅配置变更"""
    _config_reloader.subscribe(callback)


def check_config_reload() -> bool:
    """检查并重载配置（可由定时任务调用）"""
    return _config_reloader.check_and_reload()


settings = get_settings()
