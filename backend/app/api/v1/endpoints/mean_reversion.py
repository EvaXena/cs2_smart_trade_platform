# -*- coding: utf-8 -*-
"""
均值回归策略 API 端点
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
from app.models.mean_reversion_strategy import MeanReversionStrategy
from app.schemas.mean_reversion_strategy import (
    MeanReversionStrategyCreate,
    MeanReversionStrategyUpdate,
    MeanReversionStrategyResponse,
    MeanReversionStrategyListResponse,
    MeanReversionStrategyOperationResponse,
    MeanReversionPriceUpdateRequest,
    MeanReversionPriceUpdateResponse,
)
from app.services.strategies.mean_reversion import (
    MeanReversionStrategyService,
    create_mean_reversion_strategy,
    get_mean_reversion_strategy,
    get_user_mean_reversion_strategies,
    delete_mean_reversion_strategy,
    update_mean_reversion_strategy,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/strategies/mean-reversion", tags=["均值回归策略"])


@router.post("/create", response_model=MeanReversionStrategyOperationResponse, status_code=status.HTTP_201_CREATED)
async def create_mean_reversion(
    strategy_data: MeanReversionStrategyCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """创建均值回归策略"""
    try:
        # 验证阈值逻辑
        if strategy_data.sell_threshold <= strategy_data.buy_threshold:
            return error_response(
                message="卖出阈值必须大于买入阈值",
                code="INVALID_THRESHOLDS"
            )
        
        # 创建策略
        strategy = await create_mean_reversion_strategy(
            db=db,
            user_id=current_user.id,
            item_id=strategy_data.item_id,
            name=strategy_data.name,
            mean_period=strategy_data.mean_period,
            mean_type=strategy_data.mean_type,
            buy_threshold=strategy_data.buy_threshold,
            sell_threshold=strategy_data.sell_threshold,
            profit_percentage=strategy_data.profit_percentage,
            stop_loss_percentage=strategy_data.stop_loss_percentage,
            position_size=strategy_data.position_size,
        )
        
        return success_response(
            data={
                "strategy_id": strategy.id,
                "name": strategy.name,
                "status": strategy.status,
            },
            message="均值回归策略创建成功"
        )
        
    except ValueError as e:
        return error_response(message=str(e), code="VALIDATION_ERROR")
    except Exception as e:
        logger.error(f"创建均值回归策略失败: {e}")
        return error_response(message=f"创建失败: {str(e)}", code="CREATE_FAILED")


@router.get("/list", response_model=MeanReversionStrategyListResponse)
async def list_mean_reversion_strategies(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    is_active: Optional[bool] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取用户的均值回归策略列表"""
    
    # 构建过滤条件
    filters = [MeanReversionStrategy.user_id == current_user.id]
    
    if status_filter:
        filters.append(MeanReversionStrategy.status == status_filter)
    if is_active is not None:
        filters.append(MeanReversionStrategy.is_active == is_active)
    
    # 获取总数
    count_query = select(func.count()).select_from(MeanReversionStrategy).where(and_(*filters))
    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0
    
    # 分页查询
    offset = (page - 1) * page_size
    query = (
        select(MeanReversionStrategy)
        .where(and_(*filters))
        .order_by(MeanReversionStrategy.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    
    result = await db.execute(query)
    strategies = result.scalars().all()
    
    return {
        "strategies": [
            MeanReversionStrategyResponse(
                id=s.id,
                user_id=s.user_id,
                item_id=s.item_id,
                name=s.name,
                mean_period=s.mean_period,
                mean_type=s.mean_type,
                buy_threshold=s.buy_threshold,
                sell_threshold=s.sell_threshold,
                profit_percentage=s.profit_percentage,
                stop_loss_percentage=s.stop_loss_percentage,
                position_size=s.position_size,
                is_active=s.is_active,
                status=s.status,
                last_price=s.last_price,
                entry_price=s.entry_price,
                mean_price=s.mean_price,
                total_trades=s.total_trades,
                total_profit=float(s.total_profit),
                winning_trades=s.winning_trades,
                losing_trades=s.losing_trades,
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


@router.get("/{strategy_id}", response_model=MeanReversionStrategyResponse)
async def get_mean_reversion(
    strategy_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取均值回归策略详情"""
    
    # 获取策略
    strategy = await get_mean_reversion_strategy(db, strategy_id)
    
    if not strategy:
        return error_response(message="策略不存在", code="NOT_FOUND")
    
    # 验证所有权
    if strategy.user_id != current_user.id:
        return error_response(message="无权访问此策略", code="FORBIDDEN")
    
    # 获取活跃的策略实例以获取实时状态
    strategy_instance = MeanReversionStrategyService.get_active_strategy(strategy_id)
    
    if strategy_instance:
        status_data = await strategy_instance.get_status()
        return MeanReversionStrategyResponse(
            id=strategy.id,
            user_id=strategy.user_id,
            item_id=strategy.item_id,
            name=strategy.name,
            mean_period=strategy.mean_period,
            mean_type=strategy.mean_type,
            buy_threshold=strategy.buy_threshold,
            sell_threshold=strategy.sell_threshold,
            profit_percentage=strategy.profit_percentage,
            stop_loss_percentage=strategy.stop_loss_percentage,
            position_size=strategy.position_size,
            is_active=strategy.is_active,
            status=strategy.status,
            last_price=status_data.get("last_price"),
            entry_price=status_data.get("entry_price"),
            mean_price=status_data.get("mean_price"),
            total_trades=strategy.total_trades,
            total_profit=float(strategy.total_profit),
            winning_trades=strategy.winning_trades,
            losing_trades=strategy.losing_trades,
            created_at=strategy.created_at,
            updated_at=strategy.updated_at,
            started_at=strategy.started_at,
            stopped_at=strategy.stopped_at,
        )
    
    return MeanReversionStrategyResponse(
        id=strategy.id,
        user_id=strategy.user_id,
        item_id=strategy.item_id,
        name=strategy.name,
        mean_period=strategy.mean_period,
        mean_type=strategy.mean_type,
        buy_threshold=strategy.buy_threshold,
        sell_threshold=strategy.sell_threshold,
        profit_percentage=strategy.profit_percentage,
        stop_loss_percentage=strategy.stop_loss_percentage,
        position_size=strategy.position_size,
        is_active=strategy.is_active,
        status=strategy.status,
        last_price=strategy.last_price,
        entry_price=strategy.entry_price,
        mean_price=strategy.mean_price,
        total_trades=strategy.total_trades,
        total_profit=float(strategy.total_profit),
        winning_trades=strategy.winning_trades,
        losing_trades=strategy.losing_trades,
        created_at=strategy.created_at,
        updated_at=strategy.updated_at,
        started_at=strategy.started_at,
        stopped_at=strategy.stopped_at,
    )


@router.post("/{strategy_id}/start", response_model=MeanReversionStrategyOperationResponse)
async def start_mean_reversion(
    strategy_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """启动均值回归策略"""
    
    # 获取策略
    strategy = await get_mean_reversion_strategy(db, strategy_id)
    
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
        strategy_instance = MeanReversionStrategyService(db, strategy_id)
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
        logger.error(f"启动均值回归策略失败: {e}")
        return error_response(message=f"启动失败: {str(e)}", code="START_FAILED")


@router.post("/{strategy_id}/pause", response_model=MeanReversionStrategyOperationResponse)
async def pause_mean_reversion(
    strategy_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """暂停均值回归策略"""
    
    # 获取策略
    strategy = await get_mean_reversion_strategy(db, strategy_id)
    
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
        strategy_instance = MeanReversionStrategyService.get_active_strategy(strategy_id)
        
        if strategy_instance:
            result = await strategy_instance.pause()
            return result
        else:
            # 如果没有活跃实例，直接更新状态
            strategy.status = "paused"
            await db.commit()
            return success_response(message="策略已暂停")
            
    except Exception as e:
        logger.error(f"暂停均值回归策略失败: {e}")
        return error_response(message=f"暂停失败: {str(e)}", code="PAUSE_FAILED")


@router.post("/{strategy_id}/resume", response_model=MeanReversionStrategyOperationResponse)
async def resume_mean_reversion(
    strategy_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """恢复均值回归策略"""
    
    # 获取策略
    strategy = await get_mean_reversion_strategy(db, strategy_id)
    
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
        strategy_instance = MeanReversionStrategyService(db, strategy_id)
        await strategy_instance.load_strategy(strategy_id)
        result = await strategy_instance.resume()
        
        return result
            
    except Exception as e:
        logger.error(f"恢复均值回归策略失败: {e}")
        return error_response(message=f"恢复失败: {str(e)}", code="RESUME_FAILED")


@router.post("/{strategy_id}/stop", response_model=MeanReversionStrategyOperationResponse)
async def stop_mean_reversion(
    strategy_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """停止均值回归策略"""
    
    # 获取策略
    strategy = await get_mean_reversion_strategy(db, strategy_id)
    
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
        strategy_instance = MeanReversionStrategyService.get_active_strategy(strategy_id)
        
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
        logger.error(f"停止均值回归策略失败: {e}")
        return error_response(message=f"停止失败: {str(e)}", code="STOP_FAILED")


@router.post("/{strategy_id}/price", response_model=MeanReversionPriceUpdateResponse)
async def update_price(
    strategy_id: int,
    price_data: MeanReversionPriceUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """更新价格（触发均值回归交易逻辑）"""
    
    # 获取策略
    strategy = await get_mean_reversion_strategy(db, strategy_id)
    
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
        strategy_instance = MeanReversionStrategyService.get_active_strategy(strategy_id)
        
        if not strategy_instance:
            return error_response(message="策略实例未初始化", code="INSTANCE_NOT_INIT")
        
        # 处理价格更新
        result = await strategy_instance.on_price_update(price_data.price)
        
        return MeanReversionPriceUpdateResponse(
            action=result.get("action", "unknown"),
            current_price=result.get("current_price", price_data.price),
            mean_price=result.get("mean_price"),
            deviation=result.get("deviation"),
            message=result.get("message")
        )
        
    except Exception as e:
        logger.error(f"价格更新失败: {e}")
        return error_response(message=f"价格更新失败: {str(e)}", code="PRICE_UPDATE_FAILED")


@router.delete("/{strategy_id}", response_model=MeanReversionStrategyOperationResponse)
async def delete_mean_reversion(
    strategy_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """删除均值回归策略"""
    
    # 获取策略
    strategy = await get_mean_reversion_strategy(db, strategy_id)
    
    if not strategy:
        return error_response(message="策略不存在", code="NOT_FOUND")
    
    # 验证所有权
    if strategy.user_id != current_user.id:
        return error_response(message="无权访问此策略", code="FORBIDDEN")
    
    try:
        success = await delete_mean_reversion_strategy(db, strategy_id)
        
        if success:
            return success_response(message="策略已删除")
        else:
            return error_response(message="删除失败", code="DELETE_FAILED")
            
    except Exception as e:
        logger.error(f"删除均值回归策略失败: {e}")
        return error_response(message=f"删除失败: {str(e)}", code="DELETE_FAILED")


@router.put("/{strategy_id}", response_model=MeanReversionStrategyOperationResponse)
async def update_mean_reversion(
    strategy_id: int,
    strategy_data: MeanReversionStrategyUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """更新均值回归策略"""
    
    # 获取策略
    strategy = await get_mean_reversion_strategy(db, strategy_id)
    
    if not strategy:
        return error_response(message="策略不存在", code="NOT_FOUND")
    
    # 验证所有权
    if strategy.user_id != current_user.id:
        return error_response(message="无权访问此策略", code="FORBIDDEN")
    
    # 检查状态
    if strategy.status != "pending":
        return error_response(message="只能更新pending状态的策略", code="INVALID_STATE")
    
    try:
        # 验证阈值逻辑
        buy_threshold = strategy_data.buy_threshold if strategy_data.buy_threshold else strategy.buy_threshold
        sell_threshold = strategy_data.sell_threshold if strategy_data.sell_threshold else strategy.sell_threshold
        
        if sell_threshold <= buy_threshold:
            return error_response(
                message="卖出阈值必须大于买入阈值",
                code="INVALID_THRESHOLDS"
            )
        
        # 更新策略
        updated_strategy = await update_mean_reversion_strategy(
            db=db,
            strategy_id=strategy_id,
            user_id=current_user.id,
            name=strategy_data.name,
            mean_period=strategy_data.mean_period,
            mean_type=strategy_data.mean_type,
            buy_threshold=strategy_data.buy_threshold,
            sell_threshold=strategy_data.sell_threshold,
            profit_percentage=strategy_data.profit_percentage,
            stop_loss_percentage=strategy_data.stop_loss_percentage,
            position_size=strategy_data.position_size,
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
        logger.error(f"更新均值回归策略失败: {e}")
        return error_response(message=f"更新失败: {str(e)}", code="UPDATE_FAILED")


@router.get("/{strategy_id}/status")
async def get_mean_reversion_status(
    strategy_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取均值回归策略实时状态"""
    
    # 获取策略
    strategy = await get_mean_reversion_strategy(db, strategy_id)
    
    if not strategy:
        return error_response(message="策略不存在", code="NOT_FOUND")
    
    # 验证所有权
    if strategy.user_id != current_user.id:
        return error_response(message="无权访问此策略", code="FORBIDDEN")
    
    try:
        # 获取活跃策略实例
        strategy_instance = MeanReversionStrategyService.get_active_strategy(strategy_id)
        
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
                    "mean_price": strategy.mean_price,
                    "total_trades": strategy.total_trades,
                    "total_profit": float(strategy.total_profit),
                    "winning_trades": strategy.winning_trades,
                    "losing_trades": strategy.losing_trades,
                }
            )
        
    except Exception as e:
        logger.error(f"获取状态失败: {e}")
        return error_response(message=f"获取状态失败: {str(e)}", code="STATUS_FAILED")
