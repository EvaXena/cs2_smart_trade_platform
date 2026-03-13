"""
权限检查器集成测试
"""
import pytest
from httpx import AsyncClient


class TestPermissionsIntegration:
    """权限集成测试"""
    
    @pytest.mark.asyncio
    async def test_order_unauthorized(self, client):
        """未授权访问订单应返回401"""
        response = await client.get("/api/v1/orders/1")
        assert response.status_code in [401, 403]
    
    @pytest.mark.asyncio
    async def test_inventory_unauthorized(self, client):
        """未授权访问库存应返回401"""
        response = await client.get("/api/v1/inventory")
        assert response.status_code in [401, 403]
    
    @pytest.mark.asyncio
    async def test_monitors_unauthorized(self, client):
        """未授权访问监控器应返回401"""
        response = await client.get("/api/v1/monitors")
        assert response.status_code in [401, 403]
    
    @pytest.mark.asyncio
    async def test_bots_unauthorized(self, client):
        """未授权访问机器人应返回401"""
        response = await client.get("/api/v1/bots")
        assert response.status_code in [401, 403]
    
    @pytest.mark.asyncio
    async def test_batch_endpoint_validation(self, client):
        """批量端点输入验证"""
        # 超大批量请求 - 无认证返回401
        response = await client.post(
            "/api/v1/orders/batch",
            json={"orders": [{"item_id": i, "price": 100, "quantity": 1} for i in range(200)]}
        )
        assert response.status_code in [400, 401, 422]
    
    @pytest.mark.asyncio
    async def test_items_batch(self, client):
        """批量物品端点可用性"""
        response = await client.post(
            "/api/v1/items/batch",
            json={"item_ids": [1, 2, 3]}
        )
        # 公开端点，可能返回200或403
        assert response.status_code in [200, 401, 403]
