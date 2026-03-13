# -*- coding: utf-8 -*-
"""
权限检查器测试
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi import HTTPException

from app.core.permissions import (
    ResourcePermissionChecker,
    verify_resource_owner,
    require_admin,
)


class MockUser:
    """模拟用户对象"""
    def __init__(self, user_id: int, is_admin: bool = False):
        self.id = user_id
        self.is_admin = is_admin


class MockOrder:
    """模拟订单对象"""
    def __init__(self, order_id: str, user_id: int):
        self.order_id = order_id
        self.user_id = user_id
        self.status = "pending"


class MockItem:
    """模拟物品对象"""
    def __init__(self, item_id: int, owner_id: int):
        self.id = item_id
        self.owner_id = owner_id


class TestResourcePermissionChecker:
    """资源权限检查器测试"""
    
    @pytest.mark.asyncio
    async def test_owner_can_access(self):
        """测试所有者可以访问自己的资源"""
        # 注册资源获取函数
        async def get_order(order_id):
            return MockOrder("ORD-001", user_id=1)
        
        ResourcePermissionChecker.register_resource_getter("order", get_order)
        
        # 用户1访问自己的订单 - 应该成功
        result = await ResourcePermissionChecker.verify_owner(
            resource_type="order",
            resource_id="ORD-001",
            current_user_id=1
        )
        
        assert result is True
    
    @pytest.mark.asyncio
    async def test_non_owner_cannot_access(self):
        """测试非所有者不能访问"""
        async def get_order(order_id):
            return MockOrder("ORD-001", user_id=1)
        
        ResourcePermissionChecker.register_resource_getter("order", get_order)
        
        # 用户2访问用户1的订单 - 应该失败
        with pytest.raises(HTTPException) as exc_info:
            await ResourcePermissionChecker.verify_owner(
                resource_type="order",
                resource_id="ORD-001",
                current_user_id=2
            )
        
        assert exc_info.value.status_code == 403
        assert "无权访问" in exc_info.value.detail
    
    @pytest.mark.asyncio
    async def test_resource_not_found(self):
        """测试资源不存在"""
        async def get_order(order_id):
            return None
        
        ResourcePermissionChecker.register_resource_getter("order", get_order)
        
        with pytest.raises(HTTPException) as exc_info:
            await ResourcePermissionChecker.verify_owner(
                resource_type="order",
                resource_id="NON-EXISTENT",
                current_user_id=1
            )
        
        assert exc_info.value.status_code == 404
    
    @pytest.mark.asyncio
    async def test_unconfigured_resource_type(self):
        """测试未配置的资源类型 - 默认放行"""
        # 不注册，直接使用未配置的资源类型
        result = await ResourcePermissionChecker.verify_owner(
            resource_type="unknown_type",
            resource_id="123",
            current_user_id=1
        )
        
        # 未配置的资源类型应该默认放行
        assert result is True
    
    @pytest.mark.asyncio
    async def test_shared_resource_access(self):
        """测试共享资源访问"""
        # 创建支持共享的资源
        class MockTrade:
            def __init__(self):
                self.id = 1
                self.seller_id = 1
                self.buyer_id = 2
                self.shared_with = [2, 3]
        
        async def get_trade(trade_id):
            return MockTrade()
        
        ResourcePermissionChecker.register_resource_getter("trade", get_trade)
        
        # 买家2访问交易 - 应该成功
        result = await ResourcePermissionChecker.verify_owner(
            resource_type="trade",
            resource_id="1",
            current_user_id=2,
            allow_shared=True
        )
        
        assert result is True
    
    @pytest.mark.asyncio
    async def test_admin_bypass(self):
        """测试管理员权限检查 - 当前不支持管理员绕过"""
        class MockAdminOrder:
            def __init__(self):
                self.user_id = 1
        
        async def get_order(order_id):
            return MockAdminOrder()
        
        ResourcePermissionChecker.RESOURCE_GETTERS["admin_order"] = get_order
        ResourcePermissionChecker.OWNER_FIELDS["admin_order"] = "user_id"
        
        # 注意：当前实现不包含管理员绕过逻辑
        # 管理员绕过需要在业务层单独实现
        # 非所有者访问应该被拒绝
        with pytest.raises(HTTPException) as exc_info:
            await ResourcePermissionChecker.verify_owner(
                resource_type="admin_order",
                resource_id="ORD-001",
                current_user_id=999
            )
        
        assert exc_info.value.status_code == 403


class TestVerifyResourceOwnerDecorator:
    """verify_resource_owner 装饰器测试"""
    
    @pytest.mark.asyncio
    async def test_decorator_with_valid_user(self):
        """测试装饰器带有效用户"""
        async def get_order(order_id):
            return MockOrder("ORD-001", user_id=1)
        
        ResourcePermissionChecker.register_resource_getter("order", get_order)
        
        @verify_resource_owner("order", "order_id")
        async def get_order_endpoint(order_id: str, current_user: MockUser):
            return {"order_id": order_id, "user_id": current_user.id}
        
        # 调用端点
        result = await get_order_endpoint(
            order_id="ORD-001",
            current_user=MockUser(user_id=1)
        )
        
        assert result["order_id"] == "ORD-001"
        assert result["user_id"] == 1
    
    @pytest.mark.asyncio
    async def test_decorator_without_user(self):
        """测试装饰器无用户"""
        @verify_resource_owner("order", "order_id")
        async def get_order_endpoint(order_id: str, current_user: MockUser):
            return {"order_id": order_id}
        
        # 不传用户应该返回401
        with pytest.raises(HTTPException) as exc_info:
            await get_order_endpoint(order_id="ORD-001", current_user=None)
        
        assert exc_info.value.status_code == 401
        assert "未认证" in exc_info.value.detail
    
    @pytest.mark.asyncio
    async def test_decorator_without_resource_id(self):
        """测试装饰器无资源ID"""
        @verify_resource_owner("order", "order_id")
        async def get_order_endpoint(order_id: str, current_user: MockUser):
            return {"order_id": order_id}
        
        # 不传资源ID应该返回400
        with pytest.raises(HTTPException) as exc_info:
            await get_order_endpoint(order_id=None, current_user=MockUser(1))
        
        assert exc_info.value.status_code == 400


class TestRequireAdminDecorator:
    """require_admin 装饰器测试"""
    
    @pytest.mark.asyncio
    async def test_admin_can_access(self):
        """测试管理员可以访问"""
        @require_admin()
        async def admin_endpoint(current_user: MockUser):
            return {"message": "success"}
        
        result = await admin_endpoint(current_user=MockUser(user_id=1, is_admin=True))
        
        assert result["message"] == "success"
    
    @pytest.mark.asyncio
    async def test_non_admin_cannot_access(self):
        """测试非管理员不能访问"""
        @require_admin()
        async def admin_endpoint(current_user: MockUser):
            return {"message": "success"}
        
        with pytest.raises(HTTPException) as exc_info:
            await admin_endpoint(current_user=MockUser(user_id=1, is_admin=False))
        
        assert exc_info.value.status_code == 403
        assert "管理员权限" in exc_info.value.detail
    
    @pytest.mark.asyncio
    async def test_no_user(self):
        """测试无用户"""
        @require_admin()
        async def admin_endpoint(current_user: MockUser):
            return {"message": "success"}
        
        with pytest.raises(HTTPException) as exc_info:
            await admin_endpoint(current_user=None)
        
        assert exc_info.value.status_code == 401


class TestResourcePermissionCheckerEdgeCases:
    """边界情况测试"""
    
    @pytest.mark.asyncio
    async def test_owner_id_as_string(self):
        """测试所有者ID为字符串"""
        class MockOrderWithStringOwner:
            def __init__(self):
                self.order_id = "ORD-001"
                self.user_id = "1"  # 字符串类型
        
        async def get_order(order_id):
            return MockOrderWithStringOwner()
        
        ResourcePermissionChecker.register_resource_getter("order", get_order)
        
        # 应该能正确比较
        result = await ResourcePermissionChecker.verify_owner(
            resource_type="order",
            resource_id="ORD-001",
            current_user_id=1
        )
        
        assert result is True
    
    @pytest.mark.asyncio
    async def test_error_getting_resource(self):
        """测试获取资源时发生错误"""
        async def get_order_error(order_id):
            raise Exception("Database error")
        
        ResourcePermissionChecker.register_resource_getter("order", get_order_error)
        
        with pytest.raises(HTTPException) as exc_info:
            await ResourcePermissionChecker.verify_owner(
                resource_type="order",
                resource_id="ORD-001",
                current_user_id=1
            )
        
        assert exc_info.value.status_code == 500
        assert "获取失败" in exc_info.value.detail
    
    @pytest.mark.asyncio
    async def test_cannot_determine_owner(self):
        """测试无法确定所有者"""
        class MockResource:
            pass  # 没有 user_id 字段
        
        async def get_resource(resource_id):
            return MockResource()
        
        ResourcePermissionChecker.register_resource_getter("resource", get_resource)
        
        # 无法确定所有者时，应该记录警告但放行
        result = await ResourcePermissionChecker.verify_owner(
            resource_type="resource",
            resource_id="1",
            current_user_id=1
        )
        
        assert result is True
