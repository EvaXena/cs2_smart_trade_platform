# -*- coding: utf-8 -*-
"""
CS2 智能交易平台 - 后端入口
"""
from contextlib import asynccontextmanager
import json
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import engine, Base
from app.core.encryption import encryption_manager
from app.core.logging_config import init_logging
from app.core.exceptions import register_error_handlers
from app.api.v1.router import api_router
from app.api.v1.endpoints.monitoring import metrics_middleware
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.audit import audit_middleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 初始化日志配置
    init_logging(log_file="logs/app.log")
    
    # 启动时初始化加密模块
    encryption_manager.initialize()
    
    # 启动时创建数据库表
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    # 关闭时清理资源
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

    # 注册路由
    app.include_router(api_router, prefix="/api/v1")

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
        return {"status": "healthy"}

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
