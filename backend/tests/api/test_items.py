# -*- coding: utf-8 -*-
"""
Items API 测试
"""
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
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


async def get_auth_header(user: User) -> dict:
    """获取认证头"""
    token = create_access_token(data={"sub": str(user.id)})
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_get_items_empty(client: AsyncClient, test_db: AsyncSession):
    """测试获取饰品列表（空）"""
    user = await create_test_user(test_db)
    headers = await get_auth_header(user)
    
    response = await client.get("/api/v1/items/", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total" in data


@pytest.mark.asyncio
async def test_get_items_with_pagination(client: AsyncClient, test_db: AsyncSession):
    """测试获取饰品列表（分页）"""
    user = await create_test_user(test_db)
    headers = await get_auth_header(user)
    
    # 创建测试饰品
    for i in range(25):
        await create_test_item(test_db, f"Test Item {i}")
    
    # 测试分页
    response = await client.get("/api/v1/items/?page=1&page_size=10", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 10
    assert data["total"] == 25
    assert data["page"] == 1
    assert data["page_size"] == 10


@pytest.mark.asyncio
async def test_get_items_with_filters(client: AsyncClient, test_db: AsyncSession):
    """测试获取饰品列表（过滤）"""
    user = await create_test_user(test_db)
    headers = await get_auth_header(user)
    
    # 创建测试饰品
    item1 = await create_test_item(test_db, "AK-47 | Redline")
    item2 = await create_test_item(test_db, "M4A1-S | Night")
    
    # 测试分类过滤
    response = await client.get("/api/v1/items/?category=weapon", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 2


@pytest.mark.asyncio
async def test_get_item_by_id(client: AsyncClient, test_db: AsyncSession):
    """测试获取饰品详情"""
    user = await create_test_user(test_db)
    headers = await get_auth_header(user)
    
    item = await create_test_item(test_db)
    
    response = await client.get(f"/api/v1/items/{item.id}", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == item.name
    assert data["current_price"] == item.current_price


@pytest.mark.asyncio
async def test_get_item_not_found(client: AsyncClient, test_db: AsyncSession):
    """测试获取不存在的饰品"""
    user = await create_test_user(test_db)
    headers = await get_auth_header(user)
    
    response = await client.get("/api/v1/items/99999", headers=headers)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_search_items(client: AsyncClient, test_db: AsyncSession):
    """测试搜索饰品"""
    user = await create_test_user(test_db)
    headers = await get_auth_header(user)
    
    # 创建测试饰品
    await create_test_item(test_db, "AK-47 | Redline")
    await create_test_item(test_db, "M4A1-S | Night")
    
    response = await client.get("/api/v1/items/search?keyword=AK-47", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert "items" in data


@pytest.mark.asyncio
async def test_get_price_history(client: AsyncClient, test_db: AsyncSession):
    """测试获取价格历史"""
    user = await create_test_user(test_db)
    headers = await get_auth_header(user)
    
    item = await create_test_item(test_db)
    
    response = await client.get(f"/api/v1/items/{item.id}/price?days=7", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    assert data["item_id"] == item.id


@pytest.mark.asyncio
async def test_get_price_overview(client: AsyncClient, test_db: AsyncSession):
    """测试获取价格概览"""
    user = await create_test_user(test_db)
    headers = await get_auth_header(user)
    
    item = await create_test_item(test_db)
    
    response = await client.get(f"/api/v1/items/{item.id}/overview", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert "buff_price" in data
    assert "steam_price" in data
    assert "arbitrage_profit" in data
