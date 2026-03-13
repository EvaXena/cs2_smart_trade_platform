# -*- coding: utf-8 -*-
"""
API 版本路由器
支持 v1 和 v2 版本的 API
"""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from typing import Dict, Callable
import logging

logger = logging.getLogger(__name__)

# 创建版本路由器
v1_router = APIRouter(prefix="/v1")
v2_router = APIRouter(prefix="/v2")

# 主API路由器
api_router = APIRouter(prefix="/api")


def register_version_routers():
    """
    注册版本路由器
    将 v1 和 v2 路由器添加到主路由器
    """
    # 导入各版本路由
    from app.api.v1.router import router as v1_routes
    from app.api.v2 import router as v2_routes
    
    # 注册 v1 路由
    for route in v1_routes.routes:
        v1_router.routes.append(route)
    
    # 注册 v2 路由
    for route in v2_routes.routes:
        v2_router.routes.append(route)
    
    # 添加版本路由器到主路由器
    api_router.include_router(v1_router)
    api_router.include_router(v2_router)
    
    return api_router


# 预定义的版本信息
API_VERSIONS = {
    "v1": {
        "version": "1.0.0",
        "status": "deprecated",  # 状态: stable, beta, deprecated
        "deprecation_date": "2024-06-01",
        "sunset_date": "2024-12-31",  # 停用日期
        "description": "第一版 API - 基础功能",
        "migration_guide": "请迁移到 v2 API，使用 /api/v2 端点",
        "endpoints": {
            "auth": "/api/v1/auth",
            "items": "/api/v1/items",
            "orders": "/api/v1/orders",
            "inventory": "/api/v1/inventory",
            "market": "/api/v1/market",
            "bots": "/api/v1/bots",
            "monitors": "/api/v1/monitors",
            "stats": "/api/v1/stats",
            "monitoring": "/api/v1/monitoring",
        }
    },
    "v2": {
        "version": "2.0.0",
        "status": "stable",
        "description": "第二版 API - 增强功能和性能优化",
        "new_features": [
            "批量操作优化",
            "WebSocket 实时推送",
            "高级过滤和排序",
            "增强的统计分析"
        ],
        "endpoints": {
            "auth": "/api/v2/auth",
            "items": "/api/v2/items",
            "orders": "/api/v2/orders",
            "inventory": "/api/v2/inventory",
            "market": "/api/v2/market",
            "bots": "/api/v2/bots",
            "monitors": "/api/v2/monitors",
            "stats": "/api/v2/stats",
            "websocket": "/api/v2/ws",
        }
    }
}

# 默认版本（用于未指定版本的请求）
DEFAULT_API_VERSION = "v2"


def create_api_router():
    """
    创建带有版本管理的主 API 路由器
    支持版本废弃警告和自动重定向
    """
    from datetime import datetime
    
    router = APIRouter(prefix="/api")
    
    # 导入并注册 v1 路由（添加废弃警告）
    from app.api.v1 import router as v1_routes
    v1_router = APIRouter(prefix="/v1")
    v1_router.include_router(v1_routes)
    router.include_router(v1_router, tags=["v1"])
    
    # 导入并注册 v2 路由
    try:
        from app.api.v2 import router as v2_routes
        v2_router = APIRouter(prefix="/v2")
        v2_router.include_router(v2_routes)
        router.include_router(v2_router, tags=["v2"])
    except ImportError:
        logger.warning("V2 路由未实现")
    
    # 添加版本信息端点
    @router.get("/versions")
    async def get_api_versions():
        """获取所有 API 版本信息"""
        return {
            "versions": API_VERSIONS,
            "latest_stable": "v2",
            "latest_beta": None,
            "default_version": DEFAULT_API_VERSION
        }
    
    @router.get("/version/{version}")
    async def get_version_info(version: str):
        """获取特定版本信息"""
        if version not in API_VERSIONS:
            return JSONResponse(
                status_code=404,
                content={"error": f"版本 {version} 不存在"}
            )
        return API_VERSIONS[version]
    
    # 添加 v1 废弃警告端点
    @router.get("/v1/deprecation-notice")
    async def get_v1_deprecation_notice():
        """获取 v1 废弃通知"""
        v1_info = API_VERSIONS.get("v1", {})
        return {
            "deprecated": v1_info.get("status") == "deprecated",
            "sunset_date": v1_info.get("sunset_date"),
            "migration_guide": v1_info.get("migration_guide"),
            "successor_version": "v2"
        }
    
    # 注册所有资源获取函数（权限检查器需要）
    from app.core.permissions_registry import register_all_resource_getters
    register_all_resource_getters()
    
    return router
