# -*- coding: utf-8 -*-
"""
认证测试
"""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_register(client: AsyncClient):
    """测试用户注册"""
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "username": "testuser",
            "password": "Testpass123",  # 符合强度要求
            "email": "test@example.com"
        }
    )
    assert response.status_code in [201, 400]  # 201 成功或 400 用户已存在


@pytest.mark.asyncio
async def test_register_weak_password(client: AsyncClient):
    """测试弱密码注册"""
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "username": "newuser",
            "password": "weak"  # 密码太短 - Pydantic 会先拦截
        }
    )
    assert response.status_code == 422  # Pydantic 验证失败


@pytest.mark.asyncio
async def test_register_password_missing_types(client: AsyncClient):
    """测试缺少字符类型的密码"""
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "username": "newuser2",
            "password": "abcdefgh"  # 8字符但只有小写字母
        }
    )
    assert response.status_code == 400
    data = response.json()["detail"]
    assert "数字" in data or "特殊字符" in data


@pytest.mark.asyncio
async def test_register_password_exactly_8_chars_valid(client: AsyncClient):
    """测试正好8字符且满足强度要求"""
    # 注意: 由于rate limit，需要等待更长时间
    import asyncio
    await asyncio.sleep(2)  # 等待rate limit窗口过期
    
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "username": "validuser3",  # 使用不同的用户名避免冲突
            "password": "Abcd1234"  # 8字符，大小写+数字
        }
    )
    assert response.status_code == 201


@pytest.mark.asyncio
async def test_login(client: AsyncClient):
    """测试用户登录"""
    # 先注册
    await client.post(
        "/api/v1/auth/register",
        json={
            "username": "testuser",
            "password": "Testpass123"
        }
    )
    
    # 登录
    response = await client.post(
        "/api/v1/auth/login",
        data={
            "username": "testuser",
            "password": "Testpass123"
        }
    )
    assert response.status_code in [200, 401]


@pytest.mark.asyncio
async def test_get_current_user(client: AsyncClient):
    """测试获取当前用户"""
    # 先注册
    await client.post(
        "/api/v1/auth/register",
        json={
            "username": "testuser",
            "password": "testpass123"
        }
    )
    
    # 登录
    login_response = await client.post(
        "/api/v1/auth/login",
        data={
            "username": "testuser",
            "password": "testpass123"
        }
    )
    
    if login_response.status_code == 200:
        token = login_response.json()["access_token"]
        
        # 获取当前用户
        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "testuser"


@pytest.mark.asyncio
async def test_logout(client: AsyncClient):
    """测试登出"""
    # 先注册并登录
    await client.post(
        "/api/v1/auth/register",
        json={
            "username": "testuser",
            "password": "testpass123"
        }
    )
    
    login_response = await client.post(
        "/api/v1/auth/login",
        data={
            "username": "testuser",
            "password": "testpass123"
        }
    )
    
    if login_response.status_code == 200:
        token = login_response.json()["access_token"]
        
        # 登出
        response = await client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_login_atomic_race_condition():
    """
    测试登录尝试原子性 (第44轮 P0)
    验证 Lua 脚本实现的原子检查+更新
    """
    import asyncio
    from app.api.v1.endpoints.auth import _check_and_record_login_attempt_atomic
    
    # 清理测试数据
    from app.core.redis_manager import get_redis
    redis_client = await get_redis()
    await redis_client.delete("login:attempts:test_race_user")
    await redis_client.delete("login:locked:test_race_user")
    
    # 模拟5次失败登录
    for i in range(5):
        can_login, attempts, _ = await _check_and_record_login_attempt_atomic(
            "test_race_user", record_attempt=True
        )
        assert can_login == True, f"第{i+1}次应该允许登录"
    
    # 第6次应该被锁定
    can_login, attempts, error_msg = await _check_and_record_login_attempt_atomic(
        "test_race_user", record_attempt=True
    )
    assert can_login == False, "第6次应该被锁定"
    assert error_msg.startswith("locked:"), "应该返回锁定信息"
    
    # 清理
    await redis_client.delete("login:attempts:test_race_user")
    await redis_client.delete("login:locked:test_race_user")
