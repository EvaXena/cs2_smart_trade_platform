# -*- coding: utf-8 -*-
"""
统计端点
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import datetime, timedelta

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.order import Order
from app.models.inventory import Inventory, Listing
from app.models.bot import Bot, BotTrade
from app.models.monitor import MonitorTask
from app.schemas.stats import (
    OverallStats,
    UserStats,
    TradeStats,
    TradeStatsListResponse,
    ProfitStats,
    ProfitStatsResponse,
    InventoryValueStats,
    DashboardStats,
)

router = APIRouter()


@router.get("", response_model=OverallStats)
async def get_overall_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """获取总体统计"""
    # 用户数
    user_count = await db.scalar(select(func.count(User.id)))
    
    # 机器人总数
    bot_count = await db.scalar(select(func.count(Bot.id)))
    
    # 订单总数
    order_count = await db.scalar(select(func.count(Order.id)))
    
    # 交易总数
    trade_count = await db.scalar(select(func.count(BotTrade.id)))
    
    # 活跃监控数
    active_monitor_count = await db.scalar(
        select(func.count(MonitorTask.id)).where(
            MonitorTask.enabled == True,
            MonitorTask.status == 'running'
        )
    )
    
    # 计算总交易量和库存价值
    # 计算已完成订单的总交易量
    total_volume_result = await db.execute(
        select(func.sum(Order.price)).where(Order.status == 'completed')
    )
    total_volume = float(total_volume_result.scalar() or 0)
    
    # 计算库存总价值
    inventory_value_result = await db.execute(
        select(func.sum(Inventory.cost_price)).where(
            Inventory.status == 'available'
        )
    )
    inventory_value = float(inventory_value_result.scalar() or 0)
    
    return OverallStats(
        total_users=user_count or 0,
        total_bots=bot_count or 0,
        total_orders=order_count or 0,
        total_trades=trade_count or 0,
        total_volume=total_volume,
        active_monitors=active_monitor_count or 0,
        inventory_value=inventory_value
    )


@router.get("/user/{user_id}", response_model=UserStats)
async def get_user_stats(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """获取用户统计"""
    # 验证权限
    if user_id != current_user.id and not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权查看其他用户统计"
        )
    
    # 订单统计
    order_count = await db.scalar(
        select(func.count(Order.id)).where(Order.user_id == user_id)
    )
    completed_orders = await db.scalar(
        select(func.count(Order.id)).where(
            Order.user_id == user_id,
            Order.status == 'completed'
        )
    )
    cancelled_orders = await db.scalar(
        select(func.count(Order.id)).where(
            Order.user_id == user_id,
            Order.status == 'cancelled'
        )
    )
    
    # 金额统计
    total_spent = await db.scalar(
        select(func.sum(Order.price)).where(
            Order.user_id == user_id,
            Order.status == 'completed'
        )
    )
    
    # 库存统计
    inventory_count = await db.scalar(
        select(func.count(Inventory.id)).where(
            Inventory.user_id == user_id,
            Inventory.status == 'available'
        )
    )
    
    return UserStats(
        user_id=user_id,
        total_orders=order_count or 0,
        completed_orders=completed_orders or 0,
        cancelled_orders=cancelled_orders or 0,
        total_spent=float(total_spent or 0),
        total_earned=0.0,
        profit=0.0,
        inventory_count=inventory_count or 0,
        inventory_value=0.0
    )


@router.get("/trades", response_model=TradeStatsListResponse)
async def get_trade_stats(
    days: int = Query(7, ge=1, le=90),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """获取交易统计"""
    # 获取用户的所有机器人
    bot_result = await db.execute(
        select(Bot.id).where(Bot.owner_id == current_user.id)
    )
    bot_ids = [row[0] for row in bot_result.fetchall()]
    
    if not bot_ids:
        return TradeStatsListResponse(trades=[], total=0)
    
    # 获取时间范围
    start_date = datetime.utcnow() - timedelta(days=days)
    
    # 简化：返回汇总统计
    total_trades = await db.scalar(
        select(func.count(BotTrade.id)).where(
            BotTrade.bot_id.in_(bot_ids),
            BotTrade.created_at >= start_date
        )
    )
    
    successful_trades = await db.scalar(
        select(func.count(BotTrade.id)).where(
            BotTrade.bot_id.in_(bot_ids),
            BotTrade.status == 'accepted',
            BotTrade.created_at >= start_date
        )
    )
    
    # 汇总数据
    trades = [{
        "date": datetime.utcnow().strftime("%Y-%m-%d"),
        "total_trades": total_trades or 0,
        "successful_trades": successful_trades or 0,
        "failed_trades": (total_trades or 0) - (successful_trades or 0),
        "total_volume": 0.0,
        "avg_trade_value": 0.0
    }]
    
    return TradeStatsListResponse(
        trades=[TradeStats(**t) for t in trades],
        total=len(trades)
    )


@router.get("/profit", response_model=ProfitStatsResponse)
async def get_profit_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """获取利润统计"""
    # 实现实际的利润计算逻辑
    from datetime import timedelta
    
    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=now.weekday())
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    # 计算费用（Steam 交易手续费 15%）
    fee_rate = 0.15
    
    # 日利润计算
    daily_buy = await db.scalar(
        select(func.sum(Order.price)).where(
            Order.user_id == current_user.id,
            Order.side == 'buy',
            Order.status == 'completed',
            Order.created_at >= today_start
        )
    ) or 0
    
    daily_sell = await db.scalar(
        select(func.sum(Order.price)).where(
            Order.user_id == current_user.id,
            Order.side == 'sell',
            Order.status == 'completed',
            Order.created_at >= today_start
        )
    ) or 0
    
    daily_fee = daily_sell * fee_rate
    daily_profit_value = daily_sell - daily_buy - daily_fee
    
    daily_profit = ProfitStats(
        period="daily",
        total_profit=round(daily_profit_value, 2),
        arbitrage_profit=round(daily_profit_value * 0.7, 2),  # 假设 70% 来自搬砖
        flip_profit=round(daily_profit_value * 0.3, 2),      # 30% 来自flip
        fee=round(daily_fee, 2)
    )
    
    # 周利润计算
    weekly_buy = await db.scalar(
        select(func.sum(Order.price)).where(
            Order.user_id == current_user.id,
            Order.side == 'buy',
            Order.status == 'completed',
            Order.created_at >= week_start
        )
    ) or 0
    
    weekly_sell = await db.scalar(
        select(func.sum(Order.price)).where(
            Order.user_id == current_user.id,
            Order.side == 'sell',
            Order.status == 'completed',
            Order.created_at >= week_start
        )
    ) or 0
    
    weekly_fee = weekly_sell * fee_rate
    weekly_profit_value = weekly_sell - weekly_buy - weekly_fee
    
    weekly_profit = ProfitStats(
        period="weekly",
        total_profit=round(weekly_profit_value, 2),
        arbitrage_profit=round(weekly_profit_value * 0.7, 2),
        flip_profit=round(weekly_profit_value * 0.3, 2),
        fee=round(weekly_fee, 2)
    )
    
    # 月利润计算
    monthly_buy = await db.scalar(
        select(func.sum(Order.price)).where(
            Order.user_id == current_user.id,
            Order.side == 'buy',
            Order.status == 'completed',
            Order.created_at >= month_start
        )
    ) or 0
    
    monthly_sell = await db.scalar(
        select(func.sum(Order.price)).where(
            Order.user_id == current_user.id,
            Order.side == 'sell',
            Order.status == 'completed',
            Order.created_at >= month_start
        )
    ) or 0
    
    monthly_fee = monthly_sell * fee_rate
    monthly_profit_value = monthly_sell - monthly_buy - monthly_fee
    
    monthly_profit = ProfitStats(
        period="monthly",
        total_profit=round(monthly_profit_value, 2),
        arbitrage_profit=round(monthly_profit_value * 0.7, 2),
        flip_profit=round(monthly_profit_value * 0.3, 2),
        fee=round(monthly_fee, 2)
    )
    
    # 总利润计算
    all_time_buy = await db.scalar(
        select(func.sum(Order.price)).where(
            Order.user_id == current_user.id,
            Order.side == 'buy',
            Order.status == 'completed'
        )
    ) or 0
    
    all_time_sell = await db.scalar(
        select(func.sum(Order.price)).where(
            Order.user_id == current_user.id,
            Order.side == 'sell',
            Order.status == 'completed'
        )
    ) or 0
    
    all_time_fee = all_time_sell * fee_rate
    all_time_profit_value = all_time_sell - all_time_buy - all_time_fee
    
    all_time_profit = ProfitStats(
        period="all_time",
        total_profit=round(all_time_profit_value, 2),
        arbitrage_profit=round(all_time_profit_value * 0.7, 2),
        flip_profit=round(all_time_profit_value * 0.3, 2),
        fee=round(all_time_fee, 2)
    )
    
    return ProfitStatsResponse(
        daily=daily_profit,
        weekly=weekly_profit,
        monthly=monthly_profit,
        all_time=all_time_profit
    )


@router.get("/inventory_value", response_model=InventoryValueStats)
async def get_inventory_value(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """获取库存价值统计"""
    # 获取用户库存
    inventory_result = await db.execute(
        select(Inventory).where(
            Inventory.user_id == current_user.id,
            Inventory.status == 'available'
        )
    )
    inventories = inventory_result.scalars().all()
    
    # 计算总价值
    total_value = sum(
        float(inv.cost_price or 0) for inv in inventories
    )
    
    # 简化：按平台统计
    by_platform = {
        "steam": total_value * 0.5,
        "buff": total_value * 0.5
    }
    
    return InventoryValueStats(
        total_value=total_value,
        by_platform=by_platform,
        by_rarity={},
        top_items=[]
    )


@router.get("/dashboard", response_model=DashboardStats)
async def get_dashboard_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """获取仪表盘统计"""
    # 总体统计
    user_count = await db.scalar(select(func.count(User.id)))
    bot_count = await db.scalar(select(func.count(Bot.id)))
    order_count = await db.scalar(select(func.count(Order.id)))
    trade_count = await db.scalar(select(func.count(BotTrade.id)))
    active_monitor_count = await db.scalar(
        select(func.count(MonitorTask.id)).where(
            MonitorTask.enabled == True,
            MonitorTask.status == 'running'
        )
    )
    
    overview = OverallStats(
        total_users=user_count or 0,
        total_bots=bot_count or 0,
        total_orders=order_count or 0,
        total_trades=trade_count or 0,
        total_volume=0.0,
        active_monitors=active_monitor_count or 0,
        inventory_value=0.0
    )
    
    # 简化返回
    return DashboardStats(
        overview=overview,
        recent_orders=[],
        top_performers=[],
        alerts=[]
    )
