# -*- coding: utf-8 -*-
"""
权限注册表模块

用于注册资源获取函数，以便权限检查器能够获取资源并验证所有权。
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.permissions import ResourcePermissionChecker

logger = logging.getLogger(__name__)

# 全局变量存储 db session 工厂
_db_session_factory: Optional[Callable] = None


def set_db_session_factory(factory: Callable) -> None:
    """
    设置数据库会话工厂
    
    Args:
        factory: 异步会话工厂函数
    """
    global _db_session_factory
    _db_session_factory = factory


async def get_db_session() -> AsyncSession:
    """
    获取数据库会话
    
    Returns:
        AsyncSession 实例
    """
    if _db_session_factory is None:
        raise RuntimeError("数据库会话工厂未设置，请调用 set_db_session_factory()")
    async for session in _db_session_factory():
        yield session


# ============ 资源获取函数 ============

async def get_order_by_order_id(order_id: Any, db: AsyncSession = None) -> Optional[Any]:
    """
    根据订单ID获取订单资源
    
    Args:
        order_id: 订单ID (order_id 字段)
        db: 数据库会话
    
    Returns:
        Order 对象或 None
    """
    if db is None:
        logger.warning("无法获取数据库会话")
        return None
    
    from app.models.order import Order
    result = await db.execute(
        select(Order).where(Order.order_id == str(order_id))
    )
    return result.scalar_one_or_none()


async def get_inventory_by_id(inventory_id: Any, db: AsyncSession = None) -> Optional[Any]:
    """
    根据库存ID获取库存资源
    
    Args:
        inventory_id: 库存ID
        db: 数据库会话
    
    Returns:
        Inventory 对象或 None
    """
    if db is None:
        logger.warning("无法获取数据库会话")
        return None
    
    from app.models.inventory import Inventory
    result = await db.execute(
        select(Inventory).where(Inventory.id == int(inventory_id))
    )
    return result.scalar_one_or_none()


async def get_monitor_by_id(monitor_id: Any, db: AsyncSession = None) -> Optional[Any]:
    """
    根据监控ID获取监控资源
    
    Args:
        monitor_id: 监控ID
        db: 数据库会话
    
    Returns:
        MonitorTask 对象或 None
    """
    if db is None:
        logger.warning("无法获取数据库会话")
        return None
    
    from app.models.monitor import MonitorTask
    result = await db.execute(
        select(MonitorTask).where(MonitorTask.id == int(monitor_id))
    )
    return result.scalar_one_or_none()


async def get_bot_by_id(bot_id: Any, db: AsyncSession = None) -> Optional[Any]:
    """
    根据机器人ID获取机器人资源
    
    Args:
        bot_id: 机器人ID
        db: 数据库会话
    
    Returns:
        Bot 对象或 None
    """
    if db is None:
        logger.warning("无法获取数据库会话")
        return None
    
    from app.models.bot import Bot
    result = await db.execute(
        select(Bot).where(Bot.id == int(bot_id))
    )
    return result.scalar_one_or_none()


async def get_listing_by_id(listing_id: Any, db: AsyncSession = None) -> Optional[Any]:
    """
    根据上架ID获取上架记录（通过关联的Inventory获取所有者）
    
    Args:
        listing_id: 上架记录ID
        db: 数据库会话
    
    Returns:
        Listing 对象或 None
    """
    if db is None:
        logger.warning("无法获取数据库会话")
        return None
    
    from app.models.inventory import Listing, Inventory
    result = await db.execute(
        select(Listing, Inventory)
        .join(Inventory, Listing.inventory_id == Inventory.id)
        .where(Listing.id == int(listing_id))
    )
    row = result.first()
    if row:
        listing, inventory = row
        # 为 listing 添加 user_id 属性以便权限检查
        listing.user_id = inventory.user_id
        return listing
    return None


# ============ 带数据库会话的资源获取函数包装器 ============

class ResourceGetter:
    """
    资源获取器封装类
    
    提供带数据库会话的资源获取功能。
    """
    
    @staticmethod
    async def get_order(order_id: Any) -> Optional[Any]:
        """获取订单资源"""
        from app.core.database import async_session_maker
        async with async_session_maker() as db:
            return await get_order_by_order_id(order_id, db)
    
    @staticmethod
    async def get_inventory(inventory_id: Any) -> Optional[Any]:
        """获取库存资源"""
        from app.core.database import async_session_maker
        async with async_session_maker() as db:
            return await get_inventory_by_id(inventory_id, db)
    
    @staticmethod
    async def get_monitor(monitor_id: Any) -> Optional[Any]:
        """获取监控资源"""
        from app.core.database import async_session_maker
        async with async_session_maker() as db:
            return await get_monitor_by_id(monitor_id, db)
    
    @staticmethod
    async def get_bot(bot_id: Any) -> Optional[Any]:
        """获取机器人资源"""
        from app.core.database import async_session_maker
        async with async_session_maker() as db:
            return await get_bot_by_id(bot_id, db)
    
    @staticmethod
    async def get_listing(listing_id: Any) -> Optional[Any]:
        """获取上架记录资源"""
        from app.core.database import async_session_maker
        async with async_session_maker() as db:
            return await get_listing_by_id(listing_id, db)


# ============ 注册所有资源获取函数 ============

def register_all_resource_getters() -> None:
    """
    注册所有资源获取函数到权限检查器
    
    此函数应在应用启动时调用（在 main.py 或 router 初始化时）。
    """
    # 注册订单资源
    ResourcePermissionChecker.register_resource_types(
        resource_type="order",
        owner_field="user_id",
        getter=ResourceGetter.get_order,
    )
    
    # 注册库存资源
    ResourcePermissionChecker.register_resource_types(
        resource_type="inventory",
        owner_field="user_id",
        getter=ResourceGetter.get_inventory,
    )
    
    # 注册监控资源
    ResourcePermissionChecker.register_resource_types(
        resource_type="monitor",
        owner_field="user_id",
        getter=ResourceGetter.get_monitor,
    )
    
    # 注册机器人资源
    ResourcePermissionChecker.register_resource_types(
        resource_type="bot",
        owner_field="owner_id",
        getter=ResourceGetter.get_bot,
    )
    
    # 注册上架记录资源
    ResourcePermissionChecker.register_resource_types(
        resource_type="listing",
        owner_field="user_id",
        getter=ResourceGetter.get_listing,
    )
    
    logger.info("所有资源获取函数已注册到权限检查器")


def verify_resource_owner(
    resource_type: str,
    resource_id_param: str = "id",
    allow_shared: bool = False
):
    """
    资源所有权验证装饰器（带数据库会话版本）
    
    用于 FastAPI 端点的装饰器，验证当前用户是否有权访问指定资源。
    自动处理数据库会话。
    
    Args:
        resource_type: 资源类型 (order, item, trade, etc.)
        resource_id_param: 资源ID的参数名，默认为 "id"
        allow_shared: 是否允许共享资源访问
    
    Usage:
        @app.get("/orders/{order_id}")
        @verify_resource_owner("order", "order_id")
        async def get_order(
            order_id: str,
            current_user: User = Depends(get_current_user)
        ):
            ...
    """
    from functools import wraps
    from fastapi import HTTPException, status
    
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            from app.core.database import async_session_maker
            
            # 1. 获取 current_user
            current_user = kwargs.get('current_user')
            
            if not current_user:
                # 尝试从 FastAPI Depends 获取
                for arg in args:
                    if hasattr(arg, 'id') and hasattr(arg, 'username'):
                        current_user = arg
                        break
            
            if not current_user or not hasattr(current_user, 'id'):
                logger.warning("无法获取当前用户信息")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="未认证"
                )
            
            # 2. 获取资源ID
            resource_id = kwargs.get(resource_id_param)
            
            if not resource_id:
                logger.warning(f"缺少资源ID参数: {resource_id_param}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"缺少资源ID: {resource_id_param}"
                )
            
            # 3. 获取资源并验证所有权
            getter = ResourcePermissionChecker.RESOURCE_GETTERS.get(resource_type)
            
            if not getter:
                logger.error(f"未注册资源获取函数: {resource_type}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="权限检查配置错误"
                )
            
            # 使用数据库会话获取资源
            async with async_session_maker() as db:
                try:
                    resource = await getter(resource_id)
                except Exception as e:
                    logger.error(f"获取资源失败: {resource_type}:{resource_id}, error: {e}")
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="资源获取失败"
                    )
                
                if not resource:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"资源不存在: {resource_type}:{resource_id}"
                    )
                
                # 获取所有者字段
                owner_field = ResourcePermissionChecker.OWNER_FIELDS.get(resource_type)
                
                # 尝试多种方式获取所有者ID
                owner_id = None
                
                # 方式1: 直接属性访问
                if owner_field:
                    owner_id = getattr(resource, owner_field, None)
                
                # 方式2: 字典访问
                if owner_id is None and isinstance(resource, dict):
                    owner_id = resource.get(owner_field)
                
                # 方式3: 备用字段
                if owner_id is None:
                    owner_id = getattr(resource, 'user_id', None)
                    if owner_id is None:
                        owner_id = getattr(resource, 'owner_id', None)
                
                # 如果仍然无法获取所有者ID，记录警告但放行
                if owner_id is None:
                    logger.warning(
                        f"无法确定资源所有者: {resource_type}:{resource_id}，默认放行"
                    )
                    return await func(*args, **kwargs)
                
                # 转换为 int
                try:
                    owner_id = int(owner_id)
                except (TypeError, ValueError):
                    pass
                
                # 所有者检查
                if owner_id != current_user.id:
                    # 共享资源检查
                    resource_allow_shared = allow_shared or resource_type in ResourcePermissionChecker.ALLOW_SHARED
                    if not resource_allow_shared:
                        logger.warning(
                            f"未授权访问尝试: user_id={current_user.id}, "
                            f"resource={resource_type}:{resource_id}, owner_id={owner_id}"
                        )
                        raise HTTPException(
                            status_code=status.HTTP_403_FORBIDDEN,
                            detail="无权访问此资源"
                        )
                    
                    # 检查共享列表
                    shared_with = getattr(resource, 'shared_with', None)
                    if shared_with:
                        if isinstance(shared_with, list):
                            if current_user.id in shared_with:
                                return await func(*args, **kwargs)
                        elif isinstance(shared_with, str):
                            shared_list = [int(x.strip()) for x in shared_with.split(',') if x.strip().isdigit()]
                            if current_user.id in shared_list:
                                return await func(*args, **kwargs)
                    
                    # 检查 buyer_id
                    buyer_id = getattr(resource, 'buyer_id', None)
                    if buyer_id:
                        try:
                            buyer_id = int(buyer_id)
                            if buyer_id == current_user.id:
                                return await func(*args, **kwargs)
                        except (TypeError, ValueError):
                            pass
                    
                    logger.warning(
                        f"未授权访问尝试: user_id={current_user.id}, "
                        f"resource={resource_type}:{resource_id}, owner_id={owner_id}"
                    )
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="无权访问此资源"
                    )
            
            # 4. 调用原函数
            return await func(*args, **kwargs)
        
        return wrapper
    return decorator
