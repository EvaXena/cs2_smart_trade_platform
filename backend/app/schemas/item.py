# -*- coding: utf-8 -*-
"""
饰品 Schema
"""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, ConfigDict


# ===== 饰品相关 =====

class ItemBase(BaseModel):
    """饰品基础"""
    market_hash_name: str
    name: str


class ItemCreate(ItemBase):
    """饰品创建"""
    app_id: int = 730
    name_cn: Optional[str] = None
    rarity: Optional[str] = None
    exterior: Optional[str] = None
    category: Optional[str] = None
    quality: Optional[str] = None
    image_url: Optional[str] = None


class ItemUpdate(BaseModel):
    """饰品更新"""
    name_cn: Optional[str] = None
    rarity: Optional[str] = None
    exterior: Optional[str] = None
    category: Optional[str] = None
    current_price: Optional[float] = None
    lowest_price: Optional[float] = None
    volume_24h: Optional[int] = None


class ItemInDB(ItemBase):
    """数据库饰品"""
    id: int
    app_id: int
    name_cn: Optional[str] = None
    rarity: Optional[str] = None
    exterior: Optional[str] = None
    category: Optional[str] = None
    quality: Optional[str] = None
    weapon_id: Optional[str] = None
    image_url: Optional[str] = None
    current_price: float = 0
    lowest_price: float = 0
    highest_price: float = 0
    volume_24h: int = 0
    steam_lowest_price: float = 0
    steam_volume_24h: int = 0
    price_change_24h: float = 0
    price_change_percent: float = 0
    updated_at: datetime
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ItemResponse(ItemInDB):
    """饰品响应"""
    pass


class ItemListResponse(BaseModel):
    """饰品列表响应"""
    items: List[ItemResponse]
    total: int
    page: int = 1
    page_size: int = 20


class ItemSearchRequest(BaseModel):
    """饰品搜索请求"""
    keyword: Optional[str] = None
    category: Optional[str] = None
    rarity: Optional[str] = None
    exterior: Optional[str] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    page: int = 1
    page_size: int = 20
    sort_by: str = "current_price"  # current_price / volume_24h / price_change_percent
    sort_order: str = "asc"  # asc / desc


# ===== 价格历史 =====

class PriceHistoryBase(BaseModel):
    """价格历史基础"""
    item_id: int
    source: str
    price: float


class PriceHistoryInDB(PriceHistoryBase):
    """数据库价格历史"""
    id: int
    recorded_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PriceHistoryResponse(PriceHistoryInDB):
    """价格历史响应"""
    pass


class PriceHistoryListResponse(BaseModel):
    """价格历史列表响应"""
    data: List[PriceHistoryResponse]
    item_id: int
    source: str


# ===== 价格概览 =====

class PriceOverview(BaseModel):
    """价格概览"""
    item_id: int
    market_hash_name: str
    buff_price: Optional[float] = None
    steam_price: Optional[float] = None
    arbitrage_profit: Optional[float] = None
    arbitrage_percent: Optional[float] = None
    volume_24h: int = 0
    price_trend: str = "stable"  # up / down / stable
