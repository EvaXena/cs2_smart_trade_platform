# -*- coding: utf-8 -*-
"""
机器人 Schema
"""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, ConfigDict


class BotBase(BaseModel):
    """机器人基础"""
    name: str = Field(..., min_length=1, max_length=100)
    steam_id: Optional[str] = None
    username: Optional[str] = None


class BotCreate(BotBase):
    """创建机器人"""
    session_token: Optional[str] = None
    ma_file: Optional[str] = None
    access_token: Optional[str] = None


class BotUpdate(BaseModel):
    """更新机器人"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    steam_id: Optional[str] = None
    username: Optional[str] = None
    status: Optional[str] = None


class BotInDB(BotBase):
    """数据库机器人"""
    id: int
    # 敏感字段通过属性方法解密，不直接暴露在 API 响应中
    # 使用 exclude 避免 Pydantic 从 ORM 属性方法读取敏感数据
    status: str = 'offline'
    inventory_count: int = 0
    total_trades: int = 0
    successful_trades: int = 0
    last_activity: Optional[datetime] = None
    last_trade_time: Optional[datetime] = None
    last_error: Optional[str] = None
    owner_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BotResponse(BotInDB):
    """机器人响应 - 排除敏感字段"""
    model_config = ConfigDict(
        from_attributes=True,
        exclude={'session_token', 'ma_file', 'access_token'}
    )


class BotLoginRequest(BaseModel):
    """机器人登录请求"""
    session_token: Optional[str] = None
    ma_file: Optional[str] = None


class BotLoginResponse(BaseModel):
    """机器人登录响应"""
    success: bool
    message: str
    status: str


class BotInventoryItem(BaseModel):
    """机器人库存物品"""
    asset_id: str
    class_id: str
    instance_id: str
    amount: int
    name: str
    market_hash_name: str
    price: Optional[float] = None
    float_value: Optional[float] = None


class BotInventoryResponse(BaseModel):
    """机器人库存响应"""
    items: List[BotInventoryItem]
    total_count: int


class BotTradeResponse(BaseModel):
    """机器人交易响应"""
    trades: List[dict]
    total_count: int
