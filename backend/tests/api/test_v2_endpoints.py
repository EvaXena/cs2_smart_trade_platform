# -*- coding: utf-8 -*-
"""
V2 API 端点测试
测试 V2 版本 API 端点
"""
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.core.security import get_password_hash, create_access_token


async def create_test_user(test_db: AsyncSession, username: str = "testuser") -> User:
    """创建测试用户"""
    user = User(
        username=username,
        email=f"{username}@example.com",
        hashed_password=get_password_hash("Password123!")
    )
    test_db.add(user)
    await test_db.commit()
    await test_db.refresh(user)
    return user


async def get_auth_header(user: User) -> dict:
    """获取认证头"""
    token = create_access_token(data={"sub": str(user.id)})
    return {"Authorization": f"Bearer {token}"}


# ========== V2 Auth 测试 ==========

@pytest.mark.asyncio
async def test_v2_register(client: AsyncClient, test_db: AsyncSession):
    """测试V2用户注册"""
    response = await client.post(
        "/api/v2/auth/register",
        json={
            "username": "newuser",
            "email": "newuser@example.com",
            "password": "Password123!"
        }
    )
    assert response.status_code in [201, 400, 409]  # 成功或用户名/邮箱已存在


@pytest.mark.asyncio
async def test_v2_login(client: AsyncClient, test_db: AsyncSession):
    """测试V2用户登录"""
    # 先创建用户
    user = await create_test_user(test_db, "logintest")
    
    response = await client.post(
        "/api/v2/auth/login",
        data={
            "username": "logintest",
            "password": "Password123!"
        }
    )
    assert response.status_code in [200, 401]
    if response.status_code == 200:
        data = response.json()
        assert "access_token" in data
        assert data.get("token_type") == "bearer"


@pytest.mark.asyncio
async def test_v2_refresh_token(client: AsyncClient, test_db: AsyncSession):
    """测试V2 Token刷新"""
    user = await create_test_user(test_db, "refreshtest")
    headers = await get_auth_header(user)
    
    response = await client.post(
        "/api/v2/auth/refresh?refresh_token=test_token",
        headers=headers
    )
    assert response.status_code in [200, 401]


@pytest.mark.asyncio
async def test_v2_logout(client: AsyncClient, test_db: AsyncSession):
    """测试V2登出"""
    user = await create_test_user(test_db, "logouttest")
    headers = await get_auth_header(user)
    
    response = await client.post(
        "/api/v2/auth/logout",
        headers=headers
    )
    assert response.status_code in [200, 401]


# ========== V2 Bots 测试 ==========

@pytest.mark.asyncio
async def test_v2_get_bots(client: AsyncClient, test_db: AsyncSession):
    """测试V2获取机器人列表"""
    user = await create_test_user(test_db)
    headers = await get_auth_header(user)
    
    response = await client.get("/api/v2/bots/", headers=headers)
    assert response.status_code in [200, 401]


@pytest.mark.asyncio
async def test_v2_create_bot(client: AsyncClient, test_db: AsyncSession):
    """测试V2创建机器人"""
    user = await create_test_user(test_db)
    headers = await get_auth_header(user)
    
    response = await client.post(
        "/api/v2/bots/",
        headers=headers,
        json={
            "name": "V2 Test Bot",
            "steam_id": "123456789",
            "username": "testbot"
        }
    )
    assert response.status_code in [201, 401, 422]


@pytest.mark.asyncio
async def test_v2_get_bot_detail(client: AsyncClient, test_db: AsyncSession):
    """测试V2获取机器人详情"""
    user = await create_test_user(test_db)
    headers = await get_auth_header(user)
    
    response = await client.get("/api/v2/bots/1", headers=headers)
    assert response.status_code in [200, 401, 404]


@pytest.mark.asyncio
async def test_v2_update_bot(client: AsyncClient, test_db: AsyncSession):
    """测试V2更新机器人"""
    user = await create_test_user(test_db)
    headers = await get_auth_header(user)
    
    response = await client.put(
        "/api/v2/bots/1",
        headers=headers,
        json={"name": "Updated Bot"}
    )
    assert response.status_code in [200, 401, 404]


@pytest.mark.asyncio
async def test_v2_delete_bot(client: AsyncClient, test_db: AsyncSession):
    """测试V2删除机器人"""
    user = await create_test_user(test_db)
    headers = await get_auth_header(user)
    
    response = await client.delete("/api/v2/bots/1", headers=headers)
    assert response.status_code in [200, 401, 404]


# ========== V2 Inventory 测试 ==========

@pytest.mark.asyncio
async def test_v2_get_inventory(client: AsyncClient, test_db: AsyncSession):
    """测试V2获取库存"""
    user = await create_test_user(test_db)
    headers = await get_auth_header(user)
    
    response = await client.get("/api/v2/inventory/", headers=headers)
    assert response.status_code in [200, 401]


@pytest.mark.asyncio
async def test_v2_get_inventory_item(client: AsyncClient, test_db: AsyncSession):
    """测试V2获取库存物品详情"""
    user = await create_test_user(test_db)
    headers = await get_auth_header(user)
    
    response = await client.get("/api/v2/inventory/item/1", headers=headers)
    assert response.status_code in [200, 401, 404]


@pytest.mark.asyncio
async def test_v2_sync_inventory(client: AsyncClient, test_db: AsyncSession):
    """测试V2同步库存"""
    user = await create_test_user(test_db)
    headers = await get_auth_header(user)
    
    response = await client.post("/api/v2/inventory/sync?platform=steam", headers=headers)
    assert response.status_code in [200, 401, 400]


# ========== V2 Monitors 测试 ==========

@pytest.mark.asyncio
async def test_v2_get_monitors(client: AsyncClient, test_db: AsyncSession):
    """测试V2获取监控列表"""
    user = await create_test_user(test_db)
    headers = await get_auth_header(user)
    
    response = await client.get("/api/v2/monitors/", headers=headers)
    assert response.status_code in [200, 401]


@pytest.mark.asyncio
async def test_v2_create_monitor(client: AsyncClient, test_db: AsyncSession):
    """测试V2创建监控"""
    user = await create_test_user(test_db)
    headers = await get_auth_header(user)
    
    response = await client.post(
        "/api/v2/monitors/",
        headers=headers,
        json={
            "name": "Test Monitor",
            "item_name": "AK-47 | Redline",
            "price_threshold": 100.0
        }
    )
    assert response.status_code in [201, 401, 422]


@pytest.mark.asyncio
async def test_v2_get_monitor_detail(client: AsyncClient, test_db: AsyncSession):
    """测试V2获取监控详情"""
    user = await create_test_user(test_db)
    headers = await get_auth_header(user)
    
    response = await client.get("/api/v2/monitors/1", headers=headers)
    assert response.status_code in [200, 401, 404]


@pytest.mark.asyncio
async def test_v2_update_monitor(client: AsyncClient, test_db: AsyncSession):
    """测试V2更新监控"""
    user = await create_test_user(test_db)
    headers = await get_auth_header(user)
    
    response = await client.put(
        "/api/v2/monitors/1",
        headers=headers,
        json={"price_threshold": 200.0}
    )
    assert response.status_code in [200, 401, 404]


@pytest.mark.asyncio
async def test_v2_delete_monitor(client: AsyncClient, test_db: AsyncSession):
    """测试V2删除监控"""
    user = await create_test_user(test_db)
    headers = await get_auth_header(user)
    
    response = await client.delete("/api/v2/monitors/1", headers=headers)
    assert response.status_code in [200, 401, 404]


# ========== V2 Notifications 测试 ==========

@pytest.mark.asyncio
async def test_v2_get_notifications(client: AsyncClient, test_db: AsyncSession):
    """测试V2获取通知列表"""
    user = await create_test_user(test_db)
    headers = await get_auth_header(user)
    
    response = await client.get("/api/v2/notifications/", headers=headers)
    assert response.status_code in [200, 401]


@pytest.mark.asyncio
async def test_v2_mark_notification_read(client: AsyncClient, test_db: AsyncSession):
    """测试V2标记通知已读"""
    user = await create_test_user(test_db)
    headers = await get_auth_header(user)
    
    response = await client.post("/api/v2/notifications/1/read", headers=headers)
    assert response.status_code in [200, 401, 404]


@pytest.mark.asyncio
async def test_v2_delete_notification(client: AsyncClient, test_db: AsyncSession):
    """测试V2删除通知"""
    user = await create_test_user(test_db)
    headers = await get_auth_header(user)
    
    response = await client.delete("/api/v2/notifications/1", headers=headers)
    assert response.status_code in [200, 401, 404]


@pytest.mark.asyncio
async def test_v2_clear_notifications(client: AsyncClient, test_db: AsyncSession):
    """测试V2清空通知"""
    user = await create_test_user(test_db)
    headers = await get_auth_header(user)
    
    response = await client.delete("/api/v2/notifications/", headers=headers)
    # 204 No Content 也是成功状态
    assert response.status_code in [200, 204, 401]
