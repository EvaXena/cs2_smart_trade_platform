# -*- coding: utf-8 -*-
"""
订单端点
"""
import logging
from typing import Optional, List
from fastapi import APIRouter, Depends, Query, status, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.security import get_current_user
from app.core.exceptions import NotFoundError, BusinessError
from app.core.idempotency import (
    generate_idempotency_key,
    check_idempotency,
    save_idempotent_response,
)
from app.models.user import User
from app.models.order import Order
from app.schemas.order import (
    OrderCreate,
    OrderResponse,
    OrderListResponse,
    OrderCancelRequest,
    OrderStatus,
)
from app.utils.validators import validate_item_id, validate_price, validate_quantity, validate_order_id

logger = logging.getLogger(__name__)

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
    # 构建基础过滤条件
    filters = [Order.user_id == current_user.id]
    
    if status:
        filters.append(Order.status == status)
    if side:
        filters.append(Order.side == side)
    if source:
        filters.append(Order.source == source)
    
    # 使用 func.count() 获取总数（不加载所有数据到内存）
    count_query = select(func.count()).select_from(Order).where(and_(*filters))
    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0
    
    # 使用 selectinload 预加载关联数据，避免 N+1 查询
    query = (
        select(Order)
        .where(and_(*filters))
        .options(selectinload(Order.user), selectinload(Order.item))
        .order_by(Order.created_at.desc())
    )
    
    # 分页
    offset = (page - 1) * page_size
    query = query.offset(offset).limit(page_size)
    
    result = await db.execute(query)
    orders = result.scalars().all()
    
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
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    """创建订单（支持幂等性）"""
    # 如果提供了幂等性 key，进行检查
    if idempotency_key:
        # 生成内部幂等性 key
        internal_key = generate_idempotency_key(
            current_user.id,
            "POST",
            "/api/v1/orders",
            f"{order_data.item_id}:{order_data.side}:{order_data.price}:{order_data.quantity}"
        )
        
        # 检查是否已处理过
        is_duplicate, cached_response = await check_idempotency(internal_key)
        if is_duplicate and cached_response:
            logger.info(f"检测到重复订单请求，key: {idempotency_key}")
            return cached_response
    
    # 使用验证器验证输入数据
    validated_item_id = validate_item_id(order_data.item_id)
    validated_price = validate_price(order_data.price)
    validated_quantity = validate_quantity(order_data.quantity)
    
    # 生成订单号
    import uuid
    order_id = f"ORD-{uuid.uuid4().hex[:12].upper()}"
    
    order = Order(
        order_id=order_id,
        user_id=current_user.id,
        item_id=validated_item_id,
        side=order_data.side,
        price=validated_price,
        quantity=validated_quantity,
        source=order_data.source.value,
    )
    
    db.add(order)
    await db.commit()
    await db.refresh(order)
    
    # 构建响应数据
    response_data = OrderResponse.model_validate(order).model_dump()
    
    # 如果提供了幂等性 key，保存响应
    if idempotency_key:
        await save_idempotent_response(internal_key, response_data)
    
    return response_data


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取订单详情"""
    # 使用验证器验证order_id
    validated_order_id = validate_order_id(order_id)
    
    result = await db.execute(
        select(Order).where(
            and_(Order.order_id == validated_order_id, Order.user_id == current_user.id)
        )
    )
    order = result.scalar_one_or_none()
    
    if not order:
        raise NotFoundError("订单", validated_order_id)
    
    return order


@router.delete("/{order_id}")
async def cancel_order(
    order_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """取消订单"""
    # 使用验证器验证order_id
    validated_order_id = validate_order_id(order_id)
    
    result = await db.execute(
        select(Order).where(
            and_(Order.order_id == validated_order_id, Order.user_id == current_user.id)
        )
    )
    order = result.scalar_one_or_none()
    
    if not order:
        raise NotFoundError("订单", validated_order_id)
    
    if order.status != "pending":
        raise BusinessError("只能取消待处理的订单")
    
    from datetime import datetime
    order.status = "cancelled"
    order.cancelled_at = datetime.utcnow()
    
    await db.commit()
    
    return {"message": "订单已取消", "order_id": order_id}
