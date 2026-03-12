# -*- coding: utf-8 -*-
"""
认证端点
"""
import re
import time
import json
import logging
from datetime import timedelta
from typing import Dict, Tuple, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Request, Header
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.core.database import get_db
from app.core.security import (
    verify_password,
    get_password_hash,
    create_access_token,
    get_current_user,
    oauth2_scheme,
)
from app.core.token_blacklist import add_token_to_blacklist
from app.core.redis_manager import get_redis
from app.core.idempotency import (
    generate_idempotency_key,
    check_idempotency,
    save_idempotent_response,
)
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
_LOGIN_ATTEMPTS_PREFIX = "login:attempts:"
_LOCKED_ACCOUNTS_PREFIX = "login:locked:"
MAX_AGE_SECONDS = 900  # 15分钟


# Lua 脚本：原子检查+更新登录尝试
# 返回值: [can_login, attempts_count, error_message]
# can_login: 1=允许登录, 0=拒绝
LOGIN_CHECK_AND_RECORD_SCRIPT = """
local attempts_key = KEYS[1]
local locked_key = KEYS[2]
local max_attempts = tonumber(ARGV[1])
local lockout_seconds = tonumber(ARGV[2])
local current_time = tonumber(ARGV[3])
local max_age_seconds = tonumber(ARGV[4])
local record_attempt = tonumber(ARGV[5])  -- 1=记录尝试, 0=仅检查

-- 检查是否被锁定
local locked_until = redis.call("get", locked_key)
if locked_until then
    local locked_time = tonumber(locked_until)
    if current_time < locked_time then
        local remaining = locked_time - current_time
        return {0, 0, "locked:" .. remaining}
    else
        -- 解除锁定
        redis.call("del", locked_key)
        redis.call("del", attempts_key)
    end
end

-- 获取当前尝试记录
local attempts_data = redis.call("get", attempts_key)
local attempts = {}
if attempts_data then
    attempts = cjson.decode(attempts_data)
end

-- 清理过期记录
local valid_attempts = {}
for _, ts in ipairs(attempts) do
    if current_time - ts < max_age_seconds then
        table.insert(valid_attempts, ts)
    end
end

-- 检查是否超限
if #valid_attempts >= max_attempts then
    -- 锁定账户
    local locked_time = current_time + lockout_seconds
    redis.call("setex", locked_key, lockout_seconds, locked_time)
    redis.call("del", attempts_key)
    return {0, #valid_attempts, "locked:" .. lockout_seconds}
end

-- 记录新的登录尝试
if record_attempt == 1 then
    table.insert(valid_attempts, current_time)
    redis.call("setex", attempts_key, max_age_seconds, cjson.encode(valid_attempts))
end

return {1, #valid_attempts, ""}
"""


async def _cleanup_old_attempts(username: str, max_age_seconds: int = 900):
    """清理旧的登录尝试记录（Redis TTL 自动处理）"""
    pass  # Redis 通过 TTL 自动清理


async def _check_and_record_login_attempt_atomic(username: str, record_attempt: bool = True) -> Tuple[bool, int, Optional[str]]:
    """
    原子检查并记录登录尝试（使用 Lua 脚本）
    
    返回: (can_login, attempts_count, error_message)
    """
    client = await get_redis()
    
    attempts_key = f"{_LOGIN_ATTEMPTS_PREFIX}{username}"
    locked_key = f"{_LOCKED_ACCOUNTS_PREFIX}{username}"
    current_time = time.time()
    
    # 执行 Lua 脚本
    result = await client.eval(
        LOGIN_CHECK_AND_RECORD_SCRIPT,
        2,  # keys 数量
        attempts_key, locked_key,  # KEYS[1], KEYS[2]
        settings.LOGIN_MAX_ATTEMPTS,  # ARGV[1]
        settings.LOGIN_LOCKOUT_MINUTES * 60,  # ARGV[2]
        current_time,  # ARGV[3]
        MAX_AGE_SECONDS,  # ARGV[4]
        1 if record_attempt else 0  # ARGV[5]
    )
    
    can_login = result[0] == 1
    attempts_count = result[1]
    error_msg = result[2]
    
    if not can_login and error_msg:
        if error_msg.startswith("locked:"):
            lockout_seconds = int(error_msg.split(":")[1])
            remaining = lockout_seconds - (time.time() - current_time)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"登录尝试过多，请 {int(remaining)} 秒后重试"
            )
    
    return can_login, attempts_count, error_msg if error_msg else None


async def _check_login_attempts(username: str) -> bool:
    """检查是否超过登录尝试限制（仅检查，不记录）"""
    can_login, _, error_msg = await _check_and_record_login_attempt_atomic(username, record_attempt=False)
    
    if not can_login and error_msg:
        if error_msg.startswith("locked:"):
            lockout_seconds = int(error_msg.split(":")[1])
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"登录尝试过多，账户已被锁定 {lockout_seconds // 60} 分钟"
            )
    
    return True


async def _record_login_attempt(username: str):
    """记录登录尝试（原子操作）"""
    await _check_and_record_login_attempt_atomic(username, record_attempt=True)


def validate_password_strength(password: str) -> Tuple[bool, str]:
    """
    验证密码强度
    
    要求:
    - 最小长度 8 字符
    - 必须包含大小写字母、数字、特殊字符中的至少2种
    
    返回: (是否通过, 错误消息)
    """
    if len(password) < 8:
        return False, "密码长度至少为 8 个字符"
    
    # 检查字符类型
    has_lowercase = bool(re.search(r'[a-z]', password))
    has_uppercase = bool(re.search(r'[A-Z]', password))
    has_digit = bool(re.search(r'\d', password))
    has_special = bool(re.search(r'[!@#$%^&*()_+\-=\[\]{};:\'",.<>?/\\|`~]', password))
    
    # 统计包含的种类数
    types_count = sum([has_lowercase, has_uppercase, has_digit, has_special])
    
    if types_count < 2:
        # 构建错误提示
        missing_types = []
        if not has_lowercase:
            missing_types.append("小写字母")
        if not has_uppercase:
            missing_types.append("大写字母")
        if not has_digit:
            missing_types.append("数字")
        if not has_special:
            missing_types.append("特殊字符(!@#$%^&*等)")
        
        return False, f"密码必须包含至少2种字符类型，当前缺少: {', '.join(missing_types)}"
    
    return True, ""


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(
    user_data: UserCreate,
    db: AsyncSession = Depends(get_db),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")
) -> UserResponse:
    """
    用户注册
    
    创建新用户账号，支持幂等性请求。
    
    ## 参数说明
    
    请求体 (UserCreate):
    | 字段 | 类型 | 必填 | 说明 |
    |------|------|------|------|
    | username | str | 是 | 用户名，3-50字符，只允许字母、数字、下划线 |
    | email | str | 否 | 邮箱地址 |
    | password | str | 是 | 密码，至少8字符，需包含字母和数字 |
    
    ## 返回格式
    
    ```json
    {
        "id": 1,
        "username": "user123",
        "email": "user@example.com",
        "created_at": "2024-01-01T00:00:00"
    }
    ```
    
    ## 错误码
    
    - 400: 用户名已存在 / 邮箱已被使用 / 密码强度不足
    
    ## 幂等性
    
    支持通过 `Idempotency-Key` header 实现幂等性请求，避免重复创建用户。
    
    ## 示例
    
    ```bash
    curl -X POST "http://localhost:8000/api/v1/auth/register" \
      -H "Content-Type: application/json" \
      -d '{"username": "user123", "email": "user@example.com", "password": "Password123"}'
    ```
    """
    
    # 幂等性检查（仅对请求体生成key，不依赖用户ID因为用户还未创建）
    if idempotency_key:
        request_body = json.dumps(user_data.model_dump(exclude={'password': False}), sort_keys=True)
        internal_key = generate_idempotency_key(
            user_id=0,  # 未注册用户，使用0作为占位符
            method="POST",
            path="/api/v1/auth/register",
            request_body=request_body
        )
        
        # 检查是否已处理过相同请求
        is_duplicate, cached_response = await check_idempotency(internal_key)
        if is_duplicate and cached_response:
            # 返回缓存的响应
            return UserResponse(**cached_response)
    
    # 验证密码强度
    is_valid, error_msg = validate_password_strength(user_data.password)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_msg
        )
    
    # 检查用户名是否已存在
    result = await db.execute(
        select(User).where(User.username == user_data.username)
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="用户名已存在"
        )
    
    # 检查邮箱是否已存在
    if user_data.email:
        result = await db.execute(
            select(User).where(User.email == user_data.email)
        )
        if result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="邮箱已被使用"
            )
    
    # 创建用户
    user = User(
        username=user_data.username,
        email=user_data.email,
        hashed_password=get_password_hash(user_data.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    
    # 保存幂等性响应
    if idempotency_key:
        response_data = UserResponse.model_validate(user).model_dump()
        await save_idempotent_response(internal_key, response_data)
    
    return user


@router.post("/login", response_model=Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db)
) -> Token:
    """
    用户登录
    
    使用用户名和密码登录，返回访问令牌。支持登录失败限制防止暴力破解。
    
    ## 参数说明
    
    使用 OAuth2PasswordRequestForm（application/x-www-form-urlencoded）:
    | 字段 | 类型 | 必填 | 说明 |
    |------|------|------|------|
    | username | str | 是 | 用户名 |
    | password | str | 是 | 密码 |
    
    ## 返回格式
    
    ```json
    {
        "access_token": "eyJhbGciOiJIUzI1NiIs...",
        "token_type": "bearer"
    }
    ```
    
    ## 安全特性
    
    - 登录失败5次后锁定账号15分钟
    - 密码错误不返回具体错误信息防止用户名枚举
    - Token 有效期15分钟
    
    ## 错误码
    
    - 401: 用户名或密码错误
    - 423: 账号被锁定
    
    ## 示例
    
    ```bash
    curl -X POST "http://localhost:8000/api/v1/auth/login" \
      -H "Content-Type: application/x-www-form-urlencoded" \
      -d "username=user123&password=Password123"
    ```
    """
    username = form_data.username
    
    # 检查登录尝试限制
    await _check_login_attempts(username)
    
    # 查找用户
    result = await db.execute(
        select(User).where(User.username == username)
    )
    user = result.scalar_one_or_none()
    
    if not user or not verify_password(form_data.password, user.hashed_password):
        # 记录失败的登录尝试
        await _record_login_attempt(username)
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
    
    # 登录成功，清除尝试记录
    client = await get_redis()
    attempts_key = f"{_LOGIN_ATTEMPTS_PREFIX}{username}"
    await client.delete(attempts_key)
    
    # 创建访问令牌
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": str(user.id)},
        expires_delta=access_token_expires
    )
    
    logger.info(f"用户登录成功: {mask_username(username)}")
    
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/logout")
async def logout(
    current_user: User = Depends(get_current_user),
    token: str = Depends(oauth2_scheme)
):
    """用户登出 - 使 token 失效"""
    # 将 token 加入黑名单
    await add_token_to_blacklist(token)
    return {"message": "登出成功"}


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: User = Depends(get_current_user)
):
    """获取当前用户信息"""
    return current_user


@router.put("/me", response_model=UserResponse)
async def update_current_user(
    user_data: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """更新当前用户信息"""
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
