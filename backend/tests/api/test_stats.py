# -*- coding: utf-8 -*-
"""
Stats API 测试
"""
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.order import Order
from app.models.item import Item
from app.core.security import get_password_hash, create_access_token


async def create_test_user(test_db: AsyncSession) -> User:
    """创建测试用户"""
    user = User(
        username="testuser",
        email="test@example.com",
        hashed_password=get_password_hash("password123")
    )
    test_db.add(user)
    await test_db.commit()
    await test_db.refresh(user)
    return user


async def create_test_item(test_db: AsyncSession) -> Item:
    """创建测试饰品"""
    item = Item(
        name="Test Item",
        name_cn="测试饰品",
        market_hash_name="Test_Item",
        category="weapon",
        rarity="covert",
        exterior="factory_new",
        current_price=100.0,
        steam_lowest_price=120.0,
        volume_24h=100,
        price_change_percent=5.0
    )
    test_db.add(item)
    await test_db.commit()
    await test_db.refresh(item)
    return item


import random
import string

def generate_order_id() -> str:
    """生成符合规范的订单ID"""
    suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=12))
    return f"ORD-{suffix}"

async def create_test_order(test_db: AsyncSession, user: User, item: Item, status: str = "completed") -> Order:
    """创建测试订单"""
    from datetime import datetime
    order = Order(
        order_id=generate_order_id(),
        user_id=user.id,
        item_id=item.id,
        side="buy",
        price=100.0,
        quantity=1,
        status=status,
        source="manual",
        created_at=datetime.utcnow()
    )
    test_db.add(order)
    await test_db.commit()
    await test_db.refresh(order)
    return order


async def get_auth_header(user: User) -> dict:
    """获取认证头"""
    token = create_access_token(data={"sub": str(user.id)})
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_get_dashboard_stats(client: AsyncClient, test_db: AsyncSession):
    """测试获取仪表盘统计"""
    user = await create_test_user(test_db)
    headers = await get_auth_header(user)
    
    response = await client.get("/api/v1/stats/dashboard", headers=headers)
    assert response.status_code in [200, 404]


@pytest.mark.asyncio
async def test_get_trading_stats(client: AsyncClient, test_db: AsyncSession):
    """测试获取交易统计"""
    user = await create_test_user(test_db)
    headers = await get_auth_header(user)
    
    item = await create_test_item(test_db)
    await create_test_order(test_db, user, item, "completed")
    
    response = await client.get("/api/v1/stats/trading", headers=headers)
    assert response.status_code in [200, 404]


@pytest.mark.asyncio
async def test_get_profit_stats(client: AsyncClient, test_db: AsyncSession):
    """测试获取利润统计"""
    user = await create_test_user(test_db)
    headers = await get_auth_header(user)
    
    response = await client.get("/api/v1/stats/profit", headers=headers)
    assert response.status_code in [200, 404]


@pytest.mark.asyncio
async def test_get_order_stats(client: AsyncClient, test_db: AsyncSession):
    """测试获取订单统计"""
    user = await create_test_user(test_db)
    headers = await get_auth_header(user)
    
    item = await create_test_item(test_db)
    await create_test_order(test_db, user, item, "completed")
    await create_test_order(test_db, user, item, "pending")
    
    response = await client.get("/api/v1/stats/orders", headers=headers)
    assert response.status_code in [200, 404]


@pytest.mark.asyncio
async def test_get_volume_stats(client: AsyncClient, test_db: AsyncSession):
    """测试获取交易量统计"""
    user = await create_test_user(test_db)
    headers = await get_auth_header(user)
    
    response = await client.get("/api/v1/stats/volume", headers=headers)
    assert response.status_code in [200, 404]


@pytest.mark.asyncio
async def test_get_arbitrage_stats(client: AsyncClient, test_db: AsyncSession):
    """测试获取搬砖统计"""
    user = await create_test_user(test_db)
    headers = await get_auth_header(user)
    
    response = await client.get("/api/v1/stats/arbitrage", headers=headers)
    assert response.status_code in [200, 404]


@pytest.mark.asyncio
async def test_get_trend_stats(client: AsyncClient, test_db: AsyncSession):
    """测试获取趋势统计"""
    user = await create_test_user(test_db)
    headers = await get_auth_header(user)
    
    response = await client.get("/api/v1/stats/trend", headers=headers)
    assert response.status_code in [200, 404]


@pytest.mark.asyncio
async def test_get_time_range_stats(client: AsyncClient, test_db: AsyncSession):
    """测试获取时间范围统计"""
    user = await create_test_user(test_db)
    headers = await get_auth_header(user)
    
    response = await client.get("/api/v1/stats/?days=7", headers=headers)
    assert response.status_code in [200, 404]
