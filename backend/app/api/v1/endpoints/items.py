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
from app.validators.batch_validator import BatchValidator
from app.schemas.batch import ItemBatchGetRequest, ItemBatchGetResponse

router = APIRouter()

# 创建批量验证器（使用 ItemBatchGetRequest 模型）
_item_batch_validator = BatchValidator(ItemBatchGetRequest, max_size=100)


@router.get("", response_model=ItemListResponse)
async def get_items(
    page: int = Query(1, ge=1, description="页码，从1开始"),
    page_size: int = Query(20, ge=1, le=100, description="每页返回数量，最大100"),
    category: Optional[str] = Query(None, description="饰品分类筛选，如 'weapon', 'container', 'agent'"),
    rarity: Optional[str] = Query(None, description="稀有度筛选，如 'covert', 'classified', 'restricted'"),
    exterior: Optional[str] = Query(None, description="外观筛选，如 'Factory New', 'Minimal Wear'"),
    min_price: Optional[float] = Query(None, ge=0, description="最低价格筛选"),
    max_price: Optional[float] = Query(None, ge=0, description="最高价格筛选"),
    sort_by: str = Query("current_price", description="排序字段: current_price, volume_24h, price_change_percent"),
    sort_order: str = Query("asc", description="排序方向: asc, desc"),
    db: AsyncSession = Depends(get_db),
) -> ItemListResponse:
    """
    获取饰品列表
    
    支持分页、筛选、排序的饰品查询接口。返回所有在售饰品的分页列表。
    
    ## 参数说明
    
    | 参数 | 类型 | 必填 | 说明 |
    |------|------|------|------|
    | page | int | 否 | 页码，从1开始，默认1 |
    | page_size | int | 否 | 每页数量，1-100，默认20 |
    | category | str | 否 | 饰品分类 |
    | rarity | str | 否 | 稀有度 |
    | exterior | str | 否 | 外观条件 |
    | min_price | float | 否 | 最低价格 |
    | max_price | float | 否 | 最高价格 |
    | sort_by | str | 否 | 排序字段，默认 current_price |
    | sort_order | str | 否 | 排序方向，默认 asc |
    
    ## 返回格式
    
    ```json
    {
        "items": [...],
        "total": 1000,
        "page": 1,
        "page_size": 20
    }
    ```
    
    ## 错误码
    
    - 400: 参数验证失败
    
    ## 示例
    
    ```bash
    # 获取前20个热门饰品
    curl "http://localhost:8000/api/v1/items?sort_by=volume_24h&sort_order=desc"
    
    # 获取价格低于100元的武器
    curl "http://localhost:8000/api/v1/items?category=weapon&max_price=100"
    ```
    """
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
    keyword: str = Query(..., min_length=1, description="搜索关键词"),
    limit: int = Query(20, ge=1, le=100, description="返回结果数量限制"),
    db: AsyncSession = Depends(get_db),
) -> ItemListResponse:
    """
    搜索饰品
    
    根据关键词搜索饰品名称、中文名称或市场哈希名。
    
    ## 参数说明
    
    | 参数 | 类型 | 必填 | 说明 |
    |------|------|------|------|
    | keyword | str | 是 | 搜索关键词，最少1个字符 |
    | limit | int | 否 | 返回数量，1-100，默认20 |
    
    ## 返回格式
    
    ```json
    {
        "items": [
            {
                "id": 1,
                "name": "AK-47 | 红线 (久经沙场)",
                ...
            }
        ],
        "total": 10
    }
    ```
    
    ## 示例
    
    ```bash
    # 搜索含有关键词 "AK-47" 的饰品
    curl "http://localhost:8000/api/v1/items/search?keyword=AK-47"
    ```
    """
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
    
    # Convert SQLAlchemy models to ItemResponse for proper serialization
    return {
        "items": [ItemResponse.model_validate(item) for item in items],
        "total": total
    }


@router.get("/{item_id}", response_model=ItemResponse)
async def get_item(
    item_id: int,
    db: AsyncSession = Depends(get_db),
) -> ItemResponse:
    """
    获取饰品详情
    
    根据物品ID获取饰品的详细信息。
    
    ## 参数说明
    
    | 参数 | 类型 | 必填 | 说明 |
    |------|------|------|------|
    | item_id | int | 是 | 饰品ID |
    
    ## 返回格式
    
    返回 ItemResponse 格式的饰品详情，包括：
    - id: 饰品ID
    - name: 饰品名称
    - current_price: 当前售价
    - steam_lowest_price: Steam 最低售价
    - volume_24h: 24小时成交量
    - 等其他字段
    
    ## 错误码
    
    - 404: 饰品不存在
    
    ## 示例
    
    ```bash
    # 获取ID为1的饰品详情
    curl "http://localhost:8000/api/v1/items/1"
    ```
    """
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
    source: Optional[str] = Query(None, pattern="^(buff|steam)$", description="价格来源: buff 或 steam"),
    days: int = Query(7, ge=1, le=90, description="查询天数，1-90，默认7"),
    db: AsyncSession = Depends(get_db),
) -> PriceHistoryListResponse:
    """
    获取价格历史
    
    获取指定饰品的历史价格记录，用于分析价格趋势。
    
    ## 参数说明
    
    | 参数 | 类型 | 必填 | 说明 |
    |------|------|------|------|
    | item_id | int | 是 | 饰品ID |
    | source | str | 否 | 价格来源，buff 或 steam，默认全部 |
    | days | int | 否 | 查询天数，默认7天 |
    
    ## 返回格式
    
    ```json
    {
        "data": [
            {
                "id": 1,
                "item_id": 100,
                "price": 150.00,
                "source": "buff",
                "recorded_at": "2024-01-01T00:00:00"
            }
        ],
        "item_id": 100,
        "source": "all"
    }
    ```
    
    ## 错误码
    
    - 404: 饰品不存在
    
    ## 示例
    
    ```bash
    # 获取最近30天的BUFF价格历史
    curl "http://localhost:8000/api/v1/items/100/price?source=buff&days=30"
    ```
    """
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
) -> dict:
    """
    获取价格概览 (BUFF vs Steam)
    
    获取指定饰品的 BUFF 价格和 Steam 价格对比，以及搬砖利润分析。
    
    ## 参数说明
    
    | 参数 | 类型 | 必填 | 说明 |
    |------|------|------|------|
    | item_id | int | 是 | 饰品ID |
    
    ## 返回格式
    
    ```json
    {
        "item_id": 100,
        "market_hash_name": "AK-47 | 红线 (久经沙场)",
        "buff_price": 150.00,
        "steam_price": 180.00,
        "arbitrage_profit": 20.00,
        "arbitrage_percent": 13.33,
        "volume_24h": 500,
        "price_trend": "up"
    }
    ```
    
    ## 返回字段说明
    
    | 字段 | 类型 | 说明 |
    |------|------|------|
    | buff_price | float | BUFF 售价 |
    | steam_price | float | Steam 最低售价 |
    | arbitrage_profit | float | 搬砖利润（Steam收入-BUFF成本） |
    | arbitrage_percent | float | 利润率百分比 |
    | volume_24h | int | 24小时成交量 |
    | price_trend | str | 价格趋势: up(上涨), down(下跌), stable(稳定) |
    
    ## 错误码
    
    - 404: 饰品不存在
    
    ## 示例
    
    ```bash
    # 获取饰品价格概览
    curl "http://localhost:8000/api/v1/items/100/overview"
    ```
    """
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


@router.post("/batch", response_model=ItemBatchGetResponse)
async def get_items_batch(
    request: ItemBatchGetRequest,
    db: AsyncSession = Depends(get_db),
) -> ItemBatchGetResponse:
    """
    批量获取饰品
    
    一次性获取多个饰品的详细信息，支持批量查询。
    
    ## 参数说明
    
    | 参数 | 类型 | 必填 | 说明 |
    |------|------|------|------|
    | item_ids | List[int] | 是 | 饰品ID列表，最多100个 |
    
    ## 返回格式
    
    ```json
    {
        "items": [...],
        "found_count": 10,
        "not_found_ids": [101, 102],
        "total": 12
    }
    ```
    
    ## 错误码
    
    - 400: 批量大小超限或数据格式错误
    
    ## 示例
    
    ```bash
    # 批量获取饰品
    curl -X POST "http://localhost:8000/api/v1/items/batch" \
      -H "Content-Type: application/json" \
      -d '{"item_ids": [1, 2, 3, 100, 200]}'
    ```
    """
    # 使用 BatchValidator 验证批量请求
    _item_batch_validator.validate(request.item_ids)
    
    # 批量查询
    item_ids = request.item_ids
    
    # 批量查询
    query = select(Item).where(Item.id.in_(item_ids))
    result = await db.execute(query)
    items = result.scalars().all()
    
    # 构建结果
    found_items = {item.id: item for item in items}
    found_ids = list(found_items.keys())
    not_found_ids = [item_id for item_id in item_ids if item_id not in found_ids]
    
    # 按原始顺序返回
    ordered_items = [found_items[item_id] for item_id in item_ids if item_id in found_ids]
    
    return {
        "items": [ItemResponse.model_validate(item) for item in ordered_items],
        "found_count": len(found_items),
        "not_found_ids": not_found_ids,
        "total": len(item_ids)
    }
