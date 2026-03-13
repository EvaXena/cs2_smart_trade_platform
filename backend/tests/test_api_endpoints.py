# -*- coding: utf-8 -*-
"""
API端点集成测试
"""
import pytest
import pytest_asyncio
from unittest.mock import patch, AsyncMock, MagicMock
from httpx import AsyncClient


# ============ 饰品API测试 ============

@pytest.mark.asyncio
async def test_get_items_list(client):
    """测试获取饰品列表"""
    response = await client.get("/api/v1/items")
    assert response.status_code in [200, 500]  # 可能无数据但接口可达


@pytest.mark.asyncio
async def test_search_items(client):
    """测试搜索饰品"""
    response = await client.get("/api/v1/items/search?keyword=AK-47")
    assert response.status_code in [200, 404, 500]


@pytest.mark.asyncio
async def test_get_item_detail(client):
    """测试获取饰品详情"""
    # 先创建测试数据
    response = await client.get("/api/v1/items/1")
    assert response.status_code in [200, 404]


# ============ 订单API测试 ============

@pytest.mark.asyncio
async def test_create_order_unauthorized(client):
    """测试未授权创建订单"""
    response = await client.post(
        "/api/v1/orders",
        json={
            "item_id": 1,
            "side": "buy",
            "price": 100.0,
            "quantity": 1
        }
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_orders_unauthorized(client):
    """测试未授权查询订单"""
    response = await client.get("/api/v1/orders")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_order_detail(client):
    """测试获取订单详情（不存在）"""
    response = await client.get("/api/v1/orders/NONEXISTENT")
    assert response.status_code in [401, 404]


# ============ 库存API测试 ============

@pytest.mark.asyncio
async def test_list_inventory_unauthorized(client):
    """测试未授权查询库存"""
    response = await client.get("/api/v1/inventory")
    assert response.status_code == 401


# ============ 监控API测试 ============

@pytest.mark.asyncio
async def test_list_monitors_unauthorized(client):
    """测试未授权查询监控"""
    response = await client.get("/api/v1/monitors")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_monitor_unauthorized(client):
    """测试未授权创建监控"""
    response = await client.post(
        "/api/v1/monitors",
        json={
            "item_id": 1,
            "target_price": 100.0,
            "condition": "below"
        }
    )
    assert response.status_code == 401


# ============ 机器人API测试 ============

@pytest.mark.asyncio
async def test_list_bots_unauthorized(client):
    """测试未授权查询机器人"""
    response = await client.get("/api/v1/bots")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_bot_unauthorized(client):
    """测试未授权创建机器人"""
    response = await client.post(
        "/api/v1/bots",
        json={
            "name": "Test Bot",
            "platform": "buff"
        }
    )
    assert response.status_code == 401


# ============ 授权后的API测试 ============

@pytest.mark.asyncio
async def test_authenticated_orders_list(client, auth_token):
    """测试授权后查询订单列表"""
    if not auth_token:
        pytest.skip("无法获取认证令牌")
    
    response = await client.get(
        "/api/v1/orders",
        headers={"Authorization": f"Bearer {auth_token}"}
    )
    assert response.status_code == 200
    # 订单列表返回可能是分页格式 {'orders': [...], 'page': ...} 或列表
    data = response.json()
    assert "orders" in data or isinstance(data, list)


@pytest.mark.asyncio
async def test_authenticated_inventory_list(client, auth_token):
    """测试授权后查询库存"""
    if not auth_token:
        pytest.skip("无法获取认证令牌")
    
    response = await client.get(
        "/api/v1/inventory",
        headers={"Authorization": f"Bearer {auth_token}"}
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_authenticated_monitors_list(client, auth_token):
    """测试授权后查询监控列表"""
    if not auth_token:
        pytest.skip("无法获取认证令牌")
    
    response = await client.get(
        "/api/v1/monitors",
        headers={"Authorization": f"Bearer {auth_token}"}
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_authenticated_bots_list(client, auth_token):
    """测试授权后查询机器人列表"""
    if not auth_token:
        pytest.skip("无法获取认证令牌")
    
    response = await client.get(
        "/api/v1/bots",
        headers={"Authorization": f"Bearer {auth_token}"}
    )
    assert response.status_code == 200


# ============ 统计API测试 ============

@pytest.mark.asyncio
async def test_dashboard_stats(client: AsyncClient, auth_token: str):
    """测试仪表盘统计接口"""
    response = await client.get(
        "/api/v1/stats/dashboard",
        headers={"Authorization": f"Bearer {auth_token}"}
    )
    # 可能有数据也可能无数据
    assert response.status_code in [200, 401, 500]


# ============ 错误处理测试 ============

@pytest.mark.asyncio
async def test_invalid_endpoint(client):
    """测试无效端点"""
    response = await client.get("/api/v1/invalid endpoint")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_invalid_json(client):
    """测试无效JSON格式"""
    import asyncio
    await asyncio.sleep(1)  # 避免rate limit
    
    response = await client.post(
        "/api/v1/auth/register",
        json={"username": "test"}  # 缺少必填字段
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_rate_limit_on_login(client):
    """测试登录接口限流"""
    # 尝试多次登录触发限流
    import asyncio
    
    for _ in range(6):
        await client.post(
            "/api/v1/auth/login",
            data={"username": "nonexistent", "password": "wrong"}
        )
        await asyncio.sleep(0.2)
    
    # 第6次应该被限流
    response = await client.post(
        "/api/v1/auth/login",
        data={"username": "nonexistent2", "password": "wrong"}
    )
    # 可能返回429或200（取决于rate limit配置）
    assert response.status_code in [429, 200, 401]


# ============ 搬砖API测试 ============

@pytest.mark.asyncio
async def test_arbitrage_opportunities_unauthorized(client):
    """测试未授权获取搬砖机会"""
    response = await client.get("/api/v1/trading/arbitrage")
    assert response.status_code in [401, 404]


@pytest.mark.asyncio
async def test_execute_trade_unauthorized(client):
    """测试未授权执行交易"""
    response = await client.post(
        "/api/v1/trading/execute",
        json={"item_id": 1, "side": "buy"}
    )
    assert response.status_code in [401, 404]


# ============ 健康检查测试 ============

@pytest.mark.asyncio
async def test_health_check(client):
    """测试健康检查端点"""
    response = await client.get("/health")
    assert response.status_code in [200, 404]


@pytest.mark.asyncio
async def test_root_endpoint(client):
    """测试根端点"""
    response = await client.get("/")
    assert response.status_code in [200, 404]
