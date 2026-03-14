# -*- coding: utf-8 -*-
"""
CS2 智能交易平台 - 后端入口
"""
import asyncio
from contextlib import asynccontextmanager
import json
import threading
from typing import Optional
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from functools import wraps

from app.core.config import settings, check_config_reload, subscribe_config_change
from app.core.database import engine, Base
from app.core.encryption import encryption_manager
from app.core.logging_config import init_logging
from app.core.exceptions import register_error_handlers
from app.api.router import create_api_router
from app.api.v1.endpoints.monitoring import metrics_middleware
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.middleware.rate_limit import RateLimitMiddleware, ConnectionLimitMiddleware
from app.middleware.audit import audit_middleware
from app.services.steam_service import SteamAPI
from app.services.cache import get_cache
import logging

logger = logging.getLogger(__name__)

# 全局 SteamAPI 实例（线程安全）
_steam_api: Optional[SteamAPI] = None
_steam_api_lock = threading.Lock()

# 全局配置热重载任务
_config_reload_task: Optional[asyncio.Task] = None

# 缓存降级状态
_cache_degraded = False


def get_steam_api() -> SteamAPI:
    """获取全局 SteamAPI 实例（线程安全懒加载）"""
    global _steam_api
    if _steam_api is None:
        with _steam_api_lock:
            if _steam_api is None:
                _steam_api = SteamAPI()
    return _steam_api


def cache_fallback(func):
    """缓存降级装饰器：当缓存不可用时优雅降级"""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        global _cache_degraded
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            # 记录错误但不让服务崩溃
            logger.error(f"Cache operation failed: {e}")
            _cache_degraded = True
            # 返回 None 让调用方使用默认值
            return None
    return wrapper


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    global _steam_api, _cache_degraded, _config_reload_task
    
    # 初始化日志配置
    init_logging(log_file="logs/app.log")
    
    # 启动时初始化加密模块
    encryption_manager.initialize()
    
    # 启动时初始化缓存服务（带完整降级）
    try:
        from app.services.cache import ensure_cache_initialized
        cache = await ensure_cache_initialized()
        logger.info("Cache service initialized")
        
        # 启动时预热缓存
        try:
            await cache.warmup_cache()
            logger.info("Cache warmup completed")
        except Exception as e:
            logger.warning(f"Cache warmup failed: {e}")
            # 缓存预热失败不影响服务启动
    except Exception as e:
        logger.warning(f"Failed to initialize cache service: {e}")
        _cache_degraded = True
        logger.warning("Cache service degraded - using fallback mode")
    
    # 启动时创建数据库表
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # 启动时初始化 SteamAPI（延迟创建 session）
    _steam_api = SteamAPI()
    logger.info("SteamAPI initialized")
    
    # 启动配置热重载后台任务
    async def config_reload_loop():
        """配置热重载循环"""
        while True:
            try:
                await asyncio.sleep(settings.CONFIG_RELOAD_INTERVAL)
                if check_config_reload():
                    logger.info("配置已自动热重载")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"配置热重载检查异常: {e}")
    
    _config_reload_task = asyncio.create_task(config_reload_loop())
    logger.info(f"配置热重载任务已启动 (间隔: {settings.CONFIG_RELOAD_INTERVAL}秒)")
    
    yield
    
    # 关闭时取消配置热重载任务
    if _config_reload_task:
        _config_reload_task.cancel()
        try:
            await _config_reload_task
        except asyncio.CancelledError:
            pass
    
    # 关闭时清理 SteamAPI 资源
    if _steam_api:
        await _steam_api.cleanup()
        _steam_api = None
        logger.info("SteamAPI cleaned up")
    
    # 关闭时清理数据库连接
    await engine.dispose()


def create_app() -> FastAPI:
    """创建 FastAPI 应用"""
    app = FastAPI(
        title="CS2 Trade Platform API",
        description="CS2 饰品交易平台 API",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # CORS 配置
    allowed_origins = settings.ALLOWED_ORIGINS.split(",") if settings.ALLOWED_ORIGINS else ["http://localhost:5173"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 安全头部中间件
    app.add_middleware(SecurityHeadersMiddleware)

    # Rate Limiting 中间件 (测试环境禁用 - 基于DEBUG标志)
    if settings.RATE_LIMIT_ENABLED and not settings.TESTING:
        # RATE_LIMIT_ENDPOINTS 现在是字典类型，无需 json.loads
        app.add_middleware(RateLimitMiddleware, config=settings.RATE_LIMIT_ENDPOINTS)

    # 并发连接数限制中间件
    if not settings.TESTING:
        app.add_middleware(ConnectionLimitMiddleware, max_connections=100)

    # 注册路由
    api_router = create_api_router()
    app.include_router(api_router)

    # 添加指标收集中间件
    app.middleware("http")(metrics_middleware)

    # 添加审计日志中间件
    app.middleware("http")(audit_middleware)
    
    # 注册错误处理器
    register_error_handlers(app)

    @app.get("/")
    async def root():
        return {"message": "CS2 Trade Platform API", "version": "1.0.0"}

    @app.get("/health")
    async def health_check():
        """健康检查端点（带超时控制）"""
        import platform
        import sys
        
        # 获取依赖版本
        try:
            import sqlalchemy
            import redis
            import aiohttp
            db_version = sqlalchemy.__version__
            redis_version = redis.__version__
            aiohttp_version = aiohttp.__version__
        except ImportError:
            db_version = redis_version = aiohttp_version = "unknown"
        
        return {
            "status": "healthy",
            "system": {
                "platform": platform.platform(),
                "python_version": sys.version,
            },
            "dependencies": {
                "sqlalchemy": db_version,
                "redis": redis_version,
                "aiohttp": aiohttp_version,
            }
        }

    @app.get("/health/ready")
    async def readiness_check():
        """就绪检查 - 检查所有依赖服务（带超时控制）"""
        global _cache_degraded
        checks = {}
        
        # 健康检查超时配置
        HEALTH_CHECK_TIMEOUT = 5  # 秒
        
        # 检查数据库（使用参数化查询防止SQL注入，带超时控制）
        try:
            from app.core.database import engine
            from sqlalchemy import text
            async with engine.connect() as conn:
                await asyncio.wait_for(
                    conn.execute(text("SELECT 1")),
                    timeout=HEALTH_CHECK_TIMEOUT
                )
            checks["database"] = "healthy"
        except asyncio.TimeoutError:
            checks["database"] = "unhealthy: timeout"
        except Exception as e:
            checks["database"] = f"unhealthy: {str(e)}"
        
        # 检查 Redis/缓存（带超时控制）
        try:
            from app.core.redis_manager import get_redis
            redis_client = await get_redis()
            await asyncio.wait_for(
                redis_client.ping(),
                timeout=HEALTH_CHECK_TIMEOUT
            )
            checks["cache"] = "healthy"
        except asyncio.TimeoutError:
            # 缓存降级不影响整体可用性
            if _cache_degraded:
                checks["cache"] = "degraded: timeout"
            else:
                checks["cache"] = "unhealthy: timeout"
        except Exception as e:
            # 缓存降级不影响整体可用性
            if _cache_degraded:
                checks["cache"] = f"degraded: {str(e)}"
            else:
                checks["cache"] = f"unhealthy: {str(e)}"
        
        # 检查 Steam API（带超时控制）
        try:
            steam_api = get_steam_api()
            result = await asyncio.wait_for(
                steam_api.health_check(),
                timeout=HEALTH_CHECK_TIMEOUT
            )
            if result:
                checks["steam_api"] = "healthy"
            else:
                checks["steam_api"] = "degraded"
        except asyncio.TimeoutError:
            checks["steam_api"] = "unhealthy: timeout"
        except Exception as e:
            checks["steam_api"] = f"unhealthy: {str(e)}"
        
        # 判断整体状态（缓存降级不影响就绪状态）
        critical_checks = ["database", "steam_api"]
        all_critical_healthy = all(
            checks.get(k, "").startswith("healthy") 
            for k in critical_checks
        )
        
        return {
            "status": "ready" if all_critical_healthy else "not_ready",
            "checks": checks,
            "cache_degraded": _cache_degraded
        }

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
