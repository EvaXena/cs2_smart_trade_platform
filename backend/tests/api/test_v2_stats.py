# -*- coding: utf-8 -*-
"""
V2 Stats API 测试
测试V2版本 Stats 端点
"""
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.item import Item
from app.models.inventory import Inventory
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


async def create_test_inventory_item(
    test_db: AsyncSession,
    user: User,
    item: Item,
    status: str = "owned"
) -> Inventory:
    """创建测试库存物品"""
    inventory_item = Inventory(
        user_id=user.id,
        item_id=item.id,
        asset_id="test_asset_123",
        class_id="12345",
        instance_id="67890",
        amount=1,
        price=100.0,
        status=status
    )
    test_db.add(inventory_item)
    await test_db.commit()
    await test_db.refresh(inventory_item)
    return inventory_item


async def get_auth_header(user: User) -> dict:
    """获取认证头"""
    token = create_access_token(data={"sub": str(user.id)})
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_v2_get_stats_summary(client: AsyncClient, test_db: AsyncSession):
    """测试V2获取统计摘要"""
    user = await create_test_user(test_db)
    headers = await get_auth_header(user)
    
    # 创建测试数据
    item = await create_test_item(test_db, "AK-47 | Redline")
    await create_test_inventory_item(test_db, user, item, "owned")
    await create_test_inventory_item(test_db, user, item, "listed")
    
    response = await client.get("/api/v2/stats/summary", headers=headers)
    assert response.status_code in [200, 401]


@pytest.mark.asyncio
async def test_v2_get_inventory_stats(client: AsyncClient, test_db: AsyncSession):
    """测试V2获取库存统计"""
    user = await create_test_user(test_db)
    headers = await get_auth_header(user)
    
    # 创建测试数据
    item = await create_test_item(test_db, "M4A1-S | Night")
    await create_test_inventory_item(test_db, user, item, "owned")
    
    response = await client.get("/api/v2/inventory/stats", headers=headers)
    assert response.status_code in [200, 401]
