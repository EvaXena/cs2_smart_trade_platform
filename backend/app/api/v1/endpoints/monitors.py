# -*- coding: utf-8 -*-
"""
监控端点
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import datetime

from app.core.database import get_db
from app.core.security import get_current_user
from app.core.exceptions import (
    APIError, NotFoundError, UnauthorizedError, 
    BusinessError, ValidationError, ConflictError
)
from app.models.user import User
from app.models.monitor import MonitorTask, MonitorLog
from app.schemas.monitor import (
    MonitorCreate,
    MonitorUpdate,
    MonitorResponse,
    MonitorListResponse,
    MonitorLogResponse,
    MonitorLogListResponse,
    MonitorActionResponse,
)

router = APIRouter()


@router.get("/", response_model=MonitorListResponse)
async def get_monitors(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    enabled: Optional[bool] = None,
    task_status: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """获取监控任务列表"""
    query = select(MonitorTask).where(MonitorTask.user_id == current_user.id)
    
    if enabled is not None:
        query = query.where(MonitorTask.enabled == enabled)
    
    if task_status:
        query = query.where(MonitorTask.status == task_status)
    
    # 获取总数
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar()
    
    query = query.offset(skip).limit(limit).order_by(MonitorTask.created_at.desc())
    result = await db.execute(query)
    monitors = result.scalars().all()
    
    return MonitorListResponse(
        items=[MonitorResponse.model_validate(m) for m in monitors],
        total=total
    )


@router.post("/", response_model=MonitorResponse, status_code=status.HTTP_201_CREATED)
async def create_monitor(
    monitor_data: MonitorCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """创建监控任务"""
    monitor = MonitorTask(
        name=monitor_data.name,
        description=monitor_data.description,
        item_id=monitor_data.item_id,
        item_pattern=monitor_data.item_pattern,
        condition_type=monitor_data.condition_type,
        threshold=monitor_data.threshold,
        notify_enabled=monitor_data.notify_enabled,
        notify_telegram=monitor_data.notify_telegram,
        notify_email=monitor_data.notify_email,
        notify_webhook=monitor_data.notify_webhook,
        webhook_url=monitor_data.webhook_url,
        action=monitor_data.action,
        user_id=current_user.id,
        enabled=True,
        status='idle'
    )
    db.add(monitor)
    await db.commit()
    await db.refresh(monitor)
    
    return monitor


@router.get("/{monitor_id}", response_model=MonitorResponse)
async def get_monitor(
    monitor_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """获取监控任务详情"""
    result = await db.execute(
        select(MonitorTask).where(
            MonitorTask.id == monitor_id,
            MonitorTask.user_id == current_user.id
        )
    )
    monitor = result.scalar_one_or_none()
    
    if not monitor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="监控任务不存在"
        )
    
    return monitor


@router.put("/{monitor_id}", response_model=MonitorResponse)
async def update_monitor(
    monitor_id: int,
    monitor_data: MonitorUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """更新监控任务"""
    result = await db.execute(
        select(MonitorTask).where(
            MonitorTask.id == monitor_id,
            MonitorTask.user_id == current_user.id
        )
    )
    monitor = result.scalar_one_or_none()
    
    if not monitor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="监控任务不存在"
        )
    
    # 更新字段
    update_data = monitor_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(monitor, field, value)
    
    monitor.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(monitor)
    
    return monitor


@router.delete("/{monitor_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_monitor(
    monitor_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """删除监控任务"""
    result = await db.execute(
        select(MonitorTask).where(
            MonitorTask.id == monitor_id,
            MonitorTask.user_id == current_user.id
        )
    )
    monitor = result.scalar_one_or_none()
    
    if not monitor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="监控任务不存在"
        )
    
    await db.delete(monitor)
    await db.commit()
    
    return None


@router.post("/{monitor_id}/start", response_model=MonitorActionResponse)
async def start_monitor(
    monitor_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """启动监控任务"""
    result = await db.execute(
        select(MonitorTask).where(
            MonitorTask.id == monitor_id,
            MonitorTask.user_id == current_user.id
        )
    )
    monitor = result.scalar_one_or_none()
    
    if not monitor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="监控任务不存在"
        )
    
    if not monitor.enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="监控任务已被禁用"
        )
    
    # 启动实际的监控任务
    try:
        # 导入监控服务
        from app.services.monitor_service import get_price_monitor
        
        price_monitor = get_price_monitor(db)
        
        # 创建监控任务
        await price_monitor.create_monitor_task(
            name=monitor.name,
            item_id=monitor.item_id,
            condition_type=monitor.condition_type,
            threshold=float(monitor.threshold),
            action=monitor.action,
            user_id=current_user.id
        )
        
        # 启动监控
        await price_monitor.start()
        
        # 更新任务状态
        monitor.status = 'running'
        monitor.updated_at = datetime.utcnow()
        await db.commit()
        
        return MonitorActionResponse(
            success=True,
            message="监控任务已启动",
            status=monitor.status
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"启动监控任务失败: {str(e)}"
        )


@router.post("/{monitor_id}/stop", response_model=MonitorActionResponse)
async def stop_monitor(
    monitor_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """停止监控任务"""
    result = await db.execute(
        select(MonitorTask).where(
            MonitorTask.id == monitor_id,
            MonitorTask.user_id == current_user.id
        )
    )
    monitor = result.scalar_one_or_none()
    
    if not monitor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="监控任务不存在"
        )
    
    # 停止实际的监控任务
    try:
        # 导入监控服务
        from app.services.monitor_service import get_price_monitor
        
        price_monitor = get_price_monitor(db)
        
        # 停止监控
        await price_monitor.stop()
        
        # 更新任务状态
        monitor.status = 'idle'
        monitor.updated_at = datetime.utcnow()
        await db.commit()
        
        return MonitorActionResponse(
            success=True,
            message="监控任务已停止",
            status=monitor.status
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"停止监控任务失败: {str(e)}"
        )
    monitor.updated_at = datetime.utcnow()
    await db.commit()
    
    return MonitorActionResponse(
        success=True,
        message="监控任务已停止",
        status=monitor.status
    )


@router.get("/{monitor_id}/logs", response_model=MonitorLogListResponse)
async def get_monitor_logs(
    monitor_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """获取监控日志"""
    # 验证监控任务属于当前用户
    result = await db.execute(
        select(MonitorTask).where(
            MonitorTask.id == monitor_id,
            MonitorTask.user_id == current_user.id
        )
    )
    monitor = result.scalar_one_or_none()
    
    if not monitor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="监控任务不存在"
        )
    
    # 获取日志
    query = select(MonitorLog).where(MonitorLog.task_id == monitor_id)
    
    # 获取总数
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar()
    
    query = query.offset(skip).limit(limit).order_by(MonitorLog.created_at.desc())
    result = await db.execute(query)
    logs = result.scalars().all()
    
    return MonitorLogListResponse(
        logs=[MonitorLogResponse.model_validate(log) for log in logs],
        total=total
    )
