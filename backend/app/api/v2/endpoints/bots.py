# -*- coding: utf-8 -*-
"""
机器人端点 v2
增强版 - 完整的CRUD操作和启动/停止控制
"""
import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, status, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update, delete
from datetime import datetime

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.bot import Bot, BotTrade
from app.schemas.bot import (
    BotCreate,
    BotUpdate,
    BotResponse,
    BotLoginRequest,
    BotLoginResponse,
    BotInventoryResponse,
    BotInventoryItem,
    BotTradeResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/online")
async def get_online_bots(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """获取所有在线机器人 v2"""
    result = await db.execute(
        select(Bot).where(
            Bot.owner_id == current_user.id,
            Bot.status == 'online'
        )
    )
    bots = result.scalars().all()
    return bots


@router.post("/batch-status")
async def batch_update_bot_status(
    status: str = Query(..., description="目标状态: online/offline/error"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """批量更新机器人状态 v2"""
    if status not in ['online', 'offline', 'error', 'maintenance']:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="无效的状态值"
        )
    
    result = await db.execute(
        select(Bot).where(Bot.owner_id == current_user.id)
    )
    bots = result.scalars().all()
    
    updated_count = 0
    for bot in bots:
        bot.status = status
        bot.updated_at = datetime.utcnow()
        updated_count += 1
    
    await db.commit()
    
    return {
        "success": True,
        "updated": updated_count,
        "status": status
    }


@router.get("/stats/summary")
async def get_bots_summary(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """获取机器人统计摘要 v2"""
    # 统计各状态的机器人数量
    result = await db.execute(
        select(Bot.status, func.count(Bot.id))
        .where(Bot.owner_id == current_user.id)
        .group_by(Bot.status)
    )
    
    status_counts = {row[0]: row[1] for row in result.all()}
    
    # 总数
    total_result = await db.execute(
        select(func.count(Bot.id)).where(Bot.owner_id == current_user.id)
    )
    total = total_result.scalar() or 0
    
    return {
        "total": total,
        "online": status_counts.get('online', 0),
        "offline": status_counts.get('offline', 0),
        "error": status_counts.get('error', 0),
        "maintenance": status_counts.get('maintenance', 0)
    }


@router.get("/", response_model=List[BotResponse])
async def get_bots(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """获取机器人列表 v2"""
    query = select(Bot).where(Bot.owner_id == current_user.id)
    
    if status_filter:
        query = query.where(Bot.status == status_filter)
    
    query = query.offset(skip).limit(limit).order_by(Bot.created_at.desc())
    result = await db.execute(query)
    bots = result.scalars().all()
    
    return bots


@router.post("/", response_model=BotResponse, status_code=status.HTTP_201_CREATED)
async def create_bot(
    bot_data: BotCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """创建机器人 v2"""
    # 检查Steam ID是否已存在
    result = await db.execute(
        select(Bot).where(
            Bot.steam_id == bot_data.steam_id,
            Bot.owner_id == current_user.id
        )
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该Steam ID的机器人已存在"
        )
    
    bot = Bot(
        name=bot_data.name,
        steam_id=bot_data.steam_id,
        username=bot_data.username,
        session_token=bot_data.session_token,
        ma_file=bot_data.ma_file,
        access_token=bot_data.access_token,
        owner_id=current_user.id,
        status='offline'
    )
    db.add(bot)
    await db.commit()
    await db.refresh(bot)
    
    return bot


@router.get("/{bot_id}", response_model=BotResponse)
async def get_bot(
    bot_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """获取单个机器人详情 v2"""
    result = await db.execute(
        select(Bot).where(
            Bot.id == bot_id,
            Bot.owner_id == current_user.id
        )
    )
    bot = result.scalar_one_or_none()
    
    if not bot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="机器人不存在"
        )
    
    return bot


@router.put("/{bot_id}", response_model=BotResponse)
async def update_bot(
    bot_id: int,
    bot_data: BotUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """更新机器人 v2"""
    result = await db.execute(
        select(Bot).where(
            Bot.id == bot_id,
            Bot.owner_id == current_user.id
        )
    )
    bot = result.scalar_one_or_none()
    
    if not bot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="机器人不存在"
        )
    
    # 更新字段
    update_data = bot_data.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(bot, key, value)
    
    bot.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(bot)
    
    return bot


@router.delete("/{bot_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_bot(
    bot_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """删除机器人 v2"""
    result = await db.execute(
        select(Bot).where(
            Bot.id == bot_id,
            Bot.owner_id == current_user.id
        )
    )
    bot = result.scalar_one_or_none()
    
    if not bot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="机器人不存在"
        )
    
    # 检查机器人是否在线
    if bot.status == 'online':
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请先停止机器人再删除"
        )
    
    await db.delete(bot)
    await db.commit()
    
    return None


@router.post("/{bot_id}/start", response_model=BotResponse)
async def start_bot(
    bot_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """启动机器人 v2"""
    result = await db.execute(
        select(Bot).where(
            Bot.id == bot_id,
            Bot.owner_id == current_user.id
        )
    )
    bot = result.scalar_one_or_none()
    
    if not bot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="机器人不存在"
        )
    
    if bot.status == 'online':
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="机器人已在运行中"
        )
    
    # 验证认证信息
    if not bot.session_token and not bot.ma_file:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="机器人缺少认证信息"
        )

    # 实现实际的机器人启动逻辑
    try:
        # 使用 SteamTrade 服务启动机器人连接
        from app.services.steam_service import SteamTrade
        
        steam_trade = SteamTrade(
            steam_id=bot.steam_id or "",
            session_token=bot.session_token,
            ma_file=bot.ma_file
        )
        
        # 尝试登录
        login_success = await steam_trade.login()
        
        if not login_success:
            bot.status = 'error'
            bot.last_error = "登录失败，请检查认证信息"
            await db.commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="机器人登录失败，请检查认证信息"
            )
        
        # 登录成功，更新状态
        bot.status = 'online'
        bot.last_online = datetime.utcnow()
        bot.last_activity = datetime.utcnow()
        bot.last_error = None  # 清除之前的错误
        bot.updated_at = datetime.utcnow()
        
        await db.commit()
        await db.refresh(bot)
        
        logger.info(f"机器人 {bot.name} (ID: {bot.id}) 启动成功")
        
        return bot
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"机器人启动失败: {e}")
        bot.status = 'error'
        bot.last_error = str(e)
        await db.commit()
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"机器人启动失败: {str(e)}"
        )


@router.post("/{bot_id}/stop", response_model=BotResponse)
async def stop_bot(
    bot_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """停止机器人 v2"""
    result = await db.execute(
        select(Bot).where(
            Bot.id == bot_id,
            Bot.owner_id == current_user.id
        )
    )
    bot = result.scalar_one_or_none()
    
    if not bot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="机器人不存在"
        )
    
    if bot.status == 'offline':
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="机器人已停止"
        )
    
    # 实现实际的机器人停止逻辑
    try:
        # 清理敏感数据（安全退出）
        bot.clear_sensitive_data()
        
        # 更新状态
        bot.status = 'offline'
        bot.last_activity = datetime.utcnow()
        bot.updated_at = datetime.utcnow()
        
        await db.commit()
        await db.refresh(bot)
        
        logger.info(f"机器人 {bot.name} (ID: {bot.id}) 已停止")
        
        return bot
        
    except Exception as e:
        logger.error(f"机器人停止失败: {e}")
        bot.status = 'error'
        bot.last_error = str(e)
        await db.commit()
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"机器人停止失败: {str(e)}"
        )


@router.post("/{bot_id}/restart", response_model=BotResponse)
async def restart_bot(
    bot_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """重启机器人 v2"""
    # 先停止
    result = await db.execute(
        select(Bot).where(
            Bot.id == bot_id,
            Bot.owner_id == current_user.id
        )
    )
    bot = result.scalar_one_or_none()
    
    if not bot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="机器人不存在"
        )
    
    # 重启逻辑
    bot.status = 'online'
    bot.last_online = datetime.utcnow()
    bot.updated_at = datetime.utcnow()
    
    await db.commit()
    await db.refresh(bot)
    
    return bot


@router.get("/{bot_id}/inventory", response_model=BotInventoryResponse)
async def get_bot_inventory(
    bot_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """获取机器人库存 v2"""
    result = await db.execute(
        select(Bot).where(
            Bot.id == bot_id,
            Bot.owner_id == current_user.id
        )
    )
    bot = result.scalar_one_or_none()
    
    if not bot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="机器人不存在"
        )
    
    # 实现实际的库存获取逻辑
    # 从 Steam API 或数据库获取库存
    try:
        from app.services.steam_service import SteamTrade
        from app.models.item import Item
        
        items = []
        
        # 如果机器人在线，从 Steam API 获取实时库存
        if bot.status == 'online' and bot.session_token:
            try:
                steam_trade = SteamTrade(
                    steam_id=bot.steam_id or "",
                    session_token=bot.session_token,
                    ma_file=bot.ma_file
                )
                
                # 获取 Steam 库存
                steam_inventory = await steam_trade.get_inventory(
                    app_id=730,  # CS2
                    context_id=2
                )
                
                # 转换为响应格式并关联本地物品数据
                for inv_item in steam_inventory:
                    # 尝试从本地数据库获取物品信息
                    item_result = await db.execute(
                        select(Item).where(
                            Item.class_id == str(inv_item.get('classid', ''))
                        )
                    )
                    local_item = item_result.scalar_one_or_none()
                    
                    items.append(BotInventoryItem(
                        asset_id=str(inv_item.get('assetid', '')),
                        class_id=str(inv_item.get('classid', '')),
                        instance_id=str(inv_item.get('instanceid', '')),
                        amount=int(inv_item.get('amount', 1)),
                        name=local_item.name if local_item else inv_item.get('name', 'Unknown'),
                        market_hash_name=local_item.market_hash_name if local_item else inv_item.get('market_hash_name', ''),
                        price=local_item.current_price if local_item else None,
                        float_value=inv_item.get('float_value')
                    ))
                    
            except Exception as e:
                logger.warning(f"从Steam API获取库存失败，使用本地数据: {e}")
        
        # 如果没有获取到库存或机器人不在线，从本地数据库获取
        if not items:
            # 查询用户库存（通过 bot 关联的用户）
            from app.models.inventory import Inventory
            inventory_result = await db.execute(
                select(Inventory, Item).join(
                    Item, Inventory.item_id == Item.id
                ).where(
                    Inventory.user_id == bot.owner_id
                ).offset(skip).limit(limit)
            )
            
            for inv, item in inventory_result.all():
                items.append(BotInventoryItem(
                    asset_id=inv.asset_id or '',
                    class_id=inv.class_id or '',
                    instance_id=inv.instance_id or '',
                    amount=inv.amount,
                    name=item.name,
                    market_hash_name=item.market_hash_name,
                    price=float(item.current_price) if item.current_price else None,
                    float_value=inv.float_value
                ))
        
        return BotInventoryResponse(
            bot_id=bot_id,
            items=items,
            total_count=len(items)
        )
        
    except Exception as e:
        logger.error(f"获取库存失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取库存失败: {str(e)}"
        )


@router.get("/{bot_id}/trades", response_model=List[BotTradeResponse])
async def get_bot_trades(
    bot_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """获取机器人交易记录 v2"""
    result = await db.execute(
        select(Bot).where(
            Bot.id == bot_id,
            Bot.owner_id == current_user.id
        )
    )
    bot = result.scalar_one_or_none()
    
    if not bot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="机器人不存在"
        )
    
    query = select(BotTrade).where(BotTrade.bot_id == bot_id)
    
    if status_filter:
        query = query.where(BotTrade.status == status_filter)
    
    query = query.offset(skip).limit(limit).order_by(BotTrade.created_at.desc())
    result = await db.execute(query)
    trades = result.scalars().all()
    
    return trades
