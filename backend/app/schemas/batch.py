# -*- coding: utf-8 -*-
"""
批量请求 Schema

提供统一的批量请求/响应格式，支持：
- 订单批量操作
- 物品批量操作
- 通用批量操作
"""
from __future__ import annotations

from datetime import datetime
from typing import TypeVar, Generic, List, Optional, Any
from pydantic import BaseModel, Field, field_validator

from app.schemas.order import OrderCreate, OrderSide, OrderSource
from app.schemas.item import ItemResponse

T = TypeVar('T', bound=BaseModel)


# ============ 通用批量模型 ============

class BatchRequest(BaseModel):
    """批量请求基类"""
    items: List[dict] = Field(..., description="批量数据项列表")
    
    @field_validator('items')
    @classmethod
    def validate_items_not_empty(cls, v):
        if not v:
            raise ValueError("批量数据不能为空")
        return v


class BatchResponse(BaseModel):
    """批量响应基类"""
    success_count: int = Field(..., description="成功处理数量")
    fail_count: int = Field(..., description="失败处理数量")
    total: int = Field(..., description="总数量")


class BatchItemResponse(BaseModel):
    """批量单项响应"""
    index: int = Field(..., description="原始索引")
    success: bool = Field(..., description="是否成功")
    data: Optional[dict] = Field(None, description="成功时的数据")
    error: Optional[str] = Field(None, description="失败时的错误信息")


class BatchResultResponse(BaseModel):
    """批量结果响应"""
    results: List[BatchItemResponse] = Field(..., description="每项的处理结果")
    success_count: int = Field(..., description="成功数量")
    fail_count: int = Field(..., description="失败数量")
    total: int = Field(..., description="总数量")


# ============ 订单批量模型 ============

class OrderBatchCreate(BaseModel):
    """订单批量创建请求"""
    orders: List[OrderCreate] = Field(..., description="订单创建列表", max_length=100)
    
    @field_validator('orders')
    @classmethod
    def validate_orders_not_empty(cls, v):
        if not v:
            raise ValueError("订单列表不能为空")
        if len(v) > 100:
            raise ValueError("单次批量创建订单不能超过100个")
        return v


class OrderBatchItem(BaseModel):
    """订单批量单项"""
    item_id: int = Field(..., gt=0, description="饰品ID")
    side: OrderSide = Field(..., description="订单方向: buy/sell")
    price: float = Field(..., gt=0, le=10000, description="价格")
    quantity: int = Field(default=1, ge=1, le=100, description="数量")
    source: OrderSource = Field(default=OrderSource.MANUAL, description="订单来源")


class OrderBatchCreateRequest(BaseModel):
    """订单批量创建请求 (使用简化格式)"""
    orders: List[OrderBatchItem] = Field(..., description="订单列表", max_length=100)
    
    @field_validator('orders')
    @classmethod
    def validate_orders_not_empty(cls, v):
        if not v:
            raise ValueError("订单列表不能为空")
        if len(v) > 100:
            raise ValueError("单次批量创建订单不能超过100个")
        return v


class OrderBatchResponse(BaseModel):
    """订单批量响应"""
    orders: List[dict] = Field(..., description="创建的订单列表")
    success_count: int = Field(..., description="成功数量")
    fail_count: int = Field(..., description="失败数量")
    total: int = Field(..., description="总数量")


class OrderBatchCancelRequest(BaseModel):
    """订单批量取消请求"""
    order_ids: List[str] = Field(..., description="订单ID列表", max_length=50)
    
    @field_validator('order_ids')
    @classmethod
    def validate_order_ids_not_empty(cls, v):
        if not v:
            raise ValueError("订单ID列表不能为空")
        if len(v) > 50:
            raise ValueError("单次批量取消订单不能超过50个")
        return v


class OrderBatchCancelResponse(BaseModel):
    """订单批量取消响应"""
    success_count: int = Field(..., description="成功取消数量")
    fail_count: int = Field(..., description="失败数量")
    results: List[dict] = Field(..., description="每项取消结果")


# ============ 物品批量模型 ============

class ItemBatchGetRequest(BaseModel):
    """物品批量获取请求"""
    item_ids: List[int] = Field(..., description="物品ID列表", max_length=100)
    
    @field_validator('item_ids')
    @classmethod
    def validate_item_ids_not_empty(cls, v):
        if not v:
            raise ValueError("物品ID列表不能为空")
        if len(v) > 100:
            raise ValueError("单次批量获取物品不能超过100个")
        return v
    
    @field_validator('item_ids')
    @classmethod
    def validate_item_ids_positive(cls, v):
        for item_id in v:
            if item_id <= 0:
                raise ValueError("物品ID必须大于0")
        return v


class ItemBatchGetResponse(BaseModel):
    """物品批量获取响应"""
    items: List[ItemResponse] = Field(..., description="物品列表")
    found_count: int = Field(..., description="找到的物品数量")
    not_found_ids: List[int] = Field(default_factory=list, description="未找到的物品ID")
    total: int = Field(..., description="请求的总数量")


class ItemBatchPriceUpdate(BaseModel):
    """物品批量价格更新"""
    item_id: int = Field(..., gt=0, description="饰品ID")
    price: float = Field(..., gt=0, le=100000, description="新价格")


class ItemBatchPriceUpdateRequest(BaseModel):
    """物品批量价格更新请求"""
    prices: List[ItemBatchPriceUpdate] = Field(..., description="价格更新列表", max_length=50)
    
    @field_validator('prices')
    @classmethod
    def validate_prices_not_empty(cls, v):
        if not v:
            raise ValueError("价格更新列表不能为空")
        if len(v) > 50:
            raise ValueError("单次批量更新价格不能超过50个")
        return v


class ItemBatchPriceUpdateResponse(BaseModel):
    """物品批量价格更新响应"""
    success_count: int = Field(..., description="成功更新数量")
    fail_count: int = Field(..., description="失败数量")
    results: List[dict] = Field(..., description="每项更新结果")
