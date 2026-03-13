# -*- coding: utf-8 -*-
"""
认证端点 v2
增强版 - 支持Token刷新、更好的安全性
"""
import re
import time
import json
import logging
from datetime import timedelta
from typing import Dict, Tuple, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Request, Query, Query
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.core.database import get_db
from app.core.security import (
    verify_password,
    get_password_hash,
    create_access_token,
    decode_token,
    get_current_user,
    oauth2_scheme,
)
from app.core.token_blacklist import add_token_to_blacklist
from app.core.redis_manager import get_redis
from app.models.user import User
from app.schemas.user import (
    UserCreate,
    UserResponse,
    UserLogin,
    Token,
    UserUpdate,
)

logger = logging.getLogger(__name__)


def mask_username(username: str) -> str:
    """脱敏用户名用于日志记录"""
    if not username or len(username) <= 2:
        return "*" * 3
    return username[0] + "*" * (len(username) - 2) + username[-1]


router = APIRouter()

# Redis 键前缀
_LOGIN_ATTEMPTS_PREFIX = "v2:login:attempts:"
_LOCKED_ACCOUNTS_PREFIX = "v2:login:locked:"
MAX_AGE_SECONDS = 900  # 15分钟


def validate_password_strength(password: str) -> Tuple[bool, str]:
    """验证密码强度"""
    if len(password) < 8:
        return False, "密码长度至少为 8 个字符"
    
    has_lowercase = bool(re.search(r'[a-z]', password))
    has_uppercase = bool(re.search(r'[A-Z]', password))
    has_digit = bool(re.search(r'\d', password))
    has_special = bool(re.search(r'[!@#$%^&*()_+\-=\[\]{};:\'",.<>?/\\|`~]', password))
    
    types_count = sum([has_lowercase, has_uppercase, has_digit, has_special])
    
    if types_count < 2:
        missing_types = []
        if not has_lowercase:
            missing_types.append("小写字母")
        if not has_uppercase:
            missing_types.append("大写字母")
        if not has_digit:
            missing_types.append("数字")
        if not has_special:
            missing_types.append("特殊字符")
        
        return False, f"密码必须包含至少2种字符类型，当前缺少: {', '.join(missing_types)}"
    
    return True, ""


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(
    user_data: UserCreate,
    db: AsyncSession = Depends(get_db)
):
    """用户注册 v2"""
    is_valid, error_msg = validate_password_strength(user_data.password)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_msg
        )
    
    result = await db.execute(
        select(User).where(User.username == user_data.username)
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="用户名已存在"
        )
    
    if user_data.email:
        result = await db.execute(
            select(User).where(User.email == user_data.email)
        )
        if result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="邮箱已被使用"
            )
    
    user = User(
        username=user_data.username,
        email=user_data.email,
        hashed_password=get_password_hash(user_data.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    
    return user


@router.post("/login", response_model=Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db)
):
    """用户登录 v2 - 返回access_token和refresh_token"""
    username = form_data.username
    
    # 查找用户
    result = await db.execute(
        select(User).where(User.username == username)
    )
    user = result.scalar_one_or_none()
    
    if not user or not verify_password(form_data.password, user.hashed_password):
        logger.warning(f"登录失败: {mask_username(username)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账户已被禁用"
        )
    
    # 创建访问令牌和刷新令牌
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": str(user.id), "type": "access"},
        expires_delta=access_token_expires
    )
    
    refresh_token_expires = timedelta(minutes=settings.REFRESH_TOKEN_EXPIRE_MINUTES or 10080)  # 默认7天
    refresh_token = create_access_token(
        data={"sub": str(user.id), "type": "refresh"},
        expires_delta=refresh_token_expires
    )
    
    logger.info(f"用户登录成功: {mask_username(username)}")
    
    return {
        "access_token": access_token, 
        "token_type": "bearer",
        "refresh_token": refresh_token
    }


@router.post("/refresh", response_model=Token)
async def refresh_token(
    refresh_token: str = Query(..., description="Refresh Token"),
    db: AsyncSession = Depends(get_db)
):
    """刷新Access Token"""
    # 验证refresh token
    payload = decode_token(refresh_token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的refresh token"
        )
    
    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的token类型"
        )
    
    user_id = payload.get("sub")
    if isinstance(user_id, str):
        user_id = int(user_id)
    
    # 查找用户
    result = await db.execute(
        select(User).where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在或已被禁用"
        )
    
    # 生成新的access token
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": str(user.id), "type": "access"},
        expires_delta=access_token_expires
    )
    
    # 生成新的refresh token（轮换）
    new_refresh_expires = timedelta(minutes=settings.REFRESH_TOKEN_EXPIRE_MINUTES or 10080)
    new_refresh_token = create_access_token(
        data={"sub": str(user.id), "type": "refresh"},
        expires_delta=new_refresh_expires
    )
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "refresh_token": new_refresh_token
    }


@router.post("/logout")
async def logout(
    current_user: User = Depends(get_current_user),
    token: str = Depends(oauth2_scheme)
):
    """用户登出 v2 - 使 token 失效"""
    await add_token_to_blacklist(token)
    return {"message": "登出成功"}


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: User = Depends(get_current_user)
):
    """获取当前用户信息 v2"""
    return current_user


@router.put("/me", response_model=UserResponse)
async def update_current_user(
    user_data: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """更新当前用户信息 v2"""
    if user_data.email is not None:
        current_user.email = user_data.email
    if user_data.steam_id is not None:
        current_user.steam_id = user_data.steam_id
    if user_data.buff_cookie is not None:
        current_user.buff_cookie = user_data.buff_cookie
    if user_data.ma_file is not None:
        current_user.ma_file = user_data.ma_file
    
    await db.commit()
    await db.refresh(current_user)
    
    return current_user


@router.post("/change-password")
async def change_password(
    old_password: str,
    new_password: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """修改密码 v2"""
    # 验证旧密码
    if not verify_password(old_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="原密码错误"
        )
    
    # 验证新密码强度
    is_valid, error_msg = validate_password_strength(new_password)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_msg
        )
    
    # 更新密码
    current_user.hashed_password = get_password_hash(new_password)
    await db.commit()
    
    logger.info(f"用户 {mask_username(current_user.username)} 修改了密码")
    
    return {"message": "密码修改成功，请重新登录"}
