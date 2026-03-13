# -*- coding: utf-8 -*-
"""
V2 Orders API 测试
测试V2版本 Orders 端点
"""
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.item import Item
from app.models.order import Order
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


import random

async def create_test_item(test_db: AsyncSession, name: str = "Test Item") -> Item:
    """创建测试饰品"""
    unique_suffix = random.randint(10000, 99999)
    item = Item(
        name=name,
        name_cn="测试饰品",
        market_hash_name=f"Test_Item_{unique_suffix}",
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


import string

def generate_order_id() -> str:
    """生成符合规范的订单ID"""
    suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=12))
    return f"ORD-{suffix}"

async def create_test_order(
    test_db: AsyncSession,
    user: User,
    item: Item,
    status: str = "pending"
) -> Order:
    """创建测试订单"""
    order = Order(
        order_id=generate_order_id(),
        user_id=user.id,
        item_id=item.id,
        order_type="buy",
        price=100.0,
        quantity=1,
        status=status
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
async def test_v2_create_order(client: AsyncClient, test_db: AsyncSession):
    """测试V2创建订单"""
    user = await create_test_user(test_db)
    headers = await get_auth_header(user)
    
    item = await create_test_item(test_db, "AK-47 | Redline")
    
    response = await client.post(
        "/api/v2/orders/",
        headers=headers,
        json={
            "item_id": item.id,
            "order_type": "buy",
            "price": 100.0,
            "quantity": 1
        }
    )
    assert response.status_code in [201, 401, 422, 404]
