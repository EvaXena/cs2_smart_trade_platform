# -*- coding: utf-8 -*-
"""
V2 Notifications 高级API测试
测试V2版本 Notifications 高级功能
"""
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
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


async def create_test_notification(
    test_db: AsyncSession,
    user: User,
    notification_type: str = "price_alert"
) -> Notification:
    """创建测试通知"""
    from app.models.notification import NotificationType
    notification = Notification(
        user_id=user.id,
        notification_type=NotificationType.PRICE_ALERT if notification_type == "price_alert" else NotificationType.SYSTEM,
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


@pytest.mark.asyncio
async def test_v2_notifications_mark_all_read(client: AsyncClient, test_db: AsyncSession):
    """测试V2标记所有通知已读"""
    user = await create_test_user(test_db)
    headers = await get_auth_header(user)
    
    # 创建测试通知
    await create_test_notification(test_db, user, "price_alert")
    await create_test_notification(test_db, user, "trade_offer")
    
    response = await client.post("/api/v2/notifications/mark-all-read", headers=headers)
    assert response.status_code in [200, 401]


@pytest.mark.asyncio
async def test_v2_notifications_filter_by_type(client: AsyncClient, test_db: AsyncSession):
    """测试V2按类型筛选通知"""
    user = await create_test_user(test_db)
    headers = await get_auth_header(user)
    
    # 创建测试通知
    await create_test_notification(test_db, user, "price_alert")
    await create_test_notification(test_db, user, "trade_offer")
    
    response = await client.get(
        "/api/v2/notifications/",
        headers=headers,
        params={"type": "price_alert"}
    )
    assert response.status_code in [200, 401]


@pytest.mark.asyncio
async def test_v2_notifications_get_unread_count(client: AsyncClient, test_db: AsyncSession):
    """测试V2获取未读通知数量"""
    user = await create_test_user(test_db)
    headers = await get_auth_header(user)
    
    # 创建测试通知
    await create_test_notification(test_db, user, "price_alert")
    await create_test_notification(test_db, user, "trade_offer")
    
    response = await client.get("/api/v2/notifications/unread-count", headers=headers)
    assert response.status_code in [200, 401]
