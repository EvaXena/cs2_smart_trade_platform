# -*- coding: utf-8 -*-
"""
用户 Schema
"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field, ConfigDict


# ===== 用户相关 =====

class UserBase(BaseModel):
    """用户基础"""
    username: str = Field(..., min_length=3, max_length=100)
    email: Optional[EmailStr] = None


class UserCreate(UserBase):
    """用户创建"""
    password: str = Field(..., min_length=6)


class UserUpdate(BaseModel):
    """用户更新"""
    email: Optional[EmailStr] = None
    steam_id: Optional[str] = None
    buff_cookie: Optional[str] = None
    ma_file: Optional[str] = None


class UserInDB(UserBase):
    """数据库用户"""
    id: int
    steam_id: Optional[str] = None
    balance: float = 0
    is_active: bool = True
    is_superuser: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserResponse(UserInDB):
    """用户响应"""
    pass


class UserLogin(BaseModel):
    """用户登录"""
    username: str
    password: str


class Token(BaseModel):
    """令牌"""
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    """令牌数据"""
    user_id: Optional[int] = None


# ===== Steam 账户配置 =====

class SteamAccountConfig(BaseModel):
    """Steam 账户配置"""
    steam_id: str
    session_token: str
    ma_file: str


class BuffAccountConfig(BaseModel):
    """BUFF 账户配置"""
    buff_cookie: str
