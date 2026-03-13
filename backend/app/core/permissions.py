# -*- coding: utf-8 -*-
"""
资源权限检查模块

提供资源级别的所有权验证功能，防止 IDOR (Insecure Direct Object Reference) 漏洞。
"""
from __future__ import annotations

import logging
from functools import wraps
from typing import Optional, Callable, Dict, Any, Type, List
from fastapi import Depends, HTTPException, Request, status
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class ResourcePermissionChecker:
    """
    资源权限检查器
    
    用于验证用户是否有权访问特定资源。
    支持资源类型到所有者字段的映射配置。
    
    Usage:
        # 注册资源获取函数
        ResourcePermissionChecker.register_resource_getter("order", get_order_by_id)
        
        # 在端点中使用
        @app.get("/orders/{order_id}")
        @verify_resource_owner("order", "order_id")
        async def get_order(...):
            ...
    """
    
    # 资源类型到所有者字段的映射
    OWNER_FIELDS: Dict[str, str] = {
        "order": "user_id",
        "item": "owner_id",
        "inventory": "user_id",
        "price_history": "user_id",
        "trade": "seller_id",
        "api_key": "user_id",
        "bot": "owner_id",
        "monitor": "user_id",
    }
    
    # 资源类型到获取函数的映射
    RESOURCE_GETTERS: Dict[str, Callable] = {}
    
    # 允许共享访问的资源类型
    ALLOW_SHARED: List[str] = ["trade", "inventory"]
    
    @classmethod
    def register_resource_getter(cls, resource_type: str, getter: Callable) -> None:
        """
        注册资源获取函数
        
        Args:
            resource_type: 资源类型 (order, item, etc.)
            getter: 异步获取资源的函数，签名: async def get(resource_id) -> Optional[Model]
        """
        cls.RESOURCE_GETTERS[resource_type] = getter
        logger.info(f"注册资源获取函数: {resource_type}")
    
    @classmethod
    def register_resource_types(
        cls,
        resource_type: str,
        owner_field: str,
        getter: Callable,
        allow_shared: bool = False
    ) -> None:
        """
        一次性注册资源类型、所有者字段和获取函数
        
        Args:
            resource_type: 资源类型
            owner_field: 所有者字段名
            getter: 资源获取函数
            allow_shared: 是否允许共享资源访问
        """
        cls.OWNER_FIELDS[resource_type] = owner_field
        cls.RESOURCE_GETTERS[resource_type] = getter
        if allow_shared:
            if resource_type not in cls.ALLOW_SHARED:
                cls.ALLOW_SHARED.append(resource_type)
        logger.info(
            f"注册资源类型: {resource_type}, owner_field: {owner_field}, "
            f"allow_shared: {allow_shared}"
        )
    
    @classmethod
    async def verify_owner(
        cls,
        resource_type: str,
        resource_id: Any,
        current_user_id: int,
        allow_shared: bool = False
    ) -> bool:
        """
        验证用户是否为资源所有者
        
        Args:
            resource_type: 资源类型 (order, item, etc.)
            resource_id: 资源ID
            current_user_id: 当前用户ID
            allow_shared: 是否允许共享资源访问
        
        Returns:
            True if authorized
        
        Raises:
            HTTPException: 验证失败时抛出异常
                - 403: 无权访问
                - 404: 资源不存在
                - 500: 配置错误
        """
        # 检查资源类型是否配置
        if resource_type not in cls.OWNER_FIELDS:
            logger.warning(
                f"未配置权限检查的资源类型: {resource_type}，默认放行"
            )
            return True
        
        # 检查是否注册了获取函数
        if resource_type not in cls.RESOURCE_GETTERS:
            logger.error(
                f"未注册资源获取函数: {resource_type}，拒绝访问"
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="权限检查配置错误"
            )
        
        # 获取资源
        getter = cls.RESOURCE_GETTERS[resource_type]
        
        try:
            resource = await getter(resource_id)
        except Exception as e:
            logger.error(
                f"获取资源失败: {resource_type}:{resource_id}, error: {e}"
            )
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
        owner_field = cls.OWNER_FIELDS.get(resource_type)
        
        # 尝试多种方式获取所有者ID
        owner_id = None
        
        # 方式1: 直接属性访问
        if owner_field:
            owner_id = getattr(resource, owner_field, None)
        
        # 方式2: 字典访问
        if owner_id is None and isinstance(resource, dict):
            owner_id = resource.get(owner_field)
        
        # 方式3: Pydantic 模型
        if owner_id is None:
            owner_id = getattr(resource, 'user_id', None)
            if owner_id is None:
                owner_id = getattr(resource, 'owner_id', None)
        
        # 如果仍然无法获取所有者ID，记录警告但放行
        if owner_id is None:
            logger.warning(
                f"无法确定资源所有者: {resource_type}:{resource_id}，默认放行"
            )
            return True
        
        # 转换为 int (数据库返回的可能是字符串)
        try:
            owner_id = int(owner_id)
        except (TypeError, ValueError):
            pass
        
        # 所有者检查
        if owner_id == current_user_id:
            return True
        
        # 共享资源检查
        resource_allow_shared = allow_shared or resource_type in cls.ALLOW_SHARED
        if resource_allow_shared:
            # 检查是否有共享列表
            shared_with = getattr(resource, 'shared_with', None)
            if shared_with:
                if isinstance(shared_with, list):
                    if current_user_id in shared_with:
                        return True
                elif isinstance(shared_with, str):
                    # 可能是逗号分隔的字符串
                    shared_list = [int(x.strip()) for x in shared_with.split(',') if x.strip().isdigit()]
                    if current_user_id in shared_list:
                        return True
            
            # 额外检查 buyer_id (交易场景)
            buyer_id = getattr(resource, 'buyer_id', None)
            if buyer_id:
                try:
                    buyer_id = int(buyer_id)
                    if buyer_id == current_user_id:
                        return True
                except (TypeError, ValueError):
                    pass
        
        # 无权访问
        logger.warning(
            f"未授权访问尝试: user_id={current_user_id}, "
            f"resource={resource_type}:{resource_id}, owner_id={owner_id}"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权访问此资源"
        )


def verify_resource_owner(
    resource_type: str,
    resource_id_param: str = "id",
    allow_shared: bool = False
):
    """
    资源所有权验证装饰器
    
    用于 FastAPI 端点的装饰器，验证当前用户是否有权访问指定资源。
    
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
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
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
                # 尝试从 path 参数获取
                path_params = kwargs.get('path_params')
                if path_params:
                    resource_id = path_params.get(resource_id_param)
            
            if not resource_id:
                logger.warning(f"缺少资源ID参数: {resource_id_param}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"缺少资源ID: {resource_id_param}"
                )
            
            # 3. 验证所有权
            await ResourcePermissionChecker.verify_owner(
                resource_type=resource_type,
                resource_id=resource_id,
                current_user_id=current_user.id,
                allow_shared=allow_shared
            )
            
            # 4. 调用原函数
            return await func(*args, **kwargs)
        
        return wrapper
    return decorator


def require_admin():
    """
    管理员权限验证装饰器
    
    Usage:
        @app.get("/admin/users")
        @require_admin()
        async def admin_get_users(current_user: User = Depends(get_current_user)):
            ...
    """
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # 获取 current_user
            current_user = kwargs.get('current_user')
            
            if not current_user:
                for arg in args:
                    if hasattr(arg, 'id') and hasattr(arg, 'username'):
                        current_user = arg
                        break
            
            if not current_user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="未认证"
                )
            
            # 检查管理员权限
            if not getattr(current_user, 'is_admin', False):
                logger.warning(
                    f"非管理员用户尝试访问管理接口: user_id={current_user.id}"
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="需要管理员权限"
                )
            
            return await func(*args, **kwargs)
        
        return wrapper
    return decorator


# ============ 便捷函数 ============

async def get_order_resource(order_id: Any):
    """获取订单资源的辅助函数 (需要注册到 ResourcePermissionChecker)"""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.models.order import Order
    
    # 这个函数需要通过依赖注入获取 db
    # 实际使用时需要通过Depends传入
    return None


async def get_item_resource(item_id: Any):
    """获取物品资源的辅助函数 (需要注册到 ResourcePermissionChecker)"""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.models.item import Item
    
    return None
