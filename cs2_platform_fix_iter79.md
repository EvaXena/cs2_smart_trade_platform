# 第79轮修复方案

## 概述
基于第78轮审核发现的问题，本轮需要修复3个问题（P0×2 + P1×1）

---

## 问题1: 权限检查器未集成到端点 🔴 P0

### 问题描述
`ResourcePermissionChecker` 已完整实现，但未集成到具体端点，导致资源级别权限检查未生效。

### 涉及文件
- `app/api/v1/endpoints/orders.py`
- `app/api/v1/endpoints/inventory.py`
- `app/api/v1/endpoints/monitors.py`
- `app/api/v1/endpoints/bots.py`
- `app/core/permissions.py` (需新增 registry 模块)

### 修复内容

**Step 1: 创建资源获取函数注册模块**
```python
# 新建 app/core/permissions_registry.py
from app.core.permissions import ResourcePermissionChecker
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

async def get_order_getter(order_id, db: AsyncSession):
    from app.models.order import Order
    result = await db.execute(select(Order).where(Order.order_id == order_id))
    return result.scalar_one_or_none()

# 注册资源获取函数
ResourcePermissionChecker.register_resource_types(
    resource_type="order",
    owner_field="user_id",
    getter=get_order_getter,
)
```

**Step 2: 修改20+个端点添加装饰器**
```python
from app.core.permissions import verify_resource_owner

@router.get("/{order_id}", response_model=OrderResponse)
@verify_resource_owner("order", "order_id")
async def get_order(...):
    ...
```

### 需要集成的端点（20+个）
| 端点文件 | 端点 | 资源类型 |
|---------|------|---------|
| orders.py | GET /{order_id}, DELETE /{order_id}, POST /batch/cancel | order |
| inventory.py | GET/PUT/DELETE /{inventory_id}, POST /unlist | inventory |
| monitors.py | GET/PUT/DELETE /{monitor_id}, start/stop/logs | monitor |
| bots.py | GET/PUT/DELETE /{bot_id}, login/logout/refresh | bot |

### 风险
- ⚠️ 可能影响现有业务逻辑，需全面回归测试
- ⚠️ 装饰器顺序需要正确，与其他装饰器兼容

---

## 问题2: 批量端点验证器重复使用 🟠 P1

### 问题描述
- `orders.py` 批量创建在循环内调用 `validate_xxx()`，Pydantic已验证过，造成重复
- `items.py` BatchValidator 调用方式错误

### 涉及文件
- `app/api/v1/endpoints/orders.py`
- `app/api/v1/endpoints/items.py`

### 修复内容

**orders.py 修复**：使用预验证模式
```python
@router.post("/batch", response_model=OrderBatchResponse)
async def create_orders_batch(...):
    # 预验证整个批次（只执行一次）
    validated_orders = await _order_batch_create_validator.validate(request.orders)
    
    # 循环中不再重复验证
    for order_data in validated_orders:
        order_total = order_data.price * order_data.quantity
        ...
```

**items.py 修复**：修正调用方式
```python
# 改为直接传入列表
validated_request = await _item_batch_validator.validate(request.item_ids)
```

### 风险
- ⚠️ 需确保预验证与循环内逻辑兼容

---

## 问题3: 缺少集成测试 🟠 P1

### 问题描述
当前仅有单元测试，缺少HTTP级别的集成测试验证权限控制流程。

### 涉及文件
- `tests/test_permissions_integration.py` (新建)
- `tests/test_orders_integration.py` (新建)
- `tests/test_inventory_integration.py` (新建)
- `tests/test_monitors_integration.py` (新建)
- `tests/test_bots_integration.py` (新建)

### 修复内容

**创建测试文件结构**：
```
tests/
├── test_permissions_integration.py  # 权限检查器集成测试
├── test_orders_integration.py      # 订单端点集成测试
├── test_inventory_integration.py  # 库存端点集成测试
├── test_monitors_integration.py    # 监控端点集成测试
└── test_bots_integration.py        # 机器人端点集成测试
```

**测试用例设计**：
```python
@pytest.mark.asyncio
async def test_get_order_forbidden(client: AsyncClient, auth_token: str):
    """非所有者不能获取他人订单"""
    # 用户A创建订单
    # 用户B尝试访问 → 期望 403
    
@pytest.mark.asyncio
async def test_get_order_unauthorized(client: AsyncClient):
    """未认证访问被拒绝"""
    response = await client.get("/api/v1/orders/ORD-001")
    assert response.status_code == 401
```

### 风险
- ⚠️ 集成测试依赖外部服务（Redis、DB），需确保测试环境隔离

---

## 执行计划

| 优先级 | 任务 | 预计工作量 | 依赖 |
|--------|------|-----------|------|
| P0 | 创建 permissions_registry.py | 1h | permissions.py |
| P0 | 修改 orders.py 集成权限检查器 | 1h | Step 1 |
| P0 | 修改 inventory.py 集成权限检查器 | 1h | Step 1 |
| P0 | 修改 monitors.py 集成权限检查器 | 1h | Step 1 |
| P0 | 修改 bots.py 集成权限检查器 | 1h | Step 1 |
| P1 | 修复批量端点重复验证 | 0.5h | - |
| P1 | 创建集成测试文件 | 3h | conftest.py |
