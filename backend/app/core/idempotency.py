# -*- coding: utf-8 -*-
"""
API 幂等性保护模块
防止重复请求导致的重复操作
"""
import hashlib
import logging
from datetime import datetime, timedelta
from typing import Optional

from app.core.redis_manager import get_redis

logger = logging.getLogger(__name__)

# 幂等性 key 前缀
IDEMPOTENCY_PREFIX = "idempotency:"
# 默认过期时间 24 小时
DEFAULT_TTL_SECONDS = 86400


def generate_idempotency_key(
    user_id: int,
    method: str,
    path: str,
    request_body: str
) -> str:
    """
    生成幂等性 key
    
    参数:
        user_id: 用户 ID
        method: HTTP 方法
        path: 请求路径
        request_body: 请求体
    
    返回:
        幂等性 key
    """
    # 组合所有信息
    key_data = f"{user_id}:{method}:{path}:{request_body}"
    # 使用 SHA256 生成哈希作为 key
    key_hash = hashlib.sha256(key_data.encode()).hexdigest()
    return f"{IDEMPOTENCY_PREFIX}{key_hash}"


async def check_idempotency(key: str) -> tuple[bool, Optional[dict]]:
    """
    检查请求是否已处理
    
    参数:
        key: 幂等性 key
    
    返回:
        (是否已处理, 已保存的响应)
    """
    redis_client = await get_redis()
    
    # 检查 key 是否存在
    exists = await redis_client.exists(key)
    if exists:
        # 获取已保存的响应
        cached_response = await redis_client.get(key)
        if cached_response:
            import json
            return True, json.loads(cached_response)
    
    return False, None


async def save_idempotent_response(key: str, response_data: dict, ttl: int = DEFAULT_TTL_SECONDS):
    """
    保存幂等性响应
    
    参数:
        key: 幂等性 key
        response_data: 响应数据
        ttl: 过期时间（秒）
    """
    redis_client = await get_redis()
    
    import json
    await redis_client.setex(key, ttl, json.dumps(response_data))


async def create_idempotent_key(
    user_id: int,
    method: str,
    path: str,
    body: str = ""
) -> str:
    """创建幂等性 key 的便捷函数"""
    return generate_idempotency_key(user_id, method, path, body)
