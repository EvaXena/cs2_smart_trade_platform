# -*- coding: utf-8 -*-
"""
测试辅助函数
为V2 API测试提供公共的辅助函数
"""
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.item import Item
from app.models.bot import Bot
from app.models.inventory import Inventory
from app.models.order import Order
from app.models.monitor import MonitorTask
from app.models.notification import Notification
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


async def create_test_item(test_db: AsyncSession, name: str = "Test Item") -> Item:
    """创建测试饰品"""
    item = Item(
        name=name,
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


async def create_test_bot(test_db: AsyncSession, user: User, name: str = "Test Bot") -> Bot:
    """创建测试机器人"""
    bot = Bot(
        name=name,
        steam_id="123456789",
        username="testbot",
        status="online",
        owner_id=user.id
    )
    test_db.add(bot)
    await test_db.commit()
    await test_db.refresh(bot)
    return bot


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
        price=100.0,
        status=status
    )
    test_db.add(inventory_item)
    await test_db.commit()
    await test_db.refresh(inventory_item)
    return inventory_item


import random
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


async def create_test_monitor(
    test_db: AsyncSession,
    user: User,
    item_name: str = "AK-47 | Redline"
) -> MonitorTask:
    """创建测试监控"""
    monitor = MonitorTask(
        user_id=user.id,
        name="Test Monitor",
        item_name=item_name,
        price_threshold=100.0,
        is_active=True
    )
    test_db.add(monitor)
    await test_db.commit()
    await test_db.refresh(monitor)
    return monitor


async def create_test_notification(
    test_db: AsyncSession,
    user: User,
    notification_type: str = "price_alert"
) -> Notification:
    """创建测试通知"""
    notification = Notification(
        user_id=user.id,
        type=notification_type,
        title="Test Notification",
        content="This is a test notification",
        is_read=False
    )
    test_db.add(notification)
    await test_db.commit()
    await test_db.refresh(notification)
    return notification


async def get_auth_header(user: User) -> dict:
    """获取认证头"""
    token = create_access_token(data={"sub": str(user.id)})
    return {"Authorization": f"Bearer {token}"}
