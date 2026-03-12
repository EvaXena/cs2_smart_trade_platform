# -*- coding: utf-8 -*-
"""
饰品端点
"""
from typing import Optional, List
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, and_, func

from app.core.database import get_db
from app.core.security import get_current_user
from app.core.exceptions import NotFoundError
from app.core.config import settings
from app.models.user import User
from app.models.item import Item, PriceHistory
from app.schemas.item import (
    ItemResponse,
    ItemListResponse,
    ItemSearchRequest,
    PriceHistoryResponse,
    PriceHistoryListResponse,
)
from app.utils.validators import validate_item_id, validate_price, validate_limit

router = APIRouter()


@router.get("", response_model=ItemListResponse)
async def get_items(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category: Optional[str] = None,
    rarity: Optional[str] = None,
    exterior: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    sort_by: str = "current_price",
    sort_order: str = "asc",
    db: AsyncSession = Depends(get_db),
):
    """获取饰品列表"""
    # 构建基础查询条件
    conditions = []
    if category:
        conditions.append(Item.category == category)
    if rarity:
        conditions.append(Item.rarity == rarity)
    if exterior:
        conditions.append(Item.exterior == exterior)
    if min_price is not None:
        conditions.append(Item.current_price >= min_price)
    if max_price is not None:
        conditions.append(Item.current_price <= max_price)
    
    # 使用 func.count() 获取总数
    count_query = select(func.count()).select_from(Item)
    if conditions:
        count_query = count_query.where(and_(*conditions))
    
    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0
    
    # 构建分页查询
    query = select(Item)
    if conditions:
        query = query.where(and_(*conditions))
    
    # 排序
    if sort_by == "current_price":
        order_col = Item.current_price
    elif sort_by == "volume_24h":
        order_col = Item.volume_24h
    elif sort_by == "price_change_percent":
        order_col = Item.price_change_percent
    else:
        order_col = Item.id
    
    if sort_order == "desc":
        query = query.order_by(order_col.desc())
    else:
        query = query.order_by(order_col.asc())
    
    # 分页
    offset = (page - 1) * page_size
    query = query.offset(offset).limit(page_size)
    
    # 执行查询
    result = await db.execute(query)
    items = result.scalars().all()
    
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/search")
async def search_items(
    keyword: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """搜索饰品"""
    # 使用验证器验证参数
    validated_limit = validate_limit(limit)
    
    # 转义特殊字符防止 LIKE 注入
    escaped_keyword = keyword.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    search_pattern = f"%{escaped_keyword}%"
    
    # 使用 case_sensitive=False 的 ilike 查询
    # SQLAlchemy 会自动处理参数化查询，防止 SQL 注入
    count_query = select(func.count()).select_from(Item).where(
        or_(
            Item.name.ilike(search_pattern, escape='\\'),
            Item.name_cn.ilike(search_pattern, escape='\\'),
            Item.market_hash_name.ilike(search_pattern, escape='\\')
        )
    )
    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0
    
    query = select(Item).where(
        or_(
            Item.name.ilike(search_pattern, escape='\\'),
            Item.name_cn.ilike(search_pattern, escape='\\'),
            Item.market_hash_name.ilike(search_pattern, escape='\\')
        )
    ).limit(validated_limit)
    
    result = await db.execute(query)
    items = result.scalars().all()
    
    return {"items": items, "total": total}


@router.get("/{item_id}", response_model=ItemResponse)
async def get_item(
    item_id: int,
    db: AsyncSession = Depends(get_db),
):
    """获取饰品详情"""
    # 使用验证器验证item_id
    validated_item_id = validate_item_id(item_id)
    
    result = await db.execute(
        select(Item).where(Item.id == validated_item_id)
    )
    item = result.scalar_one_or_none()
    
    if not item:
        raise NotFoundError("饰品", validated_item_id)
    
    return item


@router.get("/{item_id}/price", response_model=PriceHistoryListResponse)
async def get_price_history(
    item_id: int,
    source: Optional[str] = Query(None, pattern="^(buff|steam)$"),
    days: int = Query(7, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
):
    """获取价格历史"""
    from datetime import datetime, timedelta
    
    # 使用验证器验证item_id
    validated_item_id = validate_item_id(item_id)
    
    # 验证饰品存在
    result = await db.execute(
        select(Item).where(Item.id == validated_item_id)
    )
    item = result.scalar_one_or_none()
    if not item:
        raise NotFoundError("饰品", validated_item_id)
    
    # 查询价格历史
    query = select(PriceHistory).where(
        PriceHistory.item_id == item_id,
        PriceHistory.recorded_at >= datetime.utcnow() - timedelta(days=days)
    )
    
    if source:
        query = query.where(PriceHistory.source == source)
    
    query = query.order_by(PriceHistory.recorded_at.desc())
    
    result = await db.execute(query)
    price_history = result.scalars().all()
    
    return {
        "data": price_history,
        "item_id": item_id,
        "source": source or "all"
    }


@router.get("/{item_id}/overview")
async def get_price_overview(
    item_id: int,
    db: AsyncSession = Depends(get_db),
):
    """获取价格概览 (BUFF vs Steam)"""
    # 使用验证器验证item_id
    validated_item_id = validate_item_id(item_id)
    
    result = await db.execute(
        select(Item).where(Item.id == validated_item_id)
    )
    item = result.scalar_one_or_none()
    
    if not item:
        raise NotFoundError("饰品", validated_item_id)
    
    # 计算搬砖利润
    arbitrage_profit = None
    arbitrage_percent = None
    
    if item.current_price and item.steam_lowest_price:
        # Steam 出售需要扣除手续费
        steam_sell_price = item.steam_lowest_price * settings.STEAM_FEE_RATE
        arbitrage_profit = steam_sell_price - item.current_price
        if item.current_price > 0:
            arbitrage_percent = (arbitrage_profit / item.current_price) * 100
    
    # 价格趋势
    price_trend = "stable"
    if item.price_change_percent > 1:
        price_trend = "up"
    elif item.price_change_percent < -1:
        price_trend = "down"
    
    return {
        "item_id": item.id,
        "market_hash_name": item.market_hash_name,
        "buff_price": item.current_price,
        "steam_price": item.steam_lowest_price,
        "arbitrage_profit": arbitrage_profit,
        "arbitrage_percent": arbitrage_percent,
        "volume_24h": item.volume_24h,
        "price_trend": price_trend,
    }
