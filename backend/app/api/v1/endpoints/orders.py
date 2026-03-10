# -*- coding: utf-8 -*-
"""
订单端点
"""
from typing import Optional, List
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.core.database import get_db
from app.core.security import get_current_user
from app.core.exceptions import NotFoundError, BusinessError
from app.models.user import User
from app.models.order import Order
from app.schemas.order import (
    OrderCreate,
    OrderResponse,
    OrderListResponse,
    OrderCancelRequest,
    OrderStatus,
)

router = APIRouter()


@router.get("", response_model=OrderListResponse)
async def get_orders(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    side: Optional[str] = None,
    source: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取订单列表"""
    query = select(Order).where(Order.user_id == current_user.id)
    
    if status:
        query = query.where(Order.status == status)
    if side:
        query = query.where(Order.side == side)
    if source:
        query = query.where(Order.source == source)
    
    query = query.order_by(Order.created_at.desc())
    
    # 分页
    offset = (page - 1) * page_size
    query = query.offset(offset).limit(page_size)
    
    result = await db.execute(query)
    orders = result.scalars().all()
    
    # 获取总数
    count_query = select(Order).where(Order.user_id == current_user.id)
    if status:
        count_query = count_query.where(Order.status == status)
    
    count_result = await db.execute(count_query)
    total = len(count_result.scalars().all())
    
    return {
        "orders": orders,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post("", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order(
    order_data: OrderCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """创建订单"""
    # 生成订单号
    import uuid
    order_id = f"ORD-{uuid.uuid4().hex[:12].upper()}"
    
    order = Order(
        order_id=order_id,
        user_id=current_user.id,
        item_id=order_data.item_id,
        side=order_data.side,
        price=order_data.price,
        quantity=order_data.quantity,
        source=order_data.source.value,
    )
    
    db.add(order)
    await db.commit()
    await db.refresh(order)
    
    return order


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取订单详情"""
    result = await db.execute(
        select(Order).where(
            and_(Order.order_id == order_id, Order.user_id == current_user.id)
        )
    )
    order = result.scalar_one_or_none()
    
    if not order:
        raise NotFoundError("订单", order_id)
    
    return order


@router.delete("/{order_id}")
async def cancel_order(
    order_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """取消订单"""
    result = await db.execute(
        select(Order).where(
            and_(Order.order_id == order_id, Order.user_id == current_user.id)
        )
    )
    order = result.scalar_one_or_none()
    
    if not order:
        raise NotFoundError("订单", order_id)
    
    if order.status != "pending":
        raise BusinessError("只能取消待处理的订单")
    
    from datetime import datetime
    order.status = "cancelled"
    order.cancelled_at = datetime.utcnow()
    
    await db.commit()
    
    return {"message": "订单已取消", "order_id": order_id}
