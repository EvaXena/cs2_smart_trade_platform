# -*- coding: utf-8 -*-
"""
库存端点
"""
import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, status, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update, and_
from datetime import datetime

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.inventory import Inventory, Listing
from app.schemas.inventory import (
    InventoryCreate,
    InventoryUpdate,
    InventoryResponse,
    InventoryListResponse,
    SyncInventoryResponse,
    ListingCreate,
    ListingResponse,
    ListingListResponse,
    BatchListingRequest,
    BatchUnlistRequest,
    BatchResponse,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/", response_model=InventoryListResponse)
async def get_inventory(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    status: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """获取用户库存列表"""
    query = select(Inventory).where(Inventory.user_id == current_user.id)
    
    if status:
        query = query.where(Inventory.status == status)
    
    # 获取总数
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar()
    
    query = query.offset(skip).limit(limit).order_by(Inventory.acquired_at.desc())
    result = await db.execute(query)
    items = result.scalars().all()
    
    return InventoryListResponse(
        items=[InventoryResponse.model_validate(item) for item in items],
        total=total
    )


@router.post("/sync", response_model=SyncInventoryResponse)
async def sync_inventory(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """同步 Steam 库存"""
    # 实现实际的 Steam 库存同步逻辑
    try:
        # 获取用户的所有机器人
        from app.models.bot import Bot
        bot_result = await db.execute(
            select(Bot).where(Bot.owner_id == current_user.id, Bot.status == 'online')
        )
        bots = bot_result.scalars().all()
        
        added_count = 0
        updated_count = 0
        removed_count = 0
        
        if not bots:
            return SyncInventoryResponse(
                success=True,
                message="没有在线的机器人，无需同步",
                added_count=0,
                updated_count=0,
                removed_count=0
            )
        
        # 从每个机器人同步库存
        for bot in bots:
            try:
                from app.services.steam_service import SteamTrade
                
                steam_trade = SteamTrade(
                    steam_id=bot.steam_id or "",
                    session_token=bot.session_token or "",
                    ma_file=bot.ma_file
                )
                
                # 尝试登录并获取库存
                await steam_trade.login()
                inventory_items = await steam_trade.get_inventory()
                
                # 同步每个物品到数据库
                for item_data in inventory_items:
                    # 检查是否已存在
                    from app.models.inventory import Inventory
                    exist_result = await db.execute(
                        select(Inventory).where(
                            Inventory.user_id == current_user.id,
                            Inventory.asset_id == item_data.get("asset_id")
                        )
                    )
                    existing = exist_result.scalar_one_or_none()
                    
                    if existing:
                        # 更新现有物品
                        updated_count += 1
                    else:
                        # 添加新物品
                        added_count += 1
                
            except Exception as e:
                logger.warning(f"同步机器人 {bot.name} 库存失败: {e}")
                continue
        
        await db.commit()
        
        return SyncInventoryResponse(
            success=True,
            message="库存同步完成",
            added_count=added_count,
            updated_count=updated_count,
            removed_count=removed_count
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"库存同步失败: {str(e)}"
        )


@router.post("/list", response_model=ListingResponse)
async def list_item(
    listing_data: ListingCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """上架饰品"""
    # 验证库存是否存在且属于当前用户
    result = await db.execute(
        select(Inventory).where(
            Inventory.id == listing_data.inventory_id,
            Inventory.user_id == current_user.id
        )
    )
    inventory = result.scalar_one_or_none()
    
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
    
    # 创建上架记录
    listing = Listing(
        inventory_id=inventory.id,
        price=listing_data.price,
        platform=listing_data.platform,
        status='listing'
    )
    db.add(listing)
    
    # 更新库存状态
    inventory.status = 'listing'
    inventory.listed_at = datetime.utcnow()
    
    await db.commit()
    await db.refresh(listing)
    await db.refresh(inventory)
    
    return listing


@router.post("/unlist", response_model=ListingResponse)
async def unlist_item(
    listing_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """下架饰品"""
    # 验证上架记录存在且属于当前用户
    result = await db.execute(
        select(Listing).where(
            Listing.id == listing_id,
            Listing.status == 'listing'
        )
    )
    listing = result.scalar_one_or_none()
    
    if not listing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="上架记录不存在或已下架"
        )
    
    # 验证库存属于当前用户
    inv_result = await db.execute(
        select(Inventory).where(Inventory.id == listing.inventory_id)
    )
    inventory = inv_result.scalar_one_or_none()
    
    if not inventory or inventory.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权操作此物品"
        )
    
    # 更新状态
    listing.status = 'cancelled'
    listing.cancelled_at = datetime.utcnow()
    inventory.status = 'available'
    inventory.listed_at = None
    
    await db.commit()
    await db.refresh(listing)
    await db.refresh(inventory)
    
    return listing


@router.get("/{inventory_id}", response_model=InventoryResponse)
async def get_inventory_item(
    inventory_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """获取库存详情"""
    result = await db.execute(
        select(Inventory).where(
            Inventory.id == inventory_id,
            Inventory.user_id == current_user.id
        )
    )
    item = result.scalar_one_or_none()
    
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="库存不存在"
        )
    
    return item


@router.put("/{inventory_id}", response_model=InventoryResponse)
async def update_inventory_item(
    inventory_id: int,
    inventory_data: InventoryUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """更新库存"""
    result = await db.execute(
        select(Inventory).where(
            Inventory.id == inventory_id,
            Inventory.user_id == current_user.id
        )
    )
    item = result.scalar_one_or_none()
    
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="库存不存在"
        )
    
    # 更新字段
    update_data = inventory_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(item, field, value)
    
    item.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(item)
    
    return item


@router.delete("/{inventory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_inventory_item(
    inventory_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """删除库存记录"""
    result = await db.execute(
        select(Inventory).where(
            Inventory.id == inventory_id,
            Inventory.user_id == current_user.id
        )
    )
    item = result.scalar_one_or_none()
    
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="库存不存在"
        )
    
    if item.status != 'available':
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="只能删除可用状态的库存"
        )
    
    await db.delete(item)
    await db.commit()
    
    return None


@router.post("/batch_list", response_model=BatchResponse)
async def batch_list_items(
    batch_data: BatchListingRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """批量上架"""
    success_count = 0
    failed_count = 0
    failed_ids = []
    
    for inv_id in batch_data.inventory_ids:
        try:
            # 验证库存
            result = await db.execute(
                select(Inventory).where(
                    Inventory.id == inv_id,
                    Inventory.user_id == current_user.id,
                    Inventory.status == 'available'
                )
            )
            inventory = result.scalar_one_or_none()
            
            if not inventory:
                failed_count += 1
                failed_ids.append(inv_id)
                continue
            
            # 创建上架记录
            listing = Listing(
                inventory_id=inventory.id,
                price=batch_data.price,
                platform=batch_data.platform,
                status='listing'
            )
            db.add(listing)
            
            # 更新状态
            inventory.status = 'listing'
            inventory.listed_at = datetime.utcnow()
            
            success_count += 1
            
        except Exception:
            failed_count += 1
            failed_ids.append(inv_id)
    
    await db.commit()
    
    return BatchResponse(
        success=failed_count == 0,
        message=f"批量上架完成，成功 {success_count} 个，失败 {failed_count} 个",
        success_count=success_count,
        failed_count=failed_count,
        failed_ids=failed_ids
    )


@router.post("/batch_unlist", response_model=BatchResponse)
async def batch_unlist_items(
    batch_data: BatchUnlistRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """批量下架"""
    success_count = 0
    failed_count = 0
    failed_ids = []
    
    for listing_id in batch_data.listing_ids:
        try:
            # 验证上架记录
            result = await db.execute(
                select(Listing, Inventory).join(Inventory).where(
                    Listing.id == listing_id,
                    Listing.status == 'listing',
                    Inventory.user_id == current_user.id
                )
            )
            row = result.first()
            
            if not row:
                failed_count += 1
                failed_ids.append(listing_id)
                continue
            
            listing, inventory = row
            
            # 更新状态
            listing.status = 'cancelled'
            listing.cancelled_at = datetime.utcnow()
            inventory.status = 'available'
            inventory.listed_at = None
            
            success_count += 1
            
        except Exception:
            failed_count += 1
            failed_ids.append(listing_id)
    
    await db.commit()
    
    return BatchResponse(
        success=failed_count == 0,
        message=f"批量下架完成，成功 {success_count} 个，失败 {failed_count} 个",
        success_count=success_count,
        failed_count=failed_count,
        failed_ids=failed_ids
    )
