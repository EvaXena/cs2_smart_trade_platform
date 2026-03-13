# CS2平台第79轮 - 改进方案

## 上一轮审核问题

1. **权限检查器未集成到端点**（高优先级）
2. **批量端点验证器重复使用**（中优先级）
3. **缺少集成测试**（中优先级）

---

## 问题1: 权限检查器集成方案

### 1.1 需要集成权限检查器的端点列表

| 端点文件 | 需要集成的端点 | 资源类型 | 资源ID参数 |
|---------|--------------|---------|-----------|
| orders.py | GET /{order_id} | order | order_id |
| orders.py | DELETE /{order_id} (cancel_order) | order | order_id |
| orders.py | POST /batch/cancel (单个order_id验证) | order | order_id |
| inventory.py | GET /{inventory_id} | inventory | inventory_id |
| inventory.py | PUT /{inventory_id} | inventory | inventory_id |
| inventory.py | DELETE /{inventory_id} | inventory | inventory_id |
| inventory.py | POST /unlist | inventory | listing_id→inventory_id |
| monitors.py | GET /{monitor_id} | monitor | monitor_id |
| monitors.py | PUT /{monitor_id} | monitor | monitor_id |
| monitors.py | DELETE /{monitor_id} | monitor | monitor_id |
| monitors.py | POST /{monitor_id}/start | monitor | monitor_id |
| monitors.py | POST /{monitor_id}/stop | monitor | monitor_id |
| monitors.py | GET /{monitor_id}/logs | monitor | monitor_id |
| bots.py | GET /{bot_id} | bot | bot_id |
| bots.py | PUT /{bot_id} | bot | bot_id |
| bots.py | DELETE /{bot_id} | bot | bot_id |
| bots.py | POST /{bot_id}/login | bot | bot_id |
| bots.py | POST /{bot_id}/logout | bot | bot_id |
| bots.py | POST /{bot_id}/refresh | bot | bot_id |
| bots.py | GET /{bot_id}/inventory | bot | bot_id |
| bots.py | GET /{bot_id}/trades | bot | bot_id |

### 1.2 集成方式：装饰器形式

**推荐使用装饰器形式**，因为：
- 非侵入式：无需修改端点函数签名
- 可组合：可与其他装饰器（如 idempotency）叠加使用
- 明确声明：代码清晰表明需要权限检查

**装饰器签名**：
```python
@verify_resource_owner("order", "order_id")
async def get_order(
    order_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ...
```

### 1.3 实施步骤

**Step 1: 创建资源获取函数注册模块**
```python
# app/core/permissions_registry.py
from app.core.permissions import ResourcePermissionChecker
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

async def get_order_getter(order_id, db: AsyncSession):
    from app.models.order import Order
    result = await db.execute(select(Order).where(Order.order_id == order_id))
    return result.scalar_one_or_none()

# 在应用启动时注册
ResourcePermissionChecker.register_resource_types(
    resource_type="order",
    owner_field="user_id",
    getter=get_order_getter,
)
```

**Step 2: 在 router 初始化时注册所有资源获取函数**
```python
# app/api/v1/endpoints/__init__.py 或 app/main.py
from app.core.permissions_registry import register_all_resource_getters
register_all_resource_getters()
```

**Step 3: 修改端点添加装饰器**

示例 - orders.py:
```python
from app.core.permissions import verify_resource_owner

@router.get("/{order_id}", response_model=OrderResponse)
@verify_resource_owner("order", "order_id")
async def get_order(
    order_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # 移除手动 user_id 检查，装饰器已处理
    ...
```

---

## 问题2: 批量端点重复验证修复方案

### 2.1 当前问题分析

**orders.py 批量创建订单**:
- 循环内部调用 `validate_item_id()`, `validate_price()`, `validate_quantity()`
- 这些验证在 Pydantic schema 层面已经执行过，造成重复

**items.py 批量获取**:
- BatchValidator 已创建但调用方式有问题：`await _item_batch_validator.validate([request.model_dump()])`

### 2.2 修复方案

**方案A: 预验证模式（推荐）**

在批量操作前，使用 BatchValidator 预验证整个批次：

```python
@router.post("/batch", response_model=OrderBatchResponse)
async def create_orders_batch(
    request: OrderBatchCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # 预验证整个批次
    validated_orders = await _order_batch_create_validator.validate(request.orders)
    
    # 循环中不再重复验证，直接使用 validated_orders
    for order_data in validated_orders:
        # 业务逻辑，不需要再调用 validate_xxx
        order_total = order_data.price * order_data.quantity
        ...
```

**方案B: 创建可复用的验证器单例**

在共享模块中创建单例：

```python
# app/validators/shared.py
from app.validators.batch_validator import BatchValidator
from app.schemas.batch import OrderBatchCreateRequest, ItemBatchGetRequest

order_batch_validator = BatchValidator(OrderBatchCreateRequest, max_size=100)
item_batch_validator = BatchValidator(ItemBatchGetRequest, max_size=100)
```

然后在端点中导入使用：
```python
from app.validators.shared import order_batch_validator
```

### 2.3 实施步骤

1. **修复 items.py 批量验证调用方式**:
   ```python
   # 改为直接传入列表
   validated_request = await _item_batch_validator.validate(request.item_ids)
   ```

2. **在 orders.py 批量端点中使用预验证**:
   ```python
   # 在循环前预验证
   validated_orders = await _order_batch_create_validator.validate(request.orders)
   ```

3. **创建共享验证器模块**（可选）:
   ```python
   # app/validators/__init__.py
   from app.validators.batch_validator import BatchValidator
   from app.schemas.batch import OrderBatchCreateRequest, ItemBatchGetRequest
   
   order_batch_validator = BatchValidator(OrderBatchCreateRequest, max_size=100)
   item_batch_validator = BatchValidator(ItemBatchGetRequest, max_size=100)
   ```

---

## 问题3: 集成测试结构设计

### 3.1 测试结构

使用 FastAPI TestClient + 认证模拟：

```
tests/
├── conftest.py                    # 已有的 fixtures
├── test_permissions_integration.py  # NEW: 权限检查器集成测试
├── test_orders_integration.py     # NEW: 订单端点集成测试
├── test_inventory_integration.py  # NEW: 库存端点集成测试
├── test_monitors_integration.py   # NEW: 监控端点集成测试
└── test_bots_integration.py       # NEW: 机器人端点集成测试
```

### 3.2 认证模拟方案

使用 `auth_token` fixture（在 conftest.py 中已实现）:

```python
@pytest.mark.asyncio
async def test_get_order_unauthorized(client: AsyncClient):
    """测试未认证访问被拒绝"""
    response = await client.get("/api/v1/orders/ORD-001")
    assert response.status_code == 401

@pytest.mark.asyncio
async def test_get_order_forbidden(client: AsyncClient, auth_token: str):
    """测试无权限访问被拒绝"""
    # 用户A创建订单
    response = await client.post(
        "/api/v1/orders",
        json={...},
        headers={"Authorization": f"Bearer {auth_token}"}
    )
    order_id = response.json()["order_id"]
    
    # 用户B尝试访问用户A的订单
    # 需要先创建第二个用户并获取 token
    ...
    response = await client.get(
        f"/api/v1/orders/{order_id}",
        headers={"Authorization": f"Bearer {auth_token_b}"}
    )
    assert response.status_code == 403
```

### 3.3 详细测试用例设计

**test_permissions_integration.py**:

```python
import pytest
from httpx import AsyncClient

class TestOrderPermissionIntegration:
    """订单权限集成测试"""
    
    @pytest.mark.asyncio
    async def test_owner_can_get_order(self, client: AsyncClient, auth_token: str):
        """所有者可以获取自己的订单"""
        # 创建订单
        create_resp = await client.post(
            "/api/v1/orders",
            json={
                "item_id": 1,
                "side": "buy",
                "price": 100.0,
                "quantity": 1
            },
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        order_id = create_resp.json()["order_id"]
        
        # 获取订单
        get_resp = await client.get(
            f"/api/v1/orders/{order_id}",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        
        assert get_resp.status_code == 200
        assert get_resp.json()["order_id"] == order_id
    
    @pytest.mark.asyncio
    async def test_non_owner_cannot_get_order(self, client: AsyncClient, auth_token: str):
        """非所有者不能获取他人订单"""
        # 用户A创建订单
        create_resp = await client.post(
            "/api/v1/orders",
            json={...},
            headers={"Authorization": f"Bearer {auth_token_a}"}
        )
        order_id = create_resp.json()["order_id"]
        
        # 用户B尝试获取
        get_resp = await client.get(
            f"/api/v1/orders/{order_id}",
            headers={"Authorization": f"Bearer {auth_token_b}"}
        )
        
        assert get_resp.status_code == 403
    
    @pytest.mark.asyncio
    async def test_nonexistent_order_returns_404(self, client: AsyncClient, auth_token: str):
        """不存在的订单返回404"""
        response = await client.get(
            "/api/v1/orders/NONEXISTENT",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 404
```

### 3.4 实施步骤

1. **创建权限集成测试文件**:
   ```
   tests/test_permissions_integration.py
   ```

2. **创建端点集成测试文件**:
   ```
   tests/test_orders_integration.py
   tests/test_inventory_integration.py
   tests/test_monitors_integration.py
   tests/test_bots_integration.py
   ```

3. **每个测试文件应包含**:
   - 认证相关测试（401）
   - 权限相关测试（403）
   - 正常业务流程测试（200）
   - 资源不存在测试（404）

---

## 执行计划

| 优先级 | 任务 | 预计工作量 | 依赖 |
|--------|------|-----------|------|
| P0 | 创建 permissions_registry.py 并注册资源获取函数 | 1h | permissions.py |
| P0 | 修改 orders.py 集成权限检查器 | 1h | Step 1 |
| P0 | 修改 inventory.py 集成权限检查器 | 1h | Step 1 |
| P0 | 修改 monitors.py 集成权限检查器 | 1h | Step 1 |
| P0 | 修改 bots.py 集成权限检查器 | 1h | Step 1 |
| P1 | 修复批量端点重复验证 | 0.5h | - |
| P1 | 创建集成测试文件 | 3h | conftest.py |
| P2 | 添加更多边界测试用例 | 2h | Step 6 |

---

## 预期产出

1. **权限检查器完全集成**：所有需要资源级别权限检查的端点都使用装饰器
2. **消除重复验证**：批量端点预验证，避免循环内重复调用
3. **集成测试覆盖**：HTTP 级别测试覆盖主要端点的权限控制流程
