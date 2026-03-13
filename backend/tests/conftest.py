# -*- coding: utf-8 -*-
"""
测试配置
"""
import pytest
import asyncio
import os
import sys
from typing import AsyncGenerator
from unittest.mock import MagicMock, AsyncMock, patch
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.pool import StaticPool
import pytest_asyncio

# 设置环境变量在导入app之前
os.environ["DEBUG"] = "false"
os.environ["RATE_LIMIT_ENABLED"] = "true"
os.environ["TESTING"] = "true"
os.environ["SECRET_KEY"] = "test-secret-key-for-testing-only-change-in-production"
os.environ["ENCRYPTION_KEY"] = "test-encryption-key-for-testing-only"


# 测试数据库 URL
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


# 移除自定义 event_loop fixture，使用 pytest-asyncio 的默认行为
# 旧代码会导致与 pytest-asyncio 的兼容性问题


@pytest.fixture(scope="function")
def mock_redis():
    """Mock Redis 客户端"""
    mock = AsyncMock()
    # 模拟 Redis 基本操作
    mock.get = AsyncMock(return_value=None)
    mock.set = AsyncMock(return_value=True)
    mock.setex = AsyncMock(return_value=True)
    mock.delete = AsyncMock(return_value=1)
    mock.exists = AsyncMock(return_value=0)
    mock.expire = AsyncMock(return_value=1)
    mock.ttl = AsyncMock(return_value=60)
    mock.zadd = AsyncMock(return_value=1)
    mock.zremrangebyscore = AsyncMock(return_value=0)
    mock.zcard = AsyncMock(return_value=0)
    mock.zscore = AsyncMock(return_value=None)
    mock.sadd = AsyncMock(return_value=1)
    mock.smembers = AsyncMock(return_value=set())
    mock.srem = AsyncMock(return_value=1)
    mock.publish = AsyncMock(return_value=1)
    mock.ping = AsyncMock(return_value=True)
    mock.close = AsyncMock()
    # Lua脚本执行 - 返回一个列表 [can_login, attempts, message]
    mock.eval = AsyncMock(return_value=[1, 0, ""])
    mock.evalsha = AsyncMock(return_value=[1, 0, ""])
    return mock


@pytest.fixture(autouse=True)
def reset_global_cache():
    """重置全局缓存实例，防止测试间状态污染"""
    import app.services.cache as cache_module
    
    # 保存原始值
    original_cache = cache_module._cache
    original_initialized = cache_module._cache_initialized
    
    # 重置全局缓存
    cache_module._cache = None
    cache_module._cache_initialized = False
    
    yield
    
    # 清理 - 只在需要时清理
    try:
        if cache_module._cache is not None:
            # 尝试调用清理方法
            cache_module._cache._cache.clear()
    except Exception:
        pass
    
    # 恢复原始值
    cache_module._cache = original_cache
    cache_module._cache_initialized = original_initialized


@pytest_asyncio.fixture(autouse=True)
async def patch_redis(mock_redis):
    """自动 mock 所有 Redis 连接"""
    # 重置 RedisManager 单例状态
    from app.core import redis_manager as redis_mgr_module
    if hasattr(redis_mgr_module, 'redis_manager'):
        redis_mgr_module.redis_manager._redis_client = None
    
    async def mock_get_redis():
        return mock_redis
    
    # patch多个位置以确保所有导入路径都被mock
    with patch('redis.asyncio.Redis', return_value=mock_redis):
        with patch('redis.Redis', return_value=mock_redis):
            with patch('app.core.redis_manager.redis', mock_redis):
                with patch('app.core.session_manager.redis', mock_redis):
                    with patch('app.core.redis_manager.get_redis', mock_get_redis):
                        with patch('app.core.redis_manager.redis_manager.get_client', AsyncMock(return_value=mock_redis)):
                            yield mock_redis


@pytest_asyncio.fixture(scope="function")
async def test_db() -> AsyncGenerator[AsyncSession, None]:
    """测试数据库"""
    # 导入所有模型以确保它们被注册到Base.metadata
    from app.models import user, bot, inventory, item, monitor, notification, order
    
    from app.core.database import Base
    engine = create_async_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    async_session = AsyncSession(engine, expire_on_commit=False)
    
    yield async_session
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def client(test_db: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """测试客户端"""
    from app.main import app
    from app.core.database import get_db
    
    async def override_get_db():
        yield test_db
    
    app.dependency_overrides[get_db] = override_get_db
    
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", follow_redirects=True) as ac:
        yield ac
    
    app.dependency_overrides.clear()


@pytest_asyncio.fixture(scope="function")
async def auth_token(client: AsyncClient) -> str:
    """获取授权令牌 - 供需要认证的测试使用"""
    import random
    
    # 注册用户
    username = f"testuser_{random.randint(1000, 9999)}"
    
    await client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "password": "Testpass123",
            "email": f"{username}@example.com"
        }
    )
    
    # 登录
    response = await client.post(
        "/api/v1/auth/login",
        data={
            "username": username,
            "password": "Testpass123"
        }
    )
    
    if response.status_code == 200:
        return response.json()["access_token"]
    return None
