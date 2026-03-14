# -*- coding: utf-8 -*-
"""
网格交易 schemas
"""
from typing import Optional, List, Any
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict


class GridStrategyCreate(BaseModel):
    """创建网格策略请求"""
    name: str = Field(..., description="策略名称")
    item_id: int = Field(..., description="饰品ID")
    price_lower: float = Field(..., description="价格下界", gt=0)
    price_upper: float = Field(..., description="价格上界", gt=0)
    grid_count: int = Field(10, description="网格数量", ge=2, le=100)
    quantity_per_grid: int = Field(1, description="每格数量", ge=1)
    profit_percentage: float = Field(1.0, description="止盈百分比", ge=0.1, le=50)
    stop_loss_percentage: float = Field(5.0, description="止损百分比", ge=0.1, le=50)


class GridStrategyUpdate(BaseModel):
    """更新网格策略请求"""
    name: Optional[str] = None
    price_lower: Optional[float] = Field(None, description="价格下界", gt=0)
    price_upper: Optional[float] = Field(None, description="价格上界", gt=0)
    grid_count: Optional[int] = Field(None, description="网格数量", ge=2, le=100)
    quantity_per_grid: Optional[int] = Field(None, description="每格数量", ge=1)
    profit_percentage: Optional[float] = Field(None, description="止盈百分比", ge=0.1, le=50)
    stop_loss_percentage: Optional[float] = Field(None, description="止损百分比", ge=0.1, le=50)
    is_active: Optional[bool] = None


class GridStateItem(BaseModel):
    """网格状态项"""
    index: int
    price: float
    filled: bool
    sold: bool
    buy_order_id: Optional[str] = None
    sell_order_id: Optional[str] = None
    buy_price: Optional[float] = None
    sell_price: Optional[float] = None
    profit: float = 0.0


class GridStrategyResponse(BaseModel):
    """网格策略响应"""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    user_id: int
    item_id: int
    name: str
    price_lower: float
    price_upper: float
    grid_count: int
    quantity_per_grid: int
    profit_percentage: float
    stop_loss_percentage: float
    is_active: bool
    status: str
    last_price: Optional[float] = None
    entry_price: Optional[float] = None
    total_trades: int
    total_profit: float
    completed_grids: int
    grid_prices: Optional[List[float]] = None
    grid_states: Optional[List[GridStateItem]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    stopped_at: Optional[datetime] = None


class GridStrategyListResponse(BaseModel):
    """网格策略列表响应"""
    strategies: List[GridStrategyResponse]
    total: int
    page: int
    page_size: int


class GridStrategyOperationResponse(BaseModel):
    """网格策略操作响应"""
    strategy_id: int
    success: bool
    message: str
    data: Optional[dict] = None


class GridPriceUpdateRequest(BaseModel):
    """价格更新请求"""
    price: float = Field(..., description="当前价格", gt=0)


class GridPriceUpdateResponse(BaseModel):
    """价格更新响应"""
    actions: List[dict]
    current_price: float
