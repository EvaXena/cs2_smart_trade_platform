# -*- coding: utf-8 -*-
"""
监控任务 Schema
"""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field
from decimal import Decimal


class MonitorBase(BaseModel):
    """监控任务基础"""
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    condition_type: str = Field(..., description="price_below/price_above/arbitrage/price_drop/price_rise")
    threshold: Optional[Decimal] = Field(None, decimal_places=2)


class MonitorCreate(MonitorBase):
    """创建监控任务"""
    item_id: Optional[int] = None
    item_pattern: Optional[str] = None
    notify_enabled: bool = True
    notify_telegram: bool = False
    notify_email: bool = False
    notify_webhook: bool = False
    webhook_url: Optional[str] = None
    action: Optional[str] = Field(None, description="alert/auto_buy/auto_sell")


class MonitorUpdate(BaseModel):
    """更新监控任务"""
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    condition_type: Optional[str] = None
    threshold: Optional[Decimal] = None
    notify_enabled: Optional[bool] = None
    notify_telegram: Optional[bool] = None
    notify_email: Optional[bool] = None
    notify_webhook: Optional[bool] = None
    webhook_url: Optional[str] = None
    action: Optional[str] = None
    enabled: Optional[bool] = None


class MonitorInDB(MonitorBase):
    """数据库监控任务"""
    id: int
    item_id: Optional[int] = None
    item_pattern: Optional[str] = None
    notify_enabled: bool = True
    notify_telegram: bool = False
    notify_email: bool = False
    notify_webhook: bool = False
    webhook_url: Optional[str] = None
    action: Optional[str] = None
    enabled: bool = True
    status: str = 'idle'
    user_id: int
    trigger_count: int = 0
    last_triggered: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MonitorResponse(MonitorInDB):
    """监控任务响应"""
    pass


class MonitorListResponse(BaseModel):
    """监控任务列表响应"""
    items: List[MonitorResponse]
    total: int


class MonitorLogBase(BaseModel):
    """监控日志基础"""
    trigger_type: str
    message: Optional[str] = None
    price_data: Optional[str] = None
    action_result: Optional[str] = None


class MonitorLogResponse(MonitorLogBase):
    """监控日志响应"""
    id: int
    task_id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MonitorLogListResponse(BaseModel):
    """监控日志列表响应"""
    logs: List[MonitorLogResponse]
    total: int


class MonitorActionResponse(BaseModel):
    """监控操作响应"""
    success: bool
    message: str
    status: str
