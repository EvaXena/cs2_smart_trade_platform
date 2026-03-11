# -*- coding: utf-8 -*-
"""
API v2 路由器
"""
from fastapi import APIRouter

router = APIRouter()

# v2 端点将在后续迭代中添加
# 示例:
# from app.api.v2.endpoints import orders, items, market
# router.include_router(orders.router, prefix="/orders", tags=["订单"])
# router.include_router(items.router, prefix="/items", tags=["饰品"])
# router.include_router(market.router, prefix="/market", tags=["市场"])


@router.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "ok", "version": "v2"}


@router.get("/info")
async def get_version_info():
    """获取 API v2 版本信息"""
    return {
        "version": "v2",
        "description": "CS2 交易平台 API v2 (Beta)",
        "features": [
            "改进的订单处理",
            "增强的市场分析",
            "性能优化",
        ],
    }
