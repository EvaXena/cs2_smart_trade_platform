# -*- coding: utf-8 -*-
"""
Session 管理器 - 支持分布式 Session 和 Token 管理
"""
import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

import redis.asyncio as redis

from app.core.config import settings
from app.core.redis_manager import redis_manager, _build_redis_url

logger = logging.getLogger(__name__)


class SessionManager:
    """
    Session 管理器
    
    特性:
    - 基于 Redis 的分布式 Session
    - 支持 Token 自动续期
    - 安全的 Session 数据存储
    - 完整的 Session 生命周期管理
    """
    
    SESSION_PREFIX = "session:"
    TOKEN_PREFIX = "token:"
    USER_SESSIONS_PREFIX = "user_sessions:"
    
    def __init__(
        self,
        redis_url: str = None,
        session_ttl: int = 86400,        # 默认 24 小时
        token_ttl: int = 2592000,        # 默认 30 天
        refresh_ttl: int = 3600,         # 续期窗口 1 小时
        use_redis_manager: bool = True,  # 是否使用 RedisManager（统一连接）
    ):
        # 使用 RedisManager 的 URL 构建函数，支持密码
        if use_redis_manager:
            # 使用 RedisManager 的连接
            self._use_external_redis = True
            self.redis_url = None
        else:
            # 使用自定义 URL（支持密码）
            self._use_external_redis = False
            raw_url = redis_url or settings.REDIS_URL
            # 支持 REDIS_PASSWORD 环境变量
            self.redis_url = _build_redis_url(raw_url, settings.REDIS_PASSWORD)
        
        self.session_ttl = session_ttl
        self.token_ttl = token_ttl
        self.refresh_ttl = refresh_ttl
        self._redis: Optional[redis.Redis] = None
    
    async def _get_redis(self) -> redis.Redis:
        """获取 Redis 连接（优先使用 RedisManager 统一连接）"""
        if self._use_external_redis:
            # 使用 RedisManager 的统一连接
            return await redis_manager.get_client()
        
        # 使用自定义连接
        if self._redis is None:
            self._redis = redis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True
            )
        return self._redis
    
    async def close(self):
        """关闭 Redis 连接"""
        # 如果使用的是 RedisManager，不单独关闭（由 RedisManager 统一管理）
        if self._use_external_redis:
            self._redis = None
            return
        
        # 关闭自定义连接
        if self._redis:
            await self._redis.close()
            self._redis = None
    
    async def create_session(
        self,
        user_id: int,
        username: str,
        additional_data: Dict[str, Any] = None,
    ) -> Dict[str, str]:
        """
        创建新 Session
        
        Returns:
            {
                "session_id": "xxx",
                "access_token": "xxx",
                "refresh_token": "xxx",
                "expires_in": 86400
            }
        """
        r = await self._get_redis()
        
        # 生成唯一 ID
        session_id = str(uuid.uuid4())
        access_token = f"at_{uuid.uuid4().hex}"
        refresh_token = f"rt_{uuid.uuid4().hex}"
        
        # Session 数据
        session_data = {
            "user_id": str(user_id),
            "username": username,
            "created_at": datetime.utcnow().isoformat(),
            "last_accessed": datetime.utcnow().isoformat(),
            **(additional_data or {})
        }
        
        # 存储 Session
        session_key = f"{self.SESSION_PREFIX}{session_id}"
        await r.setex(session_key, self.session_ttl, json.dumps(session_data))
        
        # 存储 Token 映射
        token_key = f"{self.TOKEN_PREFIX}{access_token}"
        await r.setex(token_key, self.token_ttl, json.dumps({
            "session_id": session_id,
            "user_id": str(user_id),
            "refresh_token": refresh_token,
            "type": "access"
        }))
        
        refresh_token_key = f"{self.TOKEN_PREFIX}{refresh_token}"
        await r.setex(refresh_token_key, self.token_ttl, json.dumps({
            "session_id": session_id,
            "user_id": str(user_id),
            "access_token": access_token,
            "type": "refresh"
        }))
        
        # 记录用户的 Session（方便查找用户的所有会话）
        user_sessions_key = f"{self.USER_SESSIONS_PREFIX}{user_id}"
        await r.sadd(user_sessions_key, session_id)
        await r.expire(user_sessions_key, self.token_ttl)
        
        logger.info(f"Created session {session_id} for user {user_id}")
        
        return {
            "session_id": session_id,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_in": self.session_ttl,
            "token_expires_in": self.token_ttl
        }
    
    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """获取 Session 数据"""
        r = await self._get_redis()
        
        session_key = f"{self.SESSION_PREFIX}{session_id}"
        data = await r.get(session_key)
        
        if data:
            session_data = json.loads(data)
            # 更新最后访问时间
            session_data["last_accessed"] = datetime.utcnow().isoformat()
            await r.setex(session_key, self.session_ttl, json.dumps(session_data))
            return session_data
        
        return None
    
    async def get_session_by_token(self, access_token: str) -> Optional[Dict[str, Any]]:
        """通过 Token 获取 Session"""
        r = await self._get_redis()
        
        # 先通过 Token 找到 Session ID
        token_key = f"{self.TOKEN_PREFIX}{access_token}"
        token_data = await r.get(token_key)
        
        if not token_data:
            return None
        
        token_info = json.loads(token_data)
        session_id = token_info.get("session_id")
        
        if not session_id:
            return None
        
        # 获取 Session 数据
        return await self.get_session(session_id)
    
    async def delete_session(self, session_id: str) -> bool:
        """删除 Session"""
        r = await self._get_redis()
        
        # 获取 Session 数据以获取用户信息
        session = await self.get_session(session_id)
        
        # 删除 Session
        session_key = f"{self.SESSION_PREFIX}{session_id}"
        await r.delete(session_key)
        
        # 清理 Token
        if session:
            # 删除用户的会话记录
            user_id = session.get("user_id")
            if user_id:
                user_sessions_key = f"{self.USER_SESSIONS_PREFIX}{user_id}"
                await r.srem(user_sessions_key, session_id)
        
        logger.info(f"Deleted session {session_id}")
        return True
    
    async def delete_user_sessions(self, user_id: int) -> int:
        """删除用户的所有 Session（用于强制下线）"""
        r = await self._get_redis()
        
        user_sessions_key = f"{self.USER_SESSIONS_PREFIX}{user_id}"
        session_ids = await r.smembers(user_sessions_key)
        
        count = 0
        for session_id in session_ids:
            await self.delete_session(session_id)
            count += 1
        
        logger.info(f"Deleted {count} sessions for user {user_id}")
        return count
    
    async def refresh_session(self, refresh_token: str) -> Optional[Dict[str, str]]:
        """
        刷新 Session
        
        使用 Refresh Token 获取新的 Access Token
        """
        r = await self._get_redis()
        
        # 验证 Refresh Token
        token_key = f"{self.TOKEN_PREFIX}{refresh_token}"
        token_data = await r.get(token_key)
        
        if not token_data:
            return None
        
        token_info = json.loads(token_data)
        
        if token_info.get("type") != "refresh":
            return None
        
        session_id = token_info.get("session_id")
        user_id = token_info.get("user_id")
        
        # 获取完整 Session 数据
        session = await self.get_session(session_id)
        if not session:
            return None
        
        # 删除旧 Token
        old_access_token = token_info.get("access_token")
        if old_access_token:
            await r.delete(f"{self.TOKEN_PREFIX}{old_access_token}")
        await r.delete(token_key)
        
        # 创建新 Token
        return await self.create_session(
            user_id=int(user_id),
            username=session.get("username", ""),
            additional_data=session
        )
    
    async def verify_token(self, access_token: str) -> Optional[Dict[str, Any]]:
        """验证 Token 并返回关联的 Session"""
        r = await self._get_redis()
        
        # 直接通过 Token 查找 Session
        session_data = await self.get_session_by_token(access_token)
        
        if session_data:
            # 检查是否在续期窗口内
            last_accessed = datetime.fromisoformat(session_data["last_accessed"])
            time_since_access = (datetime.utcnow() - last_accessed).total_seconds()
            
            if time_since_access < self.refresh_ttl:
                # 续期
                token_key = f"{self.TOKEN_PREFIX}{access_token}"
                await r.expire(token_key, self.token_ttl)
        
        return session_data
    
    async def extend_session(self, session_id: str) -> bool:
        """延长 Session 过期时间"""
        r = await self._get_redis()
        
        session_key = f"{self.SESSION_PREFIX}{session_id}"
        return await r.expire(session_key, self.session_ttl)
    
    async def get_user_sessions(self, user_id: int) -> list:
        """获取用户的所有 Session"""
        r = await self._get_redis()
        
        user_sessions_key = f"{self.USER_SESSIONS_PREFIX}{user_id}"
        session_ids = await r.smembers(user_sessions_key)
        
        sessions = []
        for session_id in session_ids:
            session = await self.get_session(session_id)
            if session:
                sessions.append({
                    "session_id": session_id,
                    **session
                })
        
        return sessions
    
    async def cleanup_expired_sessions(self, user_id: int) -> int:
        """清理用户的过期 Session"""
        r = await self._get_redis()
        
        user_sessions_key = f"{self.USER_SESSIONS_PREFIX}{user_id}"
        session_ids = await r.smembers(user_sessions_key)
        
        count = 0
        for session_id in session_ids:
            session = await self.get_session(session_id)
            if not session:
                await r.srem(user_sessions_key, session_id)
                count += 1
        
        return count
    
    async def get_stats(self) -> Dict[str, Any]:
        """获取 Session 统计信息"""
        r = await self._get_redis()
        
        # 使用 scan_iter 替代 keys() 提高性能（keys() 会阻塞 Redis）
        session_count = 0
        token_count = 0
        
        async for _ in r.scan_iter(match=f"{self.SESSION_PREFIX}*", count=100):
            session_count += 1
        
        async for _ in r.scan_iter(match=f"{self.TOKEN_PREFIX}*", count=100):
            token_count += 1
        
        return {
            "active_sessions": session_count,
            "active_tokens": token_count,
            "session_ttl": self.session_ttl,
            "token_ttl": self.token_ttl
        }


# 全局 Session 管理器实例
_session_manager: Optional[SessionManager] = None


def get_session_manager() -> SessionManager:
    """获取全局 Session 管理器"""
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager


async def close_session_manager():
    """关闭全局 Session 管理器"""
    global _session_manager
    if _session_manager:
        await _session_manager.close()
        _session_manager = None
