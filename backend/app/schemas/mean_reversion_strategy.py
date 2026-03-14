# -*- coding: utf-8 -*-
"""
均值回归策略 schemas
"""
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict


class MeanReversionStrategyCreate(BaseModel):
    """创建均值回归策略请求"""
    name: str = Field(..., description="策略名称")
    item_id: int = Field(..., description="饰品ID")
    mean_period: int = Field(20, description="均值周期", ge=5, le=200)
    mean_type: str = Field("EMA", description="均值类型: MA/EMA")
    buy_threshold: float = Field(-2.0, description="买入偏离阈值(%)", ge=-50, le=0)
    sell_threshold: float = Field(2.0, description="卖出偏离阈值(%)", ge=0, le=50)
    profit_percentage: float = Field(3.0, description="止盈百分比", ge=0.1, le=50)
    stop_loss_percentage: float = Field(5.0, description="止损百分比", ge=0.1, le=50)
    position_size: int = Field(1, description="持仓数量", ge=1)


class MeanReversionStrategyUpdate(BaseModel):
    """更新均值回归策略请求"""
    name: Optional[str] = None
    mean_period: Optional[int] = Field(None, description="均值周期", ge=5, le=200)
    mean_type: Optional[str] = None
    buy_threshold: Optional[float] = Field(None, description="买入偏离阈值(%)", ge=-50, le=0)
    sell_threshold: Optional[float] = Field(None, description="卖出偏离阈值(%)", ge=0, le=50)
    profit_percentage: Optional[float] = Field(None, description="止盈百分比", ge=0.1, le=50)
    stop_loss_percentage: Optional[float] = Field(None, description="止损百分比", ge=0.1, le=50)
    position_size: Optional[int] = Field(None, description="持仓数量", ge=1)
    is_active: Optional[bool] = None


class MeanReversionStrategyResponse(BaseModel):
    """均值回归策略响应"""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    user_id: int
    item_id: int
    name: str
    mean_period: int
    mean_type: str
    buy_threshold: float
    sell_threshold: float
    profit_percentage: float
    stop_loss_percentage: float
    position_size: int
    is_active: bool
    status: str
    last_price: Optional[float] = None
    entry_price: Optional[float] = None
    mean_price: Optional[float] = None
    total_trades: int
    total_profit: float
    winning_trades: int
    losing_trades: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    stopped_at: Optional[datetime] = None


class MeanReversionStrategyListResponse(BaseModel):
    """均值回归策略列表响应"""
    strategies: List[MeanReversionStrategyResponse]
    total: int
    page: int
    page_size: int


class MeanReversionStrategyOperationResponse(BaseModel):
    """均值回归策略操作响应"""
    strategy_id: int
    success: bool
    message: str
    data: Optional[dict] = None


class MeanReversionPriceUpdateRequest(BaseModel):
    """价格更新请求"""
    price: float = Field(..., description="当前价格", gt=0)


class MeanReversionPriceUpdateResponse(BaseModel):
    """价格更新响应"""
    action: str
    current_price: float
    mean_price: Optional[float] = None
    deviation: Optional[float] = None
    message: Optional[str] = None
