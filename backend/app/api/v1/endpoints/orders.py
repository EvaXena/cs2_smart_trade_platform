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
from app.core.config import settings
from app.core.idempotency import (
    generate_idempotency_key,
    check_idempotency,
    save_idempotent_response,
)
from app.core.permissions_registry import verify_resource_owner
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
from app.validators.batch_validator import BatchValidator
from app.schemas.batch import (
    OrderBatchCreateRequest,
    OrderBatchResponse,
    OrderBatchCancelRequest,
    OrderBatchCancelResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# 创建批量验证器
_order_batch_create_validator = BatchValidator(OrderCreate, max_size=100)


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
    
    # ========== 交易限额检查 ==========
    # 计算订单总金额
    order_total = validated_price * validated_quantity
    
    # 检查用户余额是否充足（仅针对购买订单）
    if order_data.side.value == "buy":
        # 获取用户当前余额
        user_balance = current_user.balance or 0
        if isinstance(user_balance, str):
            user_balance = float(user_balance)
        
        if user_balance < order_total:
            raise BusinessError(
                f"余额不足: 当前余额 {user_balance:.2f}，订单金额 {order_total:.2f}"
            )
        
        # 检查单笔订单限额
        if order_total > settings.MAX_SINGLE_ORDER:
            raise BusinessError(
                f"单笔订单金额超限: 最大 {settings.MAX_SINGLE_ORDER:.2f}，订单金额 {order_total:.2f}"
            )
        
        # 检查日累计限额
        from datetime import datetime, timedelta
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        
        # 查询今日已成交的订单总金额
        daily_orders_query = select(func.sum(Order.price * Order.quantity)).where(
            and_(
                Order.user_id == current_user.id,
                Order.side == "buy",
                Order.status.in_(["completed", "filled"]),  # 只计算已完成的订单
                Order.created_at >= today_start
            )
        )
        daily_result = await db.execute(daily_orders_query)
        daily_total = daily_result.scalar() or 0
        if isinstance(daily_total, str):
            daily_total = float(daily_total)
        
        if daily_total + order_total > settings.MAX_DAILY_LIMIT:
            raise BusinessError(
                f"今日交易限额已用完: 今日已交易 {daily_total:.2f}，限额 {settings.MAX_DAILY_LIMIT:.2f}"
            )
    
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


@router.get("/statistics")
async def get_order_statistics(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取订单统计信息"""
    from sqlalchemy import case
    
    # 统计订单总数
    total_result = await db.execute(
        select(func.count()).select_from(Order).where(Order.user_id == current_user.id)
    )
    total = total_result.scalar() or 0
    
    # 统计各状态订单数量
    status_result = await db.execute(
        select(
            Order.status,
            func.count(Order.id).label('count')
        ).where(Order.user_id == current_user.id).group_by(Order.status)
    )
    status_counts = {row.status: row.count for row in status_result.all()}
    
    # 统计总收入和支出
    revenue_result = await db.execute(
        select(
            func.sum(
                case(
                    (Order.side == 'sell', Order.price),
                    else_=0
                )
            ).label('revenue'),
            func.sum(
                case(
                    (Order.side == 'buy', Order.price),
                    else_=0
                )
            ).label('expense')
        ).where(Order.user_id == current_user.id, Order.status == 'completed')
    )
    revenue_row = revenue_result.one_or_none()
    
    return {
        "total": total,
        "pending": status_counts.get('pending', 0),
        "processing": status_counts.get('processing', 0),
        "completed": status_counts.get('completed', 0),
        "cancelled": status_counts.get('cancelled', 0),
        "failed": status_counts.get('failed', 0),
        "revenue": float(revenue_row.revenue or 0),
        "expense": float(revenue_row.expense or 0)
    }


@router.get("/{order_id}", response_model=OrderResponse)
@verify_resource_owner("order", "order_id")
async def get_order(
    order_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取订单详情"""
    # 使用验证器验证order_id
    validated_order_id = validate_order_id(order_id)
    
    result = await db.execute(
        select(Order).where(Order.order_id == validated_order_id)
    )
    order = result.scalar_one_or_none()
    
    if not order:
        raise NotFoundError("订单", validated_order_id)
    
    return order


@router.delete("/{order_id}")
@verify_resource_owner("order", "order_id")
async def cancel_order(
    order_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """取消订单"""
    # 使用验证器验证order_id
    validated_order_id = validate_order_id(order_id)
    
    result = await db.execute(
        select(Order).where(Order.order_id == validated_order_id)
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


@router.post("/batch", response_model=OrderBatchResponse, status_code=status.HTTP_201_CREATED)
async def create_orders_batch(
    request: OrderBatchCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    批量创建订单
    
    一次性创建多个订单，支持批量操作。
    
    ## 参数说明
    
    | 参数 | 类型 | 必填 | 说明 |
    |------|------|------|------|
    | orders | List[OrderBatchItem] | 是 | 订单列表，最多100个 |
    
    ## OrderBatchItem 字段
    
    | 字段 | 类型 | 必填 | 说明 |
    |------|------|------|------|
    | item_id | int | 是 | 饰品ID |
    | side | str | 是 | buy/sell |
    | price | float | 是 | 价格，0.01-10000 |
    | quantity | int | 否 | 数量，默认1，最大100 |
    | source | str | 否 | 来源，默认 manual |
    
    ## 返回格式
    
    ```json
    {
        "orders": [...],
        "success_count": 8,
        "fail_count": 2,
        "total": 10
    }
    ```
    
    ## 错误码
    
    - 400: 批量大小超限或数据格式错误
    - 402: 余额不足
    """
    # 预验证整个批次（使用 Pydantic 模型验证，会自动调用 validators）
    try:
        validated_orders = await _order_batch_create_validator.validate(request.orders)
    except Exception as e:
        raise BusinessError(f"批量数据验证失败: {str(e)}")
    
    # 处理订单
    created_orders = []
    results = []
    success_count = 0
    fail_count = 0
    
    for idx, order_data in enumerate(validated_orders):
        try:
            # 直接使用已验证的数据（不需要再调用 validate_xxx）
            # 计算订单金额
            order_total = float(order_data.price) * int(order_data.quantity)
            
            # 余额检查（仅购买订单）
            if order_data.side.value == "buy":
                user_balance = current_user.balance or 0
                if isinstance(user_balance, str):
                    user_balance = float(user_balance)
                
                if user_balance < order_total:
                    results.append({
                        "index": idx + 1,
                        "success": False,
                        "error": f"余额不足: 需要 {order_total:.2f}，当前 {user_balance:.2f}"
                    })
                    fail_count += 1
                    continue
            
            # 生成订单号
            import uuid
            order_id = f"ORD-{uuid.uuid4().hex[:12].upper()}"
            
            order = Order(
                order_id=order_id,
                user_id=current_user.id,
                item_id=order_data.item_id,
                side=order_data.side.value,
                price=order_data.price,
                quantity=order_data.quantity,
                source=order_data.source.value,
            )
            
            db.add(order)
            created_orders.append(order)
            
            results.append({
                "index": idx + 1,
                "success": True,
                "order_id": order_id
            })
            success_count += 1
            
        except Exception as e:
            results.append({
                "index": idx + 1,
                "success": False,
                "error": str(e)
            })
            fail_count += 1
    
    # 批量提交
    if created_orders:
        await db.commit()
        # 刷新获取完整数据
        for order in created_orders:
            await db.refresh(order)
    
    return {
        "orders": [OrderResponse.model_validate(o).model_dump() for o in created_orders],
        "success_count": success_count,
        "fail_count": fail_count,
        "total": len(request.orders)
    }


@router.post("/batch/cancel", response_model=OrderBatchCancelResponse)
async def cancel_orders_batch(
    request: OrderBatchCancelRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    批量取消订单
    
    一次性取消多个待处理的订单。
    
    ## 参数说明
    
    | 参数 | 类型 | 必填 | 说明 |
    |------|------|------|------|
    | order_ids | List[str] | 是 | 订单ID列表，最多50个 |
    
    ## 返回格式
    
    ```json
    {
        "success_count": 3,
        "fail_count": 2,
        "results": [...]
    }
    ```
    
    ## 错误码
    
    - 400: 批量大小超限或数据格式错误
    """
    results = []
    success_count = 0
    fail_count = 0
    
    # 批量取消需要验证每个订单的归属权
    for order_id in request.order_ids:
        try:
            # 验证订单ID
            validated_order_id = validate_order_id(order_id)
            
            # 查询订单（不限制 user_id，由权限检查器验证）
            result = await db.execute(
                select(Order).where(Order.order_id == validated_order_id)
            )
            order = result.scalar_one_or_none()
            
            if not order:
                results.append({
                    "order_id": order_id,
                    "success": False,
                    "error": "订单不存在"
                })
                fail_count += 1
                continue
            
            # 验证所有权
            if order.user_id != current_user.id:
                results.append({
                    "order_id": order_id,
                    "success": False,
                    "error": "无权操作此订单"
                })
                fail_count += 1
                continue
            
            if order.status != "pending":
                results.append({
                    "order_id": order_id,
                    "success": False,
                    "error": f"订单状态不是待处理，当前状态: {order.status}"
                })
                fail_count += 1
                continue
            
            # 取消订单
            from datetime import datetime
            order.status = "cancelled"
            order.cancelled_at = datetime.utcnow()
            
            results.append({
                "order_id": order_id,
                "success": True
            })
            success_count += 1
            
        except Exception as e:
            results.append({
                "order_id": order_id,
                "success": False,
                "error": str(e)
            })
            fail_count += 1
    
    # 批量提交
    await db.commit()
    
    return {
        "success_count": success_count,
        "fail_count": fail_count,
        "results": results
    }
