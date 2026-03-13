# -*- coding: utf-8 -*-
"""
库存 Schema
"""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, ConfigDict
from decimal import Decimal


class InventoryBase(BaseModel):
    """库存基础"""
    item_id: int
    asset_id: Optional[str] = None
    amount: int = 1


class InventoryCreate(InventoryBase):
    """创建库存记录"""
    instance_id: Optional[str] = None
    context_id: Optional[int] = 2
    class_id: Optional[str] = None
    cost_price: Optional[Decimal] = None
    float_value: Optional[float] = None
    paint_seed: Optional[int] = None
    raw_data: Optional[str] = None


class InventoryUpdate(BaseModel):
    """更新库存"""
    cost_price: Optional[Decimal] = None
    status: Optional[str] = None
    float_value: Optional[float] = None
    paint_seed: Optional[int] = None


class InventoryInDB(InventoryBase):
    """数据库库存"""
    id: int
    user_id: int
    instance_id: Optional[str] = None
    context_id: int = 2
    class_id: Optional[str] = None
    cost_price: Optional[Decimal] = None
    status: str = 'available'
    float_value: Optional[float] = None
    paint_seed: Optional[int] = None
    raw_data: Optional[str] = None
    acquired_at: datetime
    listed_at: Optional[datetime] = None
    sold_at: Optional[datetime] = None
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class InventoryResponse(InventoryInDB):
    """库存响应"""
    pass


class InventoryListResponse(BaseModel):
    """库存列表响应"""
    items: List[InventoryResponse]
    total: int


class ListingBase(BaseModel):
    """上架基础"""
    inventory_id: int
    price: Decimal = Field(..., decimal_places=2)
    platform: str = Field(..., description="steam/buff")


class ListingCreate(ListingBase):
    """创建上架"""
    pass


class ListingInDB(ListingBase):
    """数据库上架记录"""
    id: int
    listing_id: Optional[str] = None
    status: str = 'listing'
    listed_at: datetime
    sold_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    sold_price: Optional[Decimal] = None
    buyer_steam_id: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class ListingResponse(ListingInDB):
    """上架响应"""
    pass


class ListingListResponse(BaseModel):
    """上架列表响应"""
    listings: List[ListingResponse]
    total: int


class SyncInventoryResponse(BaseModel):
    """同步库存响应"""
    success: bool
    message: str
    added_count: int = 0
    updated_count: int = 0
    removed_count: int = 0


class BatchListingRequest(BaseModel):
    """批量上架请求"""
    inventory_ids: Optional[List[int]] = Field(None, alias="item_ids")
    price: Optional[Decimal] = Field(None, decimal_places=2)
    platform: str = "steam"
    
    class Config:
        populate_by_name = True


class BatchUnlistRequest(BaseModel):
    """批量下架请求"""
    listing_ids: List[int]


class BatchResponse(BaseModel):
    """批量操作响应"""
    success: bool
    message: str
    success_count: int = 0
    failed_count: int = 0
    failed_ids: List[int] = []
