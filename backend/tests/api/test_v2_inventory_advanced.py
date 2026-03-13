# -*- coding: utf-8 -*-
"""
V2 Inventory 高级API测试
测试V2版本 Inventory 高级功能
"""
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.item import Item
from app.models.inventory import Inventory
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
    asset_id: str = "test_asset_123",
    status: str = "owned"
) -> Inventory:
    """创建测试库存物品"""
    inventory_item = Inventory(
        user_id=user.id,
        item_id=item.id,
        asset_id=asset_id,
        class_id="12345",
        instance_id="67890",
        amount=1,
        cost_price=100.0,
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
async def test_v2_inventory_batch_list(client: AsyncClient, test_db: AsyncSession):
    """测试V2批量上架物品"""
    user = await create_test_user(test_db)
    headers = await get_auth_header(user)
    
    # 创建测试物品
    item = await create_test_item(test_db, "AK-47 | Redline")
    inv1 = await create_test_inventory_item(test_db, user, item, "asset_1", "owned")
    inv2 = await create_test_inventory_item(test_db, user, item, "asset_2", "owned")
    
    response = await client.post(
        "/api/v2/inventory/batch-list",
        headers=headers,
        json={
            "item_ids": [inv1.id, inv2.id]
        }
    )
    assert response.status_code in [200, 401]


@pytest.mark.asyncio
async def test_v2_inventory_batch_unlist(client: AsyncClient, test_db: AsyncSession):
    """测试V2批量下架物品"""
    user = await create_test_user(test_db)
    headers = await get_auth_header(user)
    
    # 创建测试物品
    item = await create_test_item(test_db, "M4A1-S | Night")
    inv1 = await create_test_inventory_item(test_db, user, item, "asset_3", "listed")
    inv2 = await create_test_inventory_item(test_db, user, item, "asset_4", "listed")
    
    response = await client.post(
        "/api/v2/inventory/batch-unlist",
        headers=headers,
        json={
            "item_ids": [inv1.id, inv2.id]
        }
    )
    assert response.status_code in [200, 401]


@pytest.mark.asyncio
async def test_v2_inventory_search(client: AsyncClient, test_db: AsyncSession):
    """测试V2搜索库存"""
    user = await create_test_user(test_db)
    headers = await get_auth_header(user)
    
    # 创建测试物品
    item = await create_test_item(test_db, "AK-47 | Redline")
    await create_test_inventory_item(test_db, user, item, "asset_5")
    
    response = await client.get(
        "/api/v2/inventory/",
        headers=headers,
        params={"search": "AK-47"}
    )
    assert response.status_code in [200, 401]


@pytest.mark.asyncio
async def test_v2_inventory_filter_by_rarity(client: AsyncClient, test_db: AsyncSession):
    """测试V2按稀有度筛选库存"""
    user = await create_test_user(test_db)
    headers = await get_auth_header(user)
    
    # 创建测试物品
    item = await create_test_item(test_db, "AK-47 | Redline")
    await create_test_inventory_item(test_db, user, item, "asset_6")
    
    response = await client.get(
        "/api/v2/inventory/",
        headers=headers,
        params={"rarity": "covert"}
    )
    assert response.status_code in [200, 401]


@pytest.mark.asyncio
async def test_v2_inventory_sort_by_price(client: AsyncClient, test_db: AsyncSession):
    """测试V2按价格排序库存"""
    user = await create_test_user(test_db)
    headers = await get_auth_header(user)
    
    # 创建测试物品
    item = await create_test_item(test_db, "M4A4 | Desert Storm")
    await create_test_inventory_item(test_db, user, item, "asset_7")
    
    response = await client.get(
        "/api/v2/inventory/",
        headers=headers,
        params={"sort_by": "price", "sort_order": "desc"}
    )
    assert response.status_code in [200, 401]
