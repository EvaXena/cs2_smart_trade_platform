# 第97轮改进方案

## 问题分析

基于调研，发现以下5个问题需要修复：

---

## P1 - 异步任务资源泄露

**位置**: `app/services/cache.py` - CacheManager 类

**问题**: 后台清理任务和 Redis 重连任务虽然已保存引用，但未使用 TaskGroup 管理

**修复方案**:

### 文件: cache.py

#### 1. 修改 CacheManager 类，添加 TaskGroup 管理

**行号约 746-775**: 修改 `_start_cleanup_task` 和 `_start_redis_reconnect_task` 方法

```python
# 在 CacheManager.__init__ 中添加:
self._task_group: Optional[asyncio.TaskGroup] = None

# 修改 _start_cleanup_task (约行 850-870):
async def _start_cleanup_task(self) -> None:
    """启动后台清理任务（使用 TaskGroup 管理）"""
    if self._current_backend == CacheBackend.MEMORY:
        async def cleanup_loop():
            while True:
                await asyncio.sleep(cleanup_config["interval"])
                await self._execute_cleanup_with_retry(
                    cleanup_config["max_retries"], 
                    cleanup_config["retry_delay"]
                )
        
        # 使用 asyncio.Task 创建任务（已有引用保存）
        self._cleanup_task = asyncio.create_task(cleanup_loop())
        logger.info("Cache cleanup task started (interval: 300s)")

# 修改 _start_redis_reconnect_task (约行 790-830):
async def _start_redis_reconnect_task(self) -> None:
    """启动 Redis 定时重连任务"""
    if self._backend != CacheBackend.REDIS:
        return
    
    async def reconnect_loop():
        # ... 现有逻辑保持不变 ...
        pass
    
    # 创建任务并保存引用
    self._redis_reconnect_task = asyncio.create_task(reconnect_loop())
```

#### 2. 修改 shutdown 方法使用 TaskGroup（可选优化）

**行号约 870-890**: 改进 shutdown 方法

```python
async def shutdown(self) -> None:
    """关闭缓存管理器并清理后台任务"""
    # 收集所有待取消任务
    pending_tasks = []
    
    if self._cleanup_task is not None and not self._cleanup_task.done():
        self._cleanup_task.cancel()
        pending_tasks.append(self._cleanup_task)
    
    if self._redis_reconnect_task is not None and not self._redis_reconnect_task.done():
        self._redis_reconnect_task.cancel()
        pending_tasks.append(self._redis_reconnect_task)
    
    # 等待所有任务取消完成
    if pending_tasks:
        try:
            await asyncio.gather(*pending_tasks, return_exceptions=True)
        except Exception as e:
            logger.warning(f"Error waiting for tasks: {e}")
    
    # 清理引用
    self._cleanup_task = None
    self._redis_reconnect_task = None
    
    # 断开 Redis 连接
    if self._redis_cache:
        await self._redis_cache.disconnect()
```

---

## P2-1 - RuntimeWarning

**位置**: 
- `app/core/risk_manager.py`
- `app/services/trading_service.py`

**问题**: 异步协程未被正确 await

**修复方案**:

### 文件: risk_manager.py

#### 检查并修复所有 async def 调用

**行号约 340-360**: `_get_redis` 方法

```python
# 当前代码（可能有问题）:
async def _get_redis(self):
    if self._redis is None:
        try:
            self._redis = await get_redis()  # 已正确 await
        except Exception as e:
            ...
    return self._redis
```

**确保调用处正确 await**:
- 在 `check_trade_risk` 方法（约行 390）中调用 `_get_redis` 时需确保 await
- 检查所有调用 `self._redis` 的地方是否有 await

### 文件: trading_service.py

#### 1. 检查 `_send_webhook_notification` 方法

**行号约 100-145**: 确保所有 asyncio 调用都被正确 await

```python
# 当前代码第 108 行:
task = asyncio.create_task(
    webhook_manager.send_webhook(...)
)
# 保存任务引用 - 已正确处理

# 第 128 行:
loop.call_soon_threadsafe(
    lambda: asyncio.create_task(self._remove_task(task_key))
)
# 这里的 lambda 调用 asyncio.create_task 可能会产生警告
# 建议修改为:
loop.call_soon_threadsafe(
    lambda: asyncio.ensure_future(self._remove_task(task_key))
)
```

#### 2. 搜索并修复所有未 await 的协程

```bash
# 使用以下命令搜索:
grep -rn "async def" app/core/risk_manager.py | head -20
grep -rn "async def" app/services/trading_service.py | head -30
```

**需要检查的关键位置**:
1. `trading_service.py` 行 492: `asyncio.create_task(self._task_registry.run(...))` - 需要确保 run 方法正确处理
2. 所有调用 `await` 的地方是否完整

---

## P2-2 - 缓存TTL抖动

**位置**: `app/services/cache.py` - CacheEntry 类

**问题**: 使用 `random.uniform(0.9, 1.1)` 雪崩保护导致测试边界不确定性

**修复方案**:

### 文件: cache.py

#### 1. 修改 CacheEntry 类，添加确定性抖动选项

**行号约 120-145**: 修改 `__init__` 方法

```python
class CacheEntry:
    """缓存条目（用于内存缓存）"""
    
    # 雪崩保护抖动范围
    AVALANCHE_JITTER_MIN = 0.9
    AVALANCHE_JITTER_MAX = 1.1
    
    # 类级别标志，用于测试环境禁用随机抖动
    _enable_jitter = True
    
    # 新增: 可选的确定性抖动种子
    _jitter_seed: Optional[int] = None
    
    def __init__(self, value: Any, ttl: int, enable_avalanche_protection: bool = True):
        self.value = value
        self.original_ttl = ttl
        
        # 缓存雪崩保护：为 TTL 添加随机抖动（默认启用）
        if enable_avalanche_protection and ttl > 0 and CacheEntry._enable_jitter:
            # 新增: 支持确定性抖动
            if CacheEntry._jitter_seed is not None:
                import random
                random.seed(CacheEntry._jitter_seed)
                jitter = random.uniform(
                    self.AVALANCHE_JITTER_MIN, 
                    self.AVALANCHE_JITTER_MAX
                )
                # 重置随机种子
                random.seed()
            else:
                jitter = random.uniform(
                    self.AVALANCHE_JITTER_MIN, 
                    self.AVALANCHE_JITTER_MAX
                )
            actual_ttl = int(ttl * jitter)
            actual_ttl = max(1, actual_ttl)
        else:
            actual_ttl = ttl
        self.expire_at = time.time() + actual_ttl if actual_ttl > 0 else float('inf')
```

#### 2. 添加类方法支持确定性抖动

**行号约 155-160**: 添加新方法

```python
@classmethod
def set_jitter_enabled(cls, enabled: bool) -> None:
    """设置是否启用随机抖动（用于测试环境）"""
    cls._enable_jitter = enabled

@classmethod
def set_jitter_seed(cls, seed: Optional[int]) -> None:
    """设置确定性抖动种子（用于测试环境）"""
    cls._jitter_seed = seed
```

#### 3. 更新测试文件使用确定性抖动

**文件**: tests/test_cache_p1_fix.py

```python
@pytest.fixture(autouse=True)
def disable_jitter():
    """禁用随机抖动以确保测试稳定性"""
    original = CacheEntry._enable_jitter
    original_seed = CacheEntry._jitter_seed
    
    # 两种方案任选其一:
    # 方案1: 完全禁用抖动
    CacheEntry.set_jitter_enabled(False)
    
    # 方案2: 使用固定种子（保持抖动行为但确定）
    # CacheEntry.set_jitter_seed(42)
    # CacheEntry.set_jitter_enabled(True)
    
    yield
    
    # 恢复
    CacheEntry.set_jitter_enabled(original)
    CacheEntry.set_jitter_seed(original_seed)
```

---

## P3-1 - 任务管理不完善

**位置**: `app/services/trading_service.py`

**问题**: 异步任务缺少重试机制和 TaskGroup 管理

**修复方案**:

### 文件: trading_service.py

#### 1. 在 TradingEngine 类中添加 TaskGroup

**行号约 45-60**: 修改 `__init__` 方法

```python
class TradingEngine:
    """交易引擎"""
    
    # 类级别的全局锁字典
    _global_item_locks: Dict[int, asyncio.Lock] = {}
    _global_locks_lock: asyncio.Lock = None
    
    def __init__(self, db: AsyncSession):
        self.db = db
        # ... 现有初始化代码 ...
        
        # 新增: TaskGroup 管理后台任务
        self._task_group: Optional[asyncio.TaskGroup] = None
        
        # 保存异步任务引用
        self._active_tasks: Dict[str, asyncio.Task] = {}
        self._tasks_lock = asyncio.Lock()
```

#### 2. 添加任务重试装饰器/工具函数

**文件顶部添加**:

```python
def async_retry(max_attempts: int = 3, delay: float = 1.0, backoff: float = 2.0):
    """异步重试装饰器"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            current_delay = delay
            
            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_attempts - 1:
                        logger.warning(
                            f"Attempt {attempt + 1}/{max_attempts} failed: {e}. "
                            f"Retrying in {current_delay}s..."
                        )
                        await asyncio.sleep(current_delay)
                        current_delay *= backoff
                    else:
                        logger.error(f"All {max_attempts} attempts failed")
            
            raise last_exception
        
        return wrapper
    return decorator
```

#### 3. 修改 `_send_webhook_notification` 使用重试机制

**行号约 95-145**: 改进 webhook 发送逻辑

```python
async def _send_webhook_notification(
    self,
    event_type: WebhookEventType,
    order_id: str,
    user_id: int,
    data: Dict[str, Any]
) -> None:
    """发送 Webhook 通知（带重试机制）"""
    
    @async_retry(max_attempts=3, delay=1.0)
    async def send_with_retry():
        return await webhook_manager.send_webhook(
            event_type=event_type,
            data=data,
            user_id=user_id,
            order_id=order_id
        )
    
    try:
        task = asyncio.create_task(send_with_retry())
        task_key = f"webhook_{event_type.value}_{order_id}_{user_id}"
        
        async with self._tasks_lock:
            self._active_tasks[task_key] = task
        
        # 清理回调
        def cleanup_callback(t: asyncio.Task) -> None:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.call_soon_threadsafe(
                        lambda: asyncio.ensure_future(self._remove_task(task_key))
                    )
            except RuntimeError:
                pass
        
        task.add_done_callback(cleanup_callback)
        
    except Exception as e:
        logger.warning(f"Failed to send webhook notification: {e}")
```

#### 4. 添加启动/停止 TaskGroup 的方法

**在 TradingEngine 类中添加**:

```python
async def start_task_group(self) -> None:
    """启动 TaskGroup 用于管理后台任务"""
    if self._task_group is None:
        self._task_group = asyncio.TaskGroup()
        await self._task_group.__aenter__()
        logger.info("TradingEngine TaskGroup started")

async def stop_task_group(self) -> None:
    """停止 TaskGroup"""
    if self._task_group is not None:
        await self._task_group.__aexit__(None, None, None)
        self._task_group = None
        logger.info("TradingEngine TaskGroup stopped")
```

---

## P3-2 - 代码重复

**位置**: 多个 endpoint 文件 (`app/api/v1/endpoints/*.py`)

**问题**: 存在重复的验证模式

**修复方案**:

### 文件: app/utils/validators.py

#### 1. 添加批量验证函数

**文件末尾添加**:

```python
def validate_trade_request(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    验证交易请求数据（买入/卖出）
    
    适用于所有交易相关的 API 端点
    
    Args:
        data: 请求数据字典
    
    Returns:
        验证后的数据字典
    
    Raises:
        ValueError: 验证失败
    """
    validated = {}
    
    # 验证 item_id（必需）
    if 'item_id' not in data:
        raise ValueError("item_id 是必需参数")
    validated['item_id'] = validate_item_id(data['item_id'])
    
    # 验证 price（必需）
    if 'price' not in data:
        raise ValueError("price 是必需参数")
    validated['price'] = validate_price(data['price'])
    
    # 验证 quantity（可选，默认1）
    quantity = data.get('quantity', 1)
    validated['quantity'] = validate_quantity(quantity)
    
    # 验证 side（可选，默认 buy）
    side = data.get('side', 'buy')
    if isinstance(side, str):
        side = side.lower()
        if side not in ['buy', 'sell']:
            raise ValueError("side 必须是 'buy' 或 'sell'")
    validated['side'] = side
    
    return validated


def validate_pagination_params(params: Dict[str, Any]) -> Dict[str, int]:
    """
    验证分页参数
    
    Args:
        params: 请求参数字典
    
    Returns:
        验证后的分页参数 {page, page_size}
    """
    page = params.get('page', 1)
    page_size = params.get('page_size', 20)
    
    return {
        'page': validate_positive_int(page, 'page'),
        'page_size': validate_limit(page_size)
    }


def validate_positive_int(value: Any, field_name: str = "value") -> int:
    """
    验证正整数
    
    Args:
        value: 值
        field_name: 字段名称
    
    Returns:
        验证后的整数
    """
    if isinstance(value, str):
        try:
            value = int(value)
        except ValueError:
            raise ValueError(f"{field_name}必须是整数类型")
    
    if not isinstance(value, int):
        raise ValueError(f"{field_name}必须是整数类型")
    
    if value <= 0:
        raise ValueError(f"{field_name}必须大于0")
    
    return value
```

#### 2. 更新 endpoint 文件使用批量验证

**示例 - orders.py**:

```python
# 之前（重复验证）:
@router.post("/orders")
async def create_order(order_data: OrderCreate):
    validated_item_id = validate_item_id(order_data.item_id)
    validated_price = validate_price(order_data.price)
    validated_quantity = validate_quantity(order_data.quantity)
    # ...

# 之后（使用批量验证）:
from app.utils.validators import validate_trade_request

@router.post("/orders")
async def create_order(order_data: OrderCreate):
    # 批量验证
    validated = validate_trade_request(order_data.dict())
    # validated = {'item_id': ..., 'price': ..., 'quantity': ..., 'side': ...}
    # ...
```

**示例 - items.py**:

```python
# 之前:
@router.get("/items")
async def get_items(limit: int = 20):
    validated_limit = validate_limit(limit)
    # ...

# 之后:
from app.utils.validators import validate_pagination_params

@router.get("/items")
async def get_items(page: int = 1, page_size: int = 20):
    # 使用分页验证
    pagination = validate_pagination_params({'page': page, 'page_size': page_size})
    # ...
```

---

## 修复优先级

| 优先级 | 问题 | 预计工作量 |
|--------|------|-----------|
| P1 | 异步任务资源泄露 | 小 |
| P2-1 | RuntimeWarning | 中 |
| P2-2 | 缓存TTL抖动 | 小 |
| P3-1 | 任务管理不完善 | 中 |
| P3-2 | 代码重复 | 大 |

---

## 测试建议

修复后运行以下测试确保不影响现有功能:

```bash
# 运行缓存测试
python -m pytest tests/test_cache_p1_fix.py -v

# 运行交易服务测试
python -m pytest tests/test_trading_service.py -v

# 运行风险管理器测试
python -m pytest tests/test_risk_manager.py -v

# 运行所有测试
python -m pytest tests/ -v --tb=short
```
