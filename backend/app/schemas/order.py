# -*- coding: utf-8 -*-
"""
订单 Schema
"""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field
from enum import Enum


class OrderSide(str, Enum):
    """订单方向"""
    BUY = "buy"
    SELL = "sell"


class OrderStatus(str, Enum):
    """订单状态"""
    PENDING = "pending"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class OrderSource(str, Enum):
    """订单来源"""
    STEAM = "steam"
    BUFF = "buff"
    MANUAL = "manual"


class OrderBase(BaseModel):
    """订单基础"""
    item_id: int
    side: OrderSide
    price: float = Field(..., gt=0)
    quantity: int = Field(default=1, ge=1)


class OrderCreate(OrderBase):
    """订单创建"""
    source: OrderSource = OrderSource.MANUAL


class OrderUpdate(BaseModel):
    """订单更新"""
    status: Optional[OrderStatus] = None
    remark: Optional[str] = None


class OrderInDB(OrderBase):
    """数据库订单"""
    id: int
    order_id: Optional[str] = None
    user_id: int
    status: str = "pending"
    source: str
    external_id: Optional[str] = None
    remark: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class OrderResponse(OrderInDB):
    """订单响应"""
    pass


class OrderListResponse(BaseModel):
    """订单列表响应"""
    orders: List[OrderResponse]
    total: int
    page: int = 1
    page_size: int = 20


class OrderCancelRequest(BaseModel):
    """取消订单请求"""
    order_id: str
