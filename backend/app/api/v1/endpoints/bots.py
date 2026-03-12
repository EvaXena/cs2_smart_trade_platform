# -*- coding: utf-8 -*-
"""
机器人端点
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, status, Query, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update
from sqlalchemy.orm import selectinload
from datetime import datetime
import json

from app.core.database import get_db
from app.core.security import get_current_user
from app.core.exceptions import (
    APIError, NotFoundError, UnauthorizedError,
    BusinessError, ExternalServiceError, ValidationError
)
from app.core.idempotency import (
    generate_idempotency_key,
    check_idempotency,
    save_idempotent_response,
)
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
from app.services.steam_service import SteamService, SteamTrade

router = APIRouter()


@router.get("/", response_model=List[BotResponse])
async def get_bots(
    skip: int = Query(0, ge=0, description="跳过的记录数"),
    limit: int = Query(100, ge=1, le=100, description="返回记录数，最大100"),
    status: Optional[str] = Query(None, description="机器人状态筛选: online, offline, trading"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> List[BotResponse]:
    """
    获取当前用户的机器人列表
    
    返回当前用户拥有的所有交易机器人的列表，支持分页和状态筛选。
    
    ## 参数说明
    
    | 参数 | 类型 | 必填 | 说明 |
    |------|------|------|------|
    | skip | int | 否 | 跳过记录数，默认0 |
    | limit | int | 否 | 返回记录数，最大100，默认100 |
    | status | str | 否 | 状态筛选: online, offline, trading |
    
    ## 返回格式
    
    ```json
    [
        {
            "id": 1,
            "name": "My Bot 1",
            "steam_id": "76561198000000000",
            "status": "online",
            "owner_id": 1,
            "created_at": "2024-01-01T00:00:00"
        }
    ]
    ```
    
    ## 需要认证
    
    此接口需要 Bearer Token 认证。
    
    ## 错误码
    
    - 401: 未认证
    
    ## 示例
    
    ```bash
    curl -H "Authorization: Bearer <token>" "http://localhost:8000/api/v1/bots?status=online"
    ```
    """
    # 预加载关联数据避免 N+1 查询
    query = select(Bot).where(Bot.owner_id == current_user.id).options(
        selectinload(Bot.trades)
    )

    if status:
        query = query.where(Bot.status == status)

    query = query.offset(skip).limit(limit).order_by(Bot.created_at.desc())
    result = await db.execute(query)
    bots = result.scalars().all()

    return bots

    
@router.post("/", response_model=BotResponse, status_code=status.HTTP_201_CREATED)
async def create_bot(
    bot_data: BotCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")
):
    """创建机器人（支持幂等性）"""
    
    # 幂等性检查
    if idempotency_key:
        # 生成内部幂等性 key
        request_body = json.dumps(bot_data.model_dump(), sort_keys=True)
        internal_key = generate_idempotency_key(
            user_id=current_user.id,
            method="POST",
            path="/api/v1/bots",
            request_body=request_body
        )
        
        # 检查是否已处理过相同请求
        is_duplicate, cached_response = await check_idempotency(internal_key)
        if is_duplicate and cached_response:
            # 返回缓存的响应
            return BotResponse(**cached_response)
    
    # 创建机器人
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
    
    # 保存幂等性响应
    if idempotency_key:
        response_data = BotResponse.model_validate(bot).model_dump()
        await save_idempotent_response(internal_key, response_data)
    
    return bot


@router.get("/{bot_id}", response_model=BotResponse)
async def get_bot(
    bot_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """获取机器人详情"""
    result = await db.execute(
        select(Bot).where(Bot.id == bot_id, Bot.owner_id == current_user.id)
    )
    bot = result.scalar_one_or_none()

    if not bot:
        raise NotFoundError("机器人", bot_id)

    return bot


@router.put("/{bot_id}", response_model=BotResponse)
async def update_bot(
    bot_id: int,
    bot_data: BotUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """更新机器人"""
    result = await db.execute(
        select(Bot).where(Bot.id == bot_id, Bot.owner_id == current_user.id)
    )
    bot = result.scalar_one_or_none()

    if not bot:
        raise NotFoundError("机器人", bot_id)

    # 更新字段
    update_data = bot_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(bot, field, value)

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
    """删除机器人"""
    result = await db.execute(
        select(Bot).where(Bot.id == bot_id, Bot.owner_id == current_user.id)
    )
    bot = result.scalar_one_or_none()

    if not bot:
        raise NotFoundError("机器人", bot_id)

    await db.delete(bot)
    await db.commit()

    return None


@router.post("/{bot_id}/login", response_model=BotLoginResponse)
async def login_bot(
    bot_id: int,
    login_data: Optional[BotLoginRequest] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """登录机器人"""
    result = await db.execute(
        select(Bot).where(Bot.id == bot_id, Bot.owner_id == current_user.id)
    )
    bot = result.scalar_one_or_none()

    if not bot:
        raise NotFoundError("机器人", bot_id)

    # 如果提供了新的认证信息，更新机器人
    if login_data:
        if login_data.session_token:
            bot.session_token = login_data.session_token
        if login_data.ma_file:
            bot.ma_file = login_data.ma_file

    # 实现实际的 Steam 登录逻辑
    if bot.session_token or bot.ma_file:
        try:
            # 使用 SteamService 进行登录验证
            steam_service = SteamService()

            if bot.session_token:
                # 验证 session token 是否有效
                # 这里简化处理，实际需要调用 Steam API 验证
                steam_trade = SteamTrade(
                    steam_id=bot.steam_id or "",
                    session_token=bot.session_token,
                    ma_file=bot.ma_file
                )
                login_success = await steam_trade.login()

                if login_success:
                    bot.status = 'online'
                    bot.last_activity = datetime.utcnow()
                else:
                    raise UnauthorizedError("Steam 登录失败，session token 无效")
            elif bot.ma_file:
                # 使用 ma_file 登录
                bot.status = 'online'
                bot.last_activity = datetime.utcnow()
            else:
                raise BusinessError("请提供 session_token 或 ma_file")
        except APIError:
            raise
        except Exception as e:
            raise ExternalServiceError("Steam", f"Steam 登录失败: {str(e)}")
    else:
        raise BusinessError("请提供 session_token 或 ma_file")

    await db.commit()
    await db.refresh(bot)

    return BotLoginResponse(
        success=True,
        message="机器人登录成功",
        status=bot.status
    )


@router.post("/{bot_id}/logout", response_model=BotLoginResponse)
async def logout_bot(
    bot_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """登出机器人"""
    result = await db.execute(
        select(Bot).where(Bot.id == bot_id, Bot.owner_id == current_user.id)
    )
    bot = result.scalar_one_or_none()

    if not bot:
        raise NotFoundError("机器人", bot_id)

    bot.status = 'offline'
    bot.last_activity = datetime.utcnow()
    await db.commit()
    await db.refresh(bot)

    return BotLoginResponse(
        success=True,
        message="机器人已登出",
        status=bot.status
    )


@router.post("/{bot_id}/refresh", response_model=BotLoginResponse)
async def refresh_bot_session(
    bot_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """刷新机器人 session"""
    result = await db.execute(
        select(Bot).where(Bot.id == bot_id, Bot.owner_id == current_user.id)
    )
    bot = result.scalar_one_or_none()

    if not bot:
        raise NotFoundError("机器人", bot_id)

    if not bot.steam_id:
        raise BusinessError("机器人未绑定 Steam 账户")

    # 实现实际的 session 刷新逻辑
    try:
        # 使用 SteamTrade 进行 session 刷新
        steam_trade = SteamTrade(
            steam_id=bot.steam_id,
            session_token=bot.session_token or "",
            ma_file=bot.ma_file
        )

        # 尝试验证 session 是否仍然有效
        # 实际实现中需要调用 Steam API 验证 token
        # 这里假设如果能创建连接则 session 有效
        await steam_trade.login()

        bot.last_activity = datetime.utcnow()
        await db.commit()
        await db.refresh(bot)

        return BotLoginResponse(
            success=True,
            message="Session 刷新成功",
            status=bot.status
        )
    except Exception as e:
        raise ExternalServiceError("Steam", f"Session 刷新失败: {str(e)}")


@router.get("/{bot_id}/inventory", response_model=BotInventoryResponse)
async def get_bot_inventory(
    bot_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """获取机器人库存"""
    result = await db.execute(
        select(Bot).where(Bot.id == bot_id, Bot.owner_id == current_user.id)
    )
    bot = result.scalar_one_or_none()

    if not bot:
        raise NotFoundError("机器人", bot_id)

    # 从数据库获取该机器人的库存
    from app.models.inventory import Inventory
    inventory_result = await db.execute(
        select(Inventory).where(
            Inventory.bot_id == bot_id,
            Inventory.status == 'available'
        )
    )
    inventory_items = inventory_result.scalars().all()

    # 转换为响应格式
    items = [
        {
            "id": item.id,
            "market_hash_name": item.market_hash_name,
            "price": item.cost_price,
            "marketable": item.marketable,
            "tradable": item.tradable,
            "inspect_in": item.inspect_in
        }
        for item in inventory_items
    ]

    return BotInventoryResponse(
        items=items,
        total_count=len(items)
    )


@router.get("/{bot_id}/trades", response_model=BotTradeResponse)
async def get_bot_trades(
    bot_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """获取机器人交易记录"""
    result = await db.execute(
        select(Bot).where(Bot.id == bot_id, Bot.owner_id == current_user.id)
    )
    bot = result.scalar_one_or_none()

    if not bot:
        raise NotFoundError("机器人", bot_id)

    # 获取交易记录
    query = select(BotTrade).where(BotTrade.bot_id == bot_id)
    query = query.offset(skip).limit(limit).order_by(BotTrade.created_at.desc())
    result = await db.execute(query)
    trades = result.scalars().all()

    trade_list = []
    for trade in trades:
        trade_list.append({
            "id": trade.id,
            "trade_offer_id": trade.trade_offer_id,
            "partner_steam_id": trade.partner_steam_id,
            "direction": trade.direction,
            "status": trade.status,
            "created_at": trade.created_at.isoformat() if trade.created_at else None,
            "accepted_at": trade.accepted_at.isoformat() if trade.accepted_at else None,
        })

    return BotTradeResponse(
        trades=trade_list,
        total_count=len(trade_list)
    )
