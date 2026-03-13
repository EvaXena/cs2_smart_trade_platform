# -*- coding: utf-8 -*-
"""
通知端点
提供通知的CRUD操作
"""
import json
import logging
from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, status, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update, delete
from pydantic import BaseModel, ConfigDict

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.notification import Notification, NotificationType, NotificationPriority, NotificationStatus

logger = logging.getLogger(__name__)

router = APIRouter()


# ========== Schema ==========

class NotificationCreate(BaseModel):
    """通知创建"""
    notification_type: NotificationType = NotificationType.SYSTEM
    priority: NotificationPriority = NotificationPriority.NORMAL
    title: str
    content: str
    data: Optional[dict] = None


class NotificationUpdate(BaseModel):
    """通知更新"""
    is_read: Optional[bool] = None
    status: Optional[NotificationStatus] = None


class NotificationResponse(BaseModel):
    """通知响应"""
    id: int
    user_id: int
    notification_type: str
    priority: str
    status: str
    title: str
    content: str
    data: Optional[dict]
    is_read: bool
    created_at: datetime
    read_at: Optional[datetime]
    
    model_config = ConfigDict(from_attributes=True)


class NotificationListResponse(BaseModel):
    """通知列表响应"""
    notifications: List[NotificationResponse]
    total: int
    unread_count: int
    skip: int
    limit: int


# ========== 端点 ==========

@router.get("/", response_model=NotificationListResponse)
async def get_notifications(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    notification_type: Optional[NotificationType] = None,
    is_read: Optional[bool] = None,
    priority: Optional[NotificationPriority] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """获取通知列表"""
    query = select(Notification).where(Notification.user_id == current_user.id)
    
    if notification_type:
        query = query.where(Notification.notification_type == notification_type)
    
    if is_read is not None:
        query = query.where(Notification.is_read == is_read)
    
    if priority:
        query = query.where(Notification.priority == priority)
    
    # 获取总数
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    
    # 未读数量
    unread_result = await db.execute(
        select(func.count())
        .where(
            Notification.user_id == current_user.id,
            Notification.is_read == False
        )
    )
    unread_count = unread_result.scalar() or 0
    
    # 分页
    query = query.offset(skip).limit(limit).order_by(Notification.created_at.desc())
    result = await db.execute(query)
    notifications = result.scalars().all()
    
    # 转换数据
    notification_list = []
    for n in notifications:
        data = None
        if n.data:
            try:
                data = json.loads(n.data)
            except json.JSONDecodeError:
                pass
        
        notification_list.append(NotificationResponse(
            id=n.id,
            user_id=n.user_id,
            notification_type=n.notification_type.value,
            priority=n.priority.value,
            status=n.status.value,
            title=n.title,
            content=n.content,
            data=data,
            is_read=n.is_read,
            created_at=n.created_at,
            read_at=n.read_at
        ))
    
    return NotificationListResponse(
        notifications=notification_list,
        total=total,
        unread_count=unread_count,
        skip=skip,
        limit=limit
    )


@router.get("/unread-count")
async def get_unread_count(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """获取未读通知数量"""
    result = await db.execute(
        select(func.count())
        .where(
            Notification.user_id == current_user.id,
            Notification.is_read == False
        )
    )
    count = result.scalar() or 0
    
    return {"unread_count": count}


@router.get("/{notification_id}", response_model=NotificationResponse)
async def get_notification(
    notification_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """获取单个通知"""
    result = await db.execute(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == current_user.id
        )
    )
    notification = result.scalar_one_or_none()
    
    if not notification:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="通知不存在"
        )
    
    data = None
    if notification.data:
        try:
            data = json.loads(notification.data)
        except json.JSONDecodeError:
            pass
    
    return NotificationResponse(
        id=notification.id,
        user_id=notification.user_id,
        notification_type=notification.notification_type.value,
        priority=notification.priority.value,
        status=notification.status.value,
        title=notification.title,
        content=notification.content,
        data=data,
        is_read=notification.is_read,
        created_at=notification.created_at,
        read_at=notification.read_at
    )


@router.put("/{notification_id}/read", response_model=NotificationResponse)
async def mark_as_read(
    notification_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """标记通知为已读"""
    result = await db.execute(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == current_user.id
        )
    )
    notification = result.scalar_one_or_none()
    
    if not notification:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="通知不存在"
        )
    
    notification.is_read = True
    notification.status = NotificationStatus.READ
    notification.read_at = datetime.utcnow()
    
    await db.commit()
    await db.refresh(notification)
    
    data = None
    if notification.data:
        try:
            data = json.loads(notification.data)
        except json.JSONDecodeError:
            pass
    
    return NotificationResponse(
        id=notification.id,
        user_id=notification.user_id,
        notification_type=notification.notification_type.value,
        priority=notification.priority.value,
        status=notification.status.value,
        title=notification.title,
        content=notification.content,
        data=data,
        is_read=notification.is_read,
        created_at=notification.created_at,
        read_at=notification.read_at
    )


@router.post("/{notification_id}/read", response_model=NotificationResponse)
async def mark_notification_read(
    notification_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """标记通知已读"""
    result = await db.execute(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == current_user.id
        )
    )
    notification = result.scalar_one_or_none()
    
    if not notification:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="通知不存在"
        )
    
    notification.is_read = True
    notification.status = NotificationStatus.READ
    notification.read_at = datetime.utcnow()
    
    await db.commit()
    await db.refresh(notification)
    
    data = None
    if notification.data:
        try:
            data = json.loads(notification.data)
        except json.JSONDecodeError:
            pass
    
    return NotificationResponse(
        id=notification.id,
        user_id=notification.user_id,
        notification_type=notification.notification_type.value,
        priority=notification.priority.value,
        status=notification.status.value,
        title=notification.title,
        content=notification.content,
        data=data,
        is_read=notification.is_read,
        created_at=notification.created_at,
        read_at=notification.read_at
    )


@router.put("/read-all")
async def mark_all_as_read(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """标记所有通知为已读"""
    await db.execute(
        update(Notification)
        .where(
            Notification.user_id == current_user.id,
            Notification.is_read == False
        )
        .values(
            is_read=True,
            status=NotificationStatus.READ,
            read_at=datetime.utcnow()
        )
    )
    await db.commit()
    
    return {"message": "所有通知已标记为已读"}


@router.delete("/{notification_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_notification(
    notification_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """删除通知"""
    result = await db.execute(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == current_user.id
        )
    )
    notification = result.scalar_one_or_none()
    
    if not notification:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="通知不存在"
        )
    
    await db.delete(notification)
    await db.commit()
    
    return None


@router.delete("/", status_code=status.HTTP_204_NO_CONTENT)
async def delete_all_notifications(
    read_only: bool = Query(True, description="是否只删除已读通知"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """清空通知"""
    query = delete(Notification).where(Notification.user_id == current_user.id)
    
    if read_only:
        query = query.where(Notification.is_read == True)
    
    await db.execute(query)
    await db.commit()
    
    return None
