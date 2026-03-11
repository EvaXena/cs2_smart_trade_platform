# -*- coding: utf-8 -*-
"""
API 幂等性保护模块
防止重复请求导致的重复操作
"""
import asyncio
import hashlib
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, Tuple

from app.core.redis_manager import get_redis

logger = logging.getLogger(__name__)

# 幂等性 key 前缀
IDEMPOTENCY_PREFIX = "idempotency:"
# 默认过期时间 24 小时
DEFAULT_TTL_SECONDS = 86400


def _recursive_sort(obj):
    """
    递归排序对象（用于标准化 JSON 以生成一致的 key）
    
    Args:
        obj: 任意 Python 对象
    
    Returns:
        排序后的对象
    """
    if isinstance(obj, dict):
        return {k: _recursive_sort(v) for k, v in sorted(obj.items())}
    elif isinstance(obj, list):
        return [_recursive_sort(item) for item in obj]
    return obj


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
    # 尝试解析 JSON 并排序键，确保相同内容的不同 JSON 顺序产生相同的 key
    try:
        body_obj = json.loads(request_body)
        sorted_body = _recursive_sort(body_obj)
        normalized_body = json.dumps(sorted_body, sort_keys=True)
    except (json.JSONDecodeError, TypeError):
        # 如果不是有效的 JSON，直接使用原始字符串
        normalized_body = request_body
    
    # 组合所有信息
    key_data = f"{user_id}:{method}:{path}:{normalized_body}"
    # 使用 SHA256 生成哈希作为 key
    key_hash = hashlib.sha256(key_data.encode()).hexdigest()
    return f"{IDEMPOTENCY_PREFIX}{key_hash}"


async def check_idempotency(key: str) -> Tuple[bool, Optional[dict]]:
    """
    检查请求是否已处理（原子操作）
    
    参数:
        key: 幂等性 key
    
    返回:
        (是否已处理, 已保存的响应)
    """
    import json
    redis_client = await get_redis()
    
    # 使用 SETNX + GET 实现原子检查
    # 先尝试设置锁（如果不存在）
    lock_key = f"{key}:lock"
    
    # 使用原子操作获取锁
    acquired = await redis_client.set(
        lock_key, 
        "1", 
        nx=True,  # 仅当不存在时设置
        ex=30     # 锁过期时间 30 秒
    )
    
    if acquired:
        try:
            # 获取锁成功，检查是否已有缓存的响应
            cached_response = await redis_client.get(key)
            if cached_response:
                # 存在已缓存的响应，返回缓存结果
                return True, json.loads(cached_response)
            # 没有缓存响应，返回 False 表示可以继续处理
            return False, None
        finally:
            # 确保锁会被释放（即使处理失败）
            # 注意：这里不删除锁，而是让它自然过期
            # 避免删除锁时恰好另一个请求进入导致的问题
            pass
    else:
        # 获取锁失败，说明有并发请求正在处理
        # 等待一段时间后检查是否有缓存的响应
        for _ in range(10):  # 最多等待 5 秒
            await asyncio.sleep(0.5)
            cached_response = await redis_client.get(key)
            if cached_response:
                return True, json.loads(cached_response)
        
        # 等待超时，返回 False
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
