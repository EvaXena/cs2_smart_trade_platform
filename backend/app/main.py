# -*- coding: utf-8 -*-
"""
CS2 智能交易平台 - 后端入口
"""
from contextlib import asynccontextmanager
import json
from typing import Optional
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from app.core.config import settings
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

# 全局 SteamAPI 实例
_steam_api: Optional[SteamAPI] = None


def get_steam_api() -> SteamAPI:
    """获取全局 SteamAPI 实例"""
    global _steam_api
    if _steam_api is None:
        _steam_api = SteamAPI()
    return _steam_api


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    global _steam_api
    
    # 初始化日志配置
    init_logging(log_file="logs/app.log")
    
    # 启动时初始化加密模块
    encryption_manager.initialize()
    
    # 启动时初始化缓存服务
    try:
        cache = get_cache()
        await cache.initialize()
        logger.info("Cache service initialized")
    except Exception as e:
        logger.warning(f"Failed to initialize cache service: {e}")
    
    # 启动时创建数据库表
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # 启动时初始化 SteamAPI（延迟创建 session）
    _steam_api = SteamAPI()
    logger.info("SteamAPI initialized")
    
    yield
    
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
        rate_limit_config = json.loads(settings.RATE_LIMIT_ENDPOINTS)
        app.add_middleware(RateLimitMiddleware, config=rate_limit_config)

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
        """健康检查端点"""
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
        """就绪检查 - 检查所有依赖服务"""
        checks = {}
        
        # 检查数据库
        try:
            from app.core.database import engine
            async with engine.connect() as conn:
                await conn.execute("SELECT 1")
            checks["database"] = "healthy"
        except Exception as e:
            checks["database"] = f"unhealthy: {str(e)}"
        
        # 检查 Redis
        try:
            from app.core.redis_manager import get_redis
            redis_client = await get_redis()
            await redis_client.ping()
            checks["redis"] = "healthy"
        except Exception as e:
            checks["redis"] = f"unhealthy: {str(e)}"
        
        # 检查 Steam API
        try:
            steam_api = get_steam_api()
            if await steam_api.health_check():
                checks["steam_api"] = "healthy"
            else:
                checks["steam_api"] = "degraded"
        except Exception as e:
            checks["steam_api"] = f"unhealthy: {str(e)}"
        
        # 判断整体状态
        all_healthy = all(v == "healthy" for v in checks.values())
        
        return {
            "status": "ready" if all_healthy else "not_ready",
            "checks": checks
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
