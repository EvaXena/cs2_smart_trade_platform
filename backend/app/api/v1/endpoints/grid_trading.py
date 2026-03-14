# -*- coding: utf-8 -*-
"""
网格交易策略 API 端点
"""
import logging
from typing import Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from app.core.database import get_db
from app.core.security import get_current_user
from app.core.response import success_response, error_response
from app.models.user import User
from app.models.grid_strategy import GridStrategy
from app.schemas.grid_strategy import (
    GridStrategyCreate,
    GridStrategyUpdate,
    GridStrategyResponse,
    GridStrategyListResponse,
    GridStrategyOperationResponse,
    GridPriceUpdateRequest,
    GridPriceUpdateResponse,
    GridStateItem,
)
from app.services.strategies.grid_trading import (
    GridTradingStrategy,
    create_grid_strategy,
    get_grid_strategy,
    get_user_grid_strategies,
    delete_grid_strategy,
    update_grid_strategy,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/strategies/grid", tags=["网格交易策略"])


@router.post("/create", response_model=GridStrategyOperationResponse, status_code=status.HTTP_201_CREATED)
async def create_grid(
    strategy_data: GridStrategyCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """创建网格交易策略"""
    try:
        # 验证价格区间
        if strategy_data.price_upper <= strategy_data.price_lower:
            return error_response(
                message="价格上界必须大于价格下界",
                code="INVALID_PRICE_RANGE"
            )
        
        # 创建策略
        strategy = await create_grid_strategy(
            db=db,
            user_id=current_user.id,
            item_id=strategy_data.item_id,
            name=strategy_data.name,
            price_lower=strategy_data.price_lower,
            price_upper=strategy_data.price_upper,
            grid_count=strategy_data.grid_count,
            quantity_per_grid=strategy_data.quantity_per_grid,
            profit_percentage=strategy_data.profit_percentage,
            stop_loss_percentage=strategy_data.stop_loss_percentage,
        )
        
        return success_response(
            data={
                "strategy_id": strategy.id,
                "name": strategy.name,
                "status": strategy.status,
            },
            message="网格策略创建成功"
        )
        
    except ValueError as e:
        return error_response(message=str(e), code="VALIDATION_ERROR")
    except Exception as e:
        logger.error(f"创建网格策略失败: {e}")
        return error_response(message=f"创建失败: {str(e)}", code="CREATE_FAILED")


@router.get("/list", response_model=GridStrategyListResponse)
async def list_grids(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    is_active: Optional[bool] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取用户的网格策略列表"""
    
    # 构建过滤条件
    filters = [GridStrategy.user_id == current_user.id]
    
    if status_filter:
        filters.append(GridStrategy.status == status_filter)
    if is_active is not None:
        filters.append(GridStrategy.is_active == is_active)
    
    # 获取总数
    count_query = select(func.count()).select_from(GridStrategy).where(and_(*filters))
    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0
    
    # 分页查询
    offset = (page - 1) * page_size
    query = (
        select(GridStrategy)
        .where(and_(*filters))
        .order_by(GridStrategy.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    
    result = await db.execute(query)
    strategies = result.scalars().all()
    
    return {
        "strategies": [
            GridStrategyResponse(
                id=s.id,
                user_id=s.user_id,
                item_id=s.item_id,
                name=s.name,
                price_lower=s.price_lower,
                price_upper=s.price_upper,
                grid_count=s.grid_count,
                quantity_per_grid=s.quantity_per_grid,
                profit_percentage=s.profit_percentage,
                stop_loss_percentage=s.stop_loss_percentage,
                is_active=s.is_active,
                status=s.status,
                last_price=s.last_price,
                entry_price=s.entry_price,
                total_trades=s.total_trades,
                total_profit=float(s.total_profit),
                completed_grids=s.completed_grids,
                created_at=s.created_at,
                updated_at=s.updated_at,
                started_at=s.started_at,
                stopped_at=s.stopped_at,
            )
            for s in strategies
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/{strategy_id}", response_model=GridStrategyResponse)
async def get_grid(
    strategy_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取网格策略详情"""
    
    # 获取策略
    strategy = await get_grid_strategy(db, strategy_id)
    
    if not strategy:
        return error_response(message="策略不存在", code="NOT_FOUND")
    
    # 验证所有权
    if strategy.user_id != current_user.id:
        return error_response(message="无权访问此策略", code="FORBIDDEN")
    
    # 获取活跃的策略实例以获取实时状态
    strategy_instance = GridTradingStrategy.get_active_strategy(strategy_id)
    
    if strategy_instance:
        # 从活跃实例获取状态
        status_data = await strategy_instance.get_status()
        grid_prices = status_data.get("grid_prices", [])
        grid_states = status_data.get("grid_states", [])
    else:
        # 从数据库获取状态
        grid_prices = []
        if strategy.grid_state:
            for i in range(strategy.grid_count):
                if str(i) in strategy.grid_state:
                    grid_prices.append(strategy.grid_state[str(i)]["price"])
        grid_states = []
    
    return GridStrategyResponse(
        id=strategy.id,
        user_id=strategy.user_id,
        item_id=strategy.item_id,
        name=strategy.name,
        price_lower=strategy.price_lower,
        price_upper=strategy.price_upper,
        grid_count=strategy.grid_count,
        quantity_per_grid=strategy.quantity_per_grid,
        profit_percentage=strategy.profit_percentage,
        stop_loss_percentage=strategy.stop_loss_percentage,
        is_active=strategy.is_active,
        status=strategy.status,
        last_price=strategy.last_price,
        entry_price=strategy.entry_price,
        total_trades=strategy.total_trades,
        total_profit=float(strategy.total_profit),
        completed_grids=strategy.completed_grids,
        grid_prices=grid_prices,
        grid_states=[GridStateItem(**gs) for gs in grid_states] if grid_states else None,
        created_at=strategy.created_at,
        updated_at=strategy.updated_at,
        started_at=strategy.started_at,
        stopped_at=strategy.stopped_at,
    )


@router.post("/{strategy_id}/start", response_model=GridStrategyOperationResponse)
async def start_grid(
    strategy_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """启动网格交易策略"""
    
    # 获取策略
    strategy = await get_grid_strategy(db, strategy_id)
    
    if not strategy:
        return error_response(message="策略不存在", code="NOT_FOUND")
    
    # 验证所有权
    if strategy.user_id != current_user.id:
        return error_response(message="无权访问此策略", code="FORBIDDEN")
    
    # 检查状态
    if strategy.status == "running":
        return error_response(message="策略已在运行中", code="ALREADY_RUNNING")
    
    if strategy.status == "stopped":
        return error_response(message="策略已停止，无法重启", code="ALREADY_STOPPED")
    
    try:
        # 创建策略实例并初始化
        strategy_instance = GridTradingStrategy(db, strategy_id)
        await strategy_instance.load_strategy(strategy_id)
        result = await strategy_instance.initialize()
        
        if result.success:
            return success_response(
                data={"strategy_id": strategy_id},
                message="策略启动成功"
            )
        else:
            return error_response(message=result.message, code="START_FAILED")
            
    except Exception as e:
        logger.error(f"启动网格策略失败: {e}")
        return error_response(message=f"启动失败: {str(e)}", code="START_FAILED")


@router.post("/{strategy_id}/pause", response_model=GridStrategyOperationResponse)
async def pause_grid(
    strategy_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """暂停网格交易策略"""
    
    # 获取策略
    strategy = await get_grid_strategy(db, strategy_id)
    
    if not strategy:
        return error_response(message="策略不存在", code="NOT_FOUND")
    
    # 验证所有权
    if strategy.user_id != current_user.id:
        return error_response(message="无权访问此策略", code="FORBIDDEN")
    
    # 检查状态
    if strategy.status != "running":
        return error_response(message="策略未在运行", code="NOT_RUNNING")
    
    try:
        # 获取活跃策略实例
        strategy_instance = GridTradingStrategy.get_active_strategy(strategy_id)
        
        if strategy_instance:
            result = await strategy_instance.pause()
            return result
        else:
            # 如果没有活跃实例，直接更新状态
            strategy.status = "paused"
            await db.commit()
            return success_response(message="策略已暂停")
            
    except Exception as e:
        logger.error(f"暂停网格策略失败: {e}")
        return error_response(message=f"暂停失败: {str(e)}", code="PAUSE_FAILED")


@router.post("/{strategy_id}/resume", response_model=GridStrategyOperationResponse)
async def resume_grid(
    strategy_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """恢复网格交易策略"""
    
    # 获取策略
    strategy = await get_grid_strategy(db, strategy_id)
    
    if not strategy:
        return error_response(message="策略不存在", code="NOT_FOUND")
    
    # 验证所有权
    if strategy.user_id != current_user.id:
        return error_response(message="无权访问此策略", code="FORBIDDEN")
    
    # 检查状态
    if strategy.status != "paused":
        return error_response(message="策略未暂停", code="NOT_PAUSED")
    
    try:
        # 创建策略实例并恢复
        strategy_instance = GridTradingStrategy(db, strategy_id)
        await strategy_instance.load_strategy(strategy_id)
        result = await strategy_instance.resume()
        
        return result
            
    except Exception as e:
        logger.error(f"恢复网格策略失败: {e}")
        return error_response(message=f"恢复失败: {str(e)}", code="RESUME_FAILED")


@router.post("/{strategy_id}/stop", response_model=GridStrategyOperationResponse)
async def stop_grid(
    strategy_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """停止网格交易策略"""
    
    # 获取策略
    strategy = await get_grid_strategy(db, strategy_id)
    
    if not strategy:
        return error_response(message="策略不存在", code="NOT_FOUND")
    
    # 验证所有权
    if strategy.user_id != current_user.id:
        return error_response(message="无权访问此策略", code="FORBIDDEN")
    
    # 检查状态
    if strategy.status == "stopped":
        return error_response(message="策略已停止", code="ALREADY_STOPPED")
    
    try:
        # 获取活跃策略实例
        strategy_instance = GridTradingStrategy.get_active_strategy(strategy_id)
        
        if strategy_instance:
            result = await strategy_instance.stop()
            if result.success:
                return success_response(
                    data=result.data,
                    message="策略已停止"
                )
            return result
        else:
            # 如果没有活跃实例，直接更新状态
            strategy.status = "stopped"
            strategy.is_active = False
            await db.commit()
            return success_response(message="策略已停止")
            
    except Exception as e:
        logger.error(f"停止网格策略失败: {e}")
        return error_response(message=f"停止失败: {str(e)}", code="STOP_FAILED")


@router.post("/{strategy_id}/price", response_model=GridPriceUpdateResponse)
async def update_price(
    strategy_id: int,
    price_data: GridPriceUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """更新价格（触发网格交易逻辑）"""
    
    # 获取策略
    strategy = await get_grid_strategy(db, strategy_id)
    
    if not strategy:
        return error_response(message="策略不存在", code="NOT_FOUND")
    
    # 验证所有权
    if strategy.user_id != current_user.id:
        return error_response(message="无权访问此策略", code="FORBIDDEN")
    
    # 检查状态
    if strategy.status != "running":
        return error_response(message="策略未在运行", code="NOT_RUNNING")
    
    try:
        # 获取活跃策略实例
        strategy_instance = GridTradingStrategy.get_active_strategy(strategy_id)
        
        if not strategy_instance:
            return error_response(message="策略实例未初始化", code="INSTANCE_NOT_INIT")
        
        # 处理价格更新
        result = await strategy_instance.on_price_update(price_data.price)
        
        return GridPriceUpdateResponse(
            actions=result.get("actions", []),
            current_price=result.get("current_price", price_data.price)
        )
        
    except Exception as e:
        logger.error(f"价格更新失败: {e}")
        return error_response(message=f"价格更新失败: {str(e)}", code="PRICE_UPDATE_FAILED")


@router.delete("/{strategy_id}", response_model=GridStrategyOperationResponse)
async def delete_grid(
    strategy_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """删除网格交易策略"""
    
    # 获取策略
    strategy = await get_grid_strategy(db, strategy_id)
    
    if not strategy:
        return error_response(message="策略不存在", code="NOT_FOUND")
    
    # 验证所有权
    if strategy.user_id != current_user.id:
        return error_response(message="无权访问此策略", code="FORBIDDEN")
    
    try:
        success = await delete_grid_strategy(db, strategy_id)
        
        if success:
            return success_response(message="策略已删除")
        else:
            return error_response(message="删除失败", code="DELETE_FAILED")
            
    except Exception as e:
        logger.error(f"删除网格策略失败: {e}")
        return error_response(message=f"删除失败: {str(e)}", code="DELETE_FAILED")


@router.put("/{strategy_id}", response_model=GridStrategyOperationResponse)
async def update_grid(
    strategy_id: int,
    strategy_data: GridStrategyUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """更新网格交易策略"""
    
    # 获取策略
    strategy = await get_grid_strategy(db, strategy_id)
    
    if not strategy:
        return error_response(message="策略不存在", code="NOT_FOUND")
    
    # 验证所有权
    if strategy.user_id != current_user.id:
        return error_response(message="无权访问此策略", code="FORBIDDEN")
    
    # 检查状态
    if strategy.status != "pending":
        return error_response(message="只能更新pending状态的策略", code="INVALID_STATE")
    
    try:
        # 验证价格区间
        price_lower = strategy_data.price_lower if strategy_data.price_lower else strategy.price_lower
        price_upper = strategy_data.price_upper if strategy_data.price_upper else strategy.price_upper
        
        if price_upper <= price_lower:
            return error_response(
                message="价格上界必须大于价格下界",
                code="INVALID_PRICE_RANGE"
            )
        
        # 更新策略
        updated_strategy = await update_grid_strategy(
            db=db,
            strategy_id=strategy_id,
            user_id=current_user.id,
            name=strategy_data.name,
            price_lower=strategy_data.price_lower,
            price_upper=strategy_data.price_upper,
            grid_count=strategy_data.grid_count,
            quantity_per_grid=strategy_data.quantity_per_grid,
            profit_percentage=strategy_data.profit_percentage,
            stop_loss_percentage=strategy_data.stop_loss_percentage,
            is_active=strategy_data.is_active,
        )
        
        if not updated_strategy:
            return error_response(message="更新失败", code="UPDATE_FAILED")
        
        return success_response(
            data={
                "strategy_id": updated_strategy.id,
                "name": updated_strategy.name,
                "status": updated_strategy.status,
            },
            message="策略更新成功"
        )
        
    except ValueError as e:
        return error_response(message=str(e), code="VALIDATION_ERROR")
    except Exception as e:
        logger.error(f"更新网格策略失败: {e}")
        return error_response(message=f"更新失败: {str(e)}", code="UPDATE_FAILED")


@router.get("/{strategy_id}/status")
async def get_grid_status(
    strategy_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取网格策略实时状态"""
    
    # 获取策略
    strategy = await get_grid_strategy(db, strategy_id)
    
    if not strategy:
        return error_response(message="策略不存在", code="NOT_FOUND")
    
    # 验证所有权
    if strategy.user_id != current_user.id:
        return error_response(message="无权访问此策略", code="FORBIDDEN")
    
    try:
        # 获取活跃策略实例
        strategy_instance = GridTradingStrategy.get_active_strategy(strategy_id)
        
        if strategy_instance:
            status_data = await strategy_instance.get_status()
            return success_response(data=status_data)
        else:
            # 返回数据库中的静态状态
            return success_response(
                data={
                    "id": strategy.id,
                    "status": strategy.status,
                    "is_active": strategy.is_active,
                    "last_price": strategy.last_price,
                    "total_trades": strategy.total_trades,
                    "total_profit": float(strategy.total_profit),
                    "completed_grids": strategy.completed_grids,
                }
            )
        
    except Exception as e:
        logger.error(f"获取状态失败: {e}")
        return error_response(message=f"获取状态失败: {str(e)}", code="STATUS_FAILED")
