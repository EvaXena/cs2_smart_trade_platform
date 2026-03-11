# -*- coding: utf-8 -*-
"""
Steam 市场端点
处理 Steam 市场的挂单操作
"""
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.inventory import Inventory, Listing
from app.models.bot import Bot
from app.services.steam_service import SteamTrade
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter()


# ========== Schema ==========

class CreateListingRequest(BaseModel):
    """创建挂单请求"""
    inventory_id: int = Field(..., description="库存ID")
    price: float = Field(..., gt=0, description="价格（元）")
    platform: str = Field(default="steam", description="平台")


class CreateListingResponse(BaseModel):
    """创建挂单响应"""
    success: bool
    listing_id: Optional[str] = None
    inventory_id: int
    price: float
    message: str


class CancelListingRequest(BaseModel):
    """取消挂单请求"""
    listing_id: int = Field(..., description="挂单ID")


class CancelListingResponse(BaseModel):
    """取消挂单响应"""
    success: bool
    listing_id: int
    message: str


class MyListingItem(BaseModel):
    """我的挂单项"""
    listing_id: int
    inventory_id: int
    asset_id: Optional[str] = None
    item_name: str
    price: float
    status: str
    listed_at: str


class MyListingsResponse(BaseModel):
    """我的挂单列表响应"""
    success: bool
    listings: list[MyListingItem]
    total: int


# ========== 辅助函数 ==========

async def get_user_steam_trade(
    user: User,
    db: AsyncSession
) -> Optional[SteamTrade]:
    """获取用户的 Steam Trade 实例"""
    # 获取用户的机器人
    bot_result = await db.execute(
        select(Bot).where(
            Bot.owner_id == user.id,
            Bot.status == 'online'
        ).limit(1)
    )
    bot = bot_result.scalar_one_or_none()
    
    if not bot or not bot.session_token:
        # 尝试从用户配置获取
        if hasattr(user, 'steam_session_token') and user.steam_session_token:
            return SteamTrade(
                steam_id=user.steam_id or "",
                session_token=user.steam_session_token
            )
        return None
    
    return SteamTrade(
        steam_id=bot.steam_id or "",
        session_token=bot.session_token,
        ma_file=bot.ma_file
    )


# ========== 路由 ==========

@router.post("/listings", response_model=CreateListingResponse)
async def create_market_listing(
    request: CreateListingRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    创建市场挂单
    
    在 Steam 市场上架饰品
    """
    if request.platform != "steam":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="当前仅支持 Steam 平台"
        )
    
    # 验证库存存在且属于当前用户
    inv_result = await db.execute(
        select(Inventory).where(
            Inventory.id == request.inventory_id,
            Inventory.user_id == current_user.id
        )
    )
    inventory = inv_result.scalar_one_or_none()
    
    if not inventory:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="库存不存在"
        )
    
    if inventory.status != 'available':
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="库存物品当前不可上架"
        )
    
    if not inventory.asset_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="库存物品缺少 asset_id，无法上架到市场"
        )
    
    # 获取 Steam Trade 实例
    steam_trade = await get_user_steam_trade(current_user, db)
    
    if not steam_trade:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="未配置 Steam 账户，无法创建挂单"
        )
    
    try:
        # 调用 Steam API 创建挂单
        result = await steam_trade.create_listing(
            asset_id=inventory.asset_id,
            app_id=730,  # CS2
            price=request.price,
            quantity=1
        )
        
        if not result.get("success", False):
            # 创建本地记录（即使API失败也记录）
            error_msg = result.get("error", "未知错误")
            
            # 创建本地挂单记录（标记为失败状态）
            listing = Listing(
                inventory_id=inventory.id,
                listing_id=None,
                price=request.price,
                platform="steam",
                status="failed",
            )
            db.add(listing)
            
            # 更新库存状态
            inventory.status = 'listing_failed'
            
            await db.commit()
            
            return CreateListingResponse(
                success=False,
                listing_id=None,
                inventory_id=inventory.id,
                price=request.price,
                message=f"Steam API 调用失败: {error_msg}"
            )
        
        # 创建本地挂单记录
        listing = Listing(
            inventory_id=inventory.id,
            listing_id=result.get("listing_id"),
            price=request.price,
            platform="steam",
            status="listing"
        )
        db.add(listing)
        
        # 更新库存状态
        inventory.status = 'listing'
        
        await db.commit()
        await db.refresh(listing)
        
        return CreateListingResponse(
            success=True,
            listing_id=result.get("listing_id"),
            inventory_id=inventory.id,
            price=request.price,
            message="挂单创建成功"
        )
        
    except Exception as e:
        logger.error(f"创建挂单异常: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"创建挂单失败: {str(e)}"
        )


@router.delete("/listings/{listing_id}", response_model=CancelListingResponse)
async def cancel_market_listing(
    listing_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    取消市场挂单
    
    从 Steam 市场下架饰品
    """
    # 验证挂单存在
    listing_result = await db.execute(
        select(Listing, Inventory).join(Inventory).where(
            Listing.id == listing_id,
            Listing.platform == "steam",
            Listing.status == "listing"
        )
    )
    row = listing_result.first()
    
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="挂单不存在或已取消"
        )
    
    listing, inventory = row
    
    # 验证权限
    if inventory.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权操作此挂单"
        )
    
    # 如果有 Steam listing_id，尝试调用 Steam API 取消
    if listing.listing_id:
        steam_trade = await get_user_steam_trade(current_user, db)
        
        if steam_trade:
            try:
                result = await steam_trade.cancel_listing(
                    listing_id=listing.listing_id,
                    app_id=730
                )
                
                if not result.get("success", False):
                    logger.warning(f"取消Steam挂单失败: {result.get('error')}")
                    # 继续执行本地状态更新
            except Exception as e:
                logger.error(f"取消Steam挂单异常: {e}")
    
    # 更新本地状态
    listing.status = "cancelled"
    inventory.status = "available"
    
    await db.commit()
    
    return CancelListingResponse(
        success=True,
        listing_id=listing_id,
        message="挂单已取消"
    )


@router.get("/listings", response_model=MyListingsResponse)
async def get_my_listings(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    获取我的挂单列表
    """
    # 获取用户的挂单记录
    offset = (page - 1) * limit
    
    # 查询挂单和关联的库存
    from sqlalchemy import func
    
    # 基础查询
    query = select(Listing, Inventory).join(
        Inventory, Listing.inventory_id == Inventory.id
    ).where(
        Inventory.user_id == current_user.id,
        Listing.platform == "steam",
        Listing.status.in_(["listing", "sold", "cancelled"])
    )
    
    # 获取总数
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    
    # 分页查询
    query = query.order_by(Listing.listed_at.desc()).offset(offset).limit(limit)
    result = await db.execute(query)
    rows = result.all()
    
    listings = []
    for listing, inventory in rows:
        # 获取物品名称
        item_name = "未知物品"
        if inventory.item:
            item_name = inventory.item.name
        
        listings.append(MyListingItem(
            listing_id=listing.id,
            inventory_id=inventory.id,
            asset_id=inventory.asset_id,
            item_name=item_name,
            price=float(listing.price),
            status=listing.status,
            listed_at=listing.listed_at.isoformat() if listing.listed_at else ""
        ))
    
    return MyListingsResponse(
        success=True,
        listings=listings,
        total=total
    )


@router.get("/listings/{listing_id}")
async def get_listing_detail(
    listing_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    获取挂单详情
    """
    result = await db.execute(
        select(Listing, Inventory).join(
            Inventory, Listing.inventory_id == Inventory.id
        ).where(
            Listing.id == listing_id,
            Inventory.user_id == current_user.id
        )
    )
    row = result.first()
    
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="挂单不存在"
        )
    
    listing, inventory = row
    
    return {
        "success": True,
        "listing": {
            "id": listing.id,
            "listing_id": listing.listing_id,
            "inventory_id": listing.inventory_id,
            "asset_id": inventory.asset_id,
            "price": float(listing.price),
            "status": listing.status,
            "platform": listing.platform,
            "listed_at": listing.listed_at.isoformat() if listing.listed_at else None,
            "sold_at": listing.sold_at.isoformat() if listing.sold_at else None,
            "cancelled_at": listing.cancelled_at.isoformat() if listing.cancelled_at else None,
        },
        "inventory": {
            "id": inventory.id,
            "asset_id": inventory.asset_id,
            "class_id": inventory.class_id,
            "instance_id": inventory.instance_id,
            "float_value": inventory.float_value,
            "status": inventory.status,
        }
    }
