# CS2智能交易平台第60轮 - 解决方案文档

## 概述

| 项目 | 内容 |
|------|------|
| 迭代轮次 | 第60轮 |
| 任务类型 | 解决方案整理 |
| 整理者 | 23号写手 |
| 日期 | 2026-03-12 |

---

## 问题清单

本轮针对第60轮调研发现的5个P1问题制定解决方案：

| 问题ID | 问题描述 | 优先级 |
|--------|----------|--------|
| P1-1 | 搬砖卖出流程未实现 - trading_service.py未调用Steam上架API | P1 |
| P1-2 | Steam反爬虫未应对 - 需新增AntiCrawlerManager | P1 |
| P1-3 | 异步任务追踪不完整 - 需新增TaskRegistry | P1 |
| P1-4 | 健康检查误判 - 400/401不应视为健康 | P1 |
| P1-5 | 配置热重载未集成 - 需集成到FastAPI生命周期 | P1 |

---

## 问题1：搬砖卖出流程未实现

### 问题描述

`trading_service.py` 中的 `execute_arbitrage` 方法在买入完成后，仅创建了卖出订单记录，但未实际调用 Steam 市场API进行上架操作。

### 当前代码问题

文件：`backend/app/services/trading_service.py`

```python
# 当前实现（第218-255行）
if settings.AUTO_CONFIRM:
    try:
        # 创建卖出订单记录
        sell_order = Order(...)
        self.db.add(sell_order)
        
        # 注意：这里没有调用实际上架API
        if self.steam_market.steam_login or self.steam_market.webcookie:
            logger.info(f"卖出订单创建成功: ...")
            # 仅记录日志，未实际调用上架
        else:
            logger.warning("未配置 Steam 认证信息")
```

### 解决方案

**修改文件**：`backend/app/services/trading_service.py`

**修改位置**：`execute_arbitrage` 方法，约第218-260行

**修改内容**：

1. 在创建卖出订单后，调用 `steam_market.create_listing()` 实际上架
2. 需要先获取物品的 `asset_id`（从Steam库存获取）
3. 添加重试机制和错误处理

```python
# 修改后的代码结构
async def execute_arbitrage(self, ...):
    # ... 买入逻辑 ...
    
    # 买入成功后，获取库存中的asset_id
    if sell_platform == "steam":
        # 获取Steam库存
        inventory_result = await self._get_steam_inventory(user_id)
        
        # 找到对应的asset_id
        asset_id = self._find_asset_by_hash(inventory_result, item.market_hash_name)
        
        if asset_id:
            # 调用实际上架API
            listing_result = await self.steam_market.create_listing(
                asset_id=asset_id,
                app_id=730,
                price=sell_price,
                market_hash_name=item.market_hash_name
            )
            
            if listing_result.get("success"):
                sell_order.status = "listed"
                sell_order.listing_id = listing_result.get("listing_id")
            else:
                sell_order.status = "listing_failed"
                sell_order.error_message = listing_result.get("message")
        else:
            sell_order.status = "asset_not_found"
    
    await self.db.commit()
```

**新增辅助方法**：

```python
async def _get_steam_inventory(self, steam_id: str) -> List[Dict]:
    """获取Steam库存"""
    # 调用steam_service.get_inventory()
    pass

async def _find_asset_by_hash(self, inventory: List[Dict], market_hash_name: str) -> Optional[str]:
    """从库存中查找物品的asset_id"""
    for asset in inventory:
        if asset.get("market_hash_name") == market_hash_name:
            return asset.get("asset_id")
    return None
```

---

## 问题2：Steam反爬虫未应对

### 问题描述

当前代码缺少针对Steam反爬虫机制的应对措施，包括：
- 请求频率限制
- User-Agent轮换
- 请求间隔控制
- 代理IP支持

### 解决方案

**新增文件**：`backend/app/core/anti_crawler.py`

```python
# -*- coding: utf-8 -*-
"""
Steam反爬虫应对管理器
"""
import asyncio
import random
import time
from typing import Optional, Dict, List
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging

import aiohttp

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class RequestRecord:
    """请求记录"""
    timestamp: datetime
    endpoint: str
    success: bool


class AntiCrawlerManager:
    """反爬虫应对管理器"""
    
    # 默认User-Agent列表
    DEFAULT_USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    ]
    
    def __init__(
        self,
        min_interval: float = 0.5,
        max_interval: float = 2.0,
        max_requests_per_minute: int = 20,
        user_agents: List[str] = None,
        proxies: List[str] = None
    ):
        self.min_interval = min_interval
        self.max_interval = max_interval
        self.max_requests_per_minute = max_requests_per_minute
        self.user_agents = user_agents or self.DEFAULT_USER_AGENTS
        self.proxies = proxies or []
        
        # 请求记录
        self._request_history: List[RequestRecord] = []
        self._lock = asyncio.Lock()
        
        # 当前使用的代理索引
        self._proxy_index = 0
    
    async def wait_if_needed(self, endpoint: str = "default"):
        """请求前等待（频率控制）"""
        async with self._lock:
            now = datetime.now()
            cutoff = now - timedelta(minutes=1)
            
            # 清理历史记录
            self._request_history = [
                r for r in self._request_history 
                if r.timestamp > cutoff
            ]
            
            # 检查请求频率
            request_count = len(self._request_history)
            if request_count >= self.max_requests_per_minute:
                # 等待直到最旧的请求超时
                oldest = self._request_history[0]
                wait_time = (oldest.timestamp - cutoff).total_seconds()
                if wait_time > 0:
                    logger.warning(f"请求频率达到限制，等待 {wait_time:.1f} 秒")
                    await asyncio.sleep(wait_time)
            
            # 随机等待间隔
            interval = random.uniform(self.min_interval, self.max_interval)
            await asyncio.sleep(interval)
    
    def get_headers(self) -> Dict[str, str]:
        """获取随机请求头"""
        return {
            "User-Agent": random.choice(self.user_agents),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
        }
    
    def get_proxy(self) -> Optional[str]:
        """获取代理（轮换）"""
        if not self.proxies:
            return None
        
        proxy = self.proxies[self._proxy_index]
        self._proxy_index = (self._proxy_index + 1) % len(self.proxies)
        return proxy
    
    async def record_request(self, endpoint: str, success: bool):
        """记录请求结果"""
        async with self._lock:
            self._request_history.append(
                RequestRecord(
                    timestamp=datetime.now(),
                    endpoint=endpoint,
                    success=success
                )
            )
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        now = datetime.now()
        cutoff = now - timedelta(minutes=1)
        
        recent = [r for r in self._request_history if r.timestamp > cutoff]
        
        return {
            "total_requests": len(self._request_history),
            "requests_last_minute": len(recent),
            "success_rate": sum(1 for r in recent if r.success) / len(recent) if recent else 0,
            "current_proxy": self.proxies[self._proxy_index - 1] if self.proxies else None,
        }


# 全局实例
_anti_crawler: Optional[AntiCrawlerManager] = None


def get_anti_crawler() -> AntiCrawlerManager:
    """获取反爬虫管理器实例"""
    global _anti_crawler
    if _anti_crawler is None:
        _anti_crawler = AntiCrawlerManager(
            min_interval=settings.BUFF_API_INTERVAL,
            max_interval=settings.BUFF_API_INTERVAL * 2,
        )
    return _anti_crawler
```

**配置文件更新**（`backend/app/core/config.py`）：

```python
# 新增配置项
STEAM_ANTI_CRAWLER_ENABLED: bool = Field(default=True, description="启用反爬虫应对")
STEAM_REQUEST_INTERVAL: float = Field(default=0.5, description="Steam请求间隔(秒)")
STEAM_MAX_REQUESTS_PER_MINUTE: int = Field(default=20, description="每分钟最大请求数")
STEAM_PROXIES: str = Field(default="", description="代理IP列表(逗号分隔)")
```

---

## 问题3：异步任务追踪不完整

### 问题描述

当前系统缺乏统一的异步任务追踪机制，导致：
- 任务状态不可查询
- 无法取消正在执行的任务
- 任务失败无法重试

### 解决方案

**新增文件**：`backend/app/core/task_registry.py`

```python
# -*- coding: utf-8 -*-
"""
异步任务注册表
用于追踪和管理后台异步任务
"""
import asyncio
import logging
from typing import Optional, Dict, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from uuid import uuid4

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    """任务状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Task:
    """任务对象"""
    task_id: str
    name: str
    func: Callable
    args: tuple = field(default_factory=tuple)
    kwargs: dict = field(default_factory=dict)
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    retry_count: int = 0
    max_retries: int = 3


class TaskRegistry:
    """任务注册表"""
    
    def __init__(self, max_retries: int = 3):
        self._tasks: Dict[str, Task] = {}
        self._max_retries = max_retries
        self._lock = asyncio.Lock()
    
    async def register(
        self,
        name: str,
        func: Callable,
        *args,
        **kwargs
    ) -> str:
        """注册新任务"""
        task_id = str(uuid4())[:8]
        
        task = Task(
            task_id=task_id,
            name=name,
            func=func,
            args=args,
            kwargs=kwargs,
            max_retries=self._max_retries
        )
        
        async with self._lock:
            self._tasks[task_id] = task
        
        logger.info(f"任务已注册: {task_id} - {name}")
        
        # 自动启动任务
        asyncio.create_task(self._run_task(task_id))
        
        return task_id
    
    async def _run_task(self, task_id: str):
        """执行任务"""
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
        
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now()
        
        try:
            logger.info(f"开始执行任务: {task_id}")
            
            if asyncio.iscoroutinefunction(task.func):
                result = await task.func(*task.args, **task.kwargs)
            else:
                result = task.func(*task.args, **task.kwargs)
            
            task.result = result
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.now()
            
            logger.info(f"任务完成: {task_id}")
            
        except asyncio.CancelledError:
            task.status = TaskStatus.CANCELLED
            task.completed_at = datetime.now()
            logger.warning(f"任务取消: {task_id}")
            
        except Exception as e:
            task.error = str(e)
            task.retry_count += 1
            
            if task.retry_count < task.max_retries:
                logger.warning(f"任务失败，准备重试: {task_id}, retry={task.retry_count}")
                # 延迟重试
                await asyncio.sleep(2 ** task.retry_count)
                asyncio.create_task(self._run_task(task_id))
            else:
                task.status = TaskStatus.FAILED
                task.completed_at = datetime.now()
                logger.error(f"任务失败: {task_id}, error={e}")
    
    async def get_task(self, task_id: str) -> Optional[Task]:
        """获取任务状态"""
        async with self._lock:
            return self._tasks.get(task_id)
    
    async def cancel_task(self, task_id: str) -> bool:
        """取消任务"""
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False
            
            if task.status == TaskStatus.RUNNING:
                # 注意：无法真正取消正在运行的协程
                task.status = TaskStatus.CANCELLED
                return True
            
            return False
    
    async def list_tasks(
        self,
        status: TaskStatus = None,
        limit: int = 100
    ) -> list:
        """列出任务"""
        async with self._lock:
            tasks = list(self._tasks.values())
            
            if status:
                tasks = [t for t in tasks if t.status == status]
            
            # 按创建时间倒序
            tasks.sort(key=lambda t: t.created_at, reverse=True)
            
            return tasks[:limit]
    
    async def clear_completed(self):
        """清理已完成任务"""
        async with self._lock:
            completed_ids = [
                tid for tid, t in self._tasks.items()
                if t.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)
            ]
            
            for tid in completed_ids:
                del self._tasks[tid]
            
            logger.info(f"已清理 {len(completed_ids)} 个已完成任务")


# 全局实例
_task_registry: Optional[TaskRegistry] = None


def get_task_registry() -> TaskRegistry:
    """获取任务注册表实例"""
    global _task_registry
    if _task_registry is None:
        _task_registry = TaskRegistry()
    return _task_registry
```

**API端点**（可选）：`backend/app/api/v1/endpoints/tasks.py`

```python
# 新增任务查询API
@router.get("/tasks/{task_id}")
async def get_task_status(task_id: str):
    """获取任务状态"""
    registry = get_task_registry()
    task = await registry.get_task(task_id)
    
    if not task:
        return error_response(message="任务不存在", code="TASK_NOT_FOUND")
    
    return success_response(data={
        "task_id": task.task_id,
        "name": task.name,
        "status": task.status.value,
        "result": task.result,
        "error": task.error,
        "retry_count": task.retry_count,
    })
```

---

## 问题4：健康检查误判

### 问题描述

`steam_service.py` 的 `health_check` 方法将 HTTP 400 和 401 状态码视为健康，这是不正确的：
- 400：请求参数错误
- 401：认证失败

### 当前代码问题

文件：`backend/app/services/steam_service.py`，第65-67行

```python
async def health_check(self) -> bool:
    # ...
    return response.status in (200, 400, 401)  # 错误：400/401不应视为健康
```

### 解决方案

**修改文件**：`backend/app/services/steam_service.py`

**修改位置**：第47-75行 `health_check` 方法

**修改内容**：

```python
async def health_check(self) -> bool:
    """
    检查 Session 健康状态
    
    Returns:
        是否健康
    """
    if self._session is None:
        return False
    
    # 检查 session 是否已关闭
    if self._session.closed:
        return False
    
    # 尝试发送一个轻量级请求来验证连接
    try:
        test_url = f"{self.base_url}/ISteamUser/GetPlayerSummaries/v0002/"
        params = {"key": self.api_key, "steamids": "76561197960435530"}
        
        async with self._session.get(
            test_url,
            params=params,
            timeout=aiohttp.ClientTimeout(total=5)
        ) as response:
            # 只将200视为健康状态
            # 400/401表示认证或参数问题，应视为不健康
            if response.status == 200:
                return True
            elif response.status == 401:
                logger.warning("Steam API 认证失败，请检查 API Key")
                return False
            elif response.status == 400:
                logger.warning("Steam API 请求参数错误")
                return False
            else:
                logger.warning(f"Steam API 返回异常状态码: {response.status}")
                return False
                
    except asyncio.TimeoutError:
        logger.warning("Steam API 健康检查超时")
        return False
    except aiohttp.ClientError as e:
        logger.warning(f"Steam API 健康检查失败: {e}")
        return False
    except Exception as e:
        logger.warning(f"Steam API 健康检查异常: {e}")
        return False
```

**同步修改**：`main.py` 中的健康检查逻辑

文件：`backend/app/main.py`，约第155-175行

```python
# 检查 Steam API
try:
    steam_api = get_steam_api()
    if await steam_api.health_check():
        checks["steam_api"] = "healthy"
    else:
        checks["steam_api"] = "unhealthy: session check failed"
except Exception as e:
    checks["steam_api"] = f"unhealthy: {str(e)}"
```

---

## 问题5：配置热重载未集成

### 问题描述

虽然 `config.py` 已实现 `ConfigReloader` 类，但未集成到 FastAPI 生命周期中，导致：
- 配置变更需要重启服务才能生效
- 后台任务未启动

### 当前代码问题

文件：`backend/app/main.py`

已存在配置热重载代码，但需要确认是否正确集成。

### 解决方案

**确认现有实现**：查看 `main.py` 第60-80行

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ...
    
    # 启动配置热重载后台任务
    async def config_reload_loop():
        """配置热重载循环"""
        while True:
            try:
                await asyncio.sleep(settings.CONFIG_RELOAD_INTERVAL)
                if check_config_reload():
                    logger.info("配置已自动热重载")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"配置热重载检查异常: {e}")
    
    _config_reload_task = asyncio.create_task(config_reload_loop())
    logger.info(f"配置热重载任务已启动 (间隔: {settings.CONFIG_RELOAD_INTERVAL}秒)")
    
    yield
    
    # 关闭时取消配置热重载任务
    if _config_reload_task:
        _config_reload_task.cancel()
        # ...
```

**结论**：配置热重载已集成，但需要增强以下功能：

1. **配置变更事件发布**：当配置更新时，通知相关服务重新加载
2. **配置验证**：重载前验证配置有效性
3. **优雅重启**：关键配置变更时优雅重启相关组件

**增强实现**：

文件：`backend/app/core/config.py`

```python
class ConfigReloader:
    """配置热重载管理器"""
    
    def __init__(self, config_file: str = ".env"):
        self._config_file = config_file
        self._subscribers: List[Callable[[Dict], None]] = []
        self._last_mtime: float = 0
        self._settings_instance: Optional['Settings'] = None
        self._last_config: Dict = {}
    
    def check_and_reload(self) -> bool:
        """检查并重载配置（需手动调用或配合定时任务）"""
        config_path = Path(self._config_file)
        if not config_path.exists():
            return False
        
        current_mtime = config_path.stat().st_mtime
        if current_mtime > self._last_mtime:
            logger.info(f"检测到配置文件变化: {self._config_file}")
            
            # 获取旧配置用于比较
            old_config = self._last_config.copy()
            
            # 验证新配置
            try:
                new_settings = get_settings()
                new_config = new_settings.model_dump()
                
                # 检查关键配置变更
                critical_changes = self._detect_critical_changes(old_config, new_config)
                
                if critical_changes:
                    logger.warning(f"检测到关键配置变更: {critical_changes}")
                    # 可以选择拒绝重载或触发优雅重启
                
                self._last_config = new_config
                
            except Exception as e:
                logger.error(f"配置验证失败，不应用变更: {e}")
                return False
            
            self._last_mtime = current_mtime
            
            # 清除缓存
            get_settings.cache_clear()
            
            # 重新加载
            new_settings = get_settings()
            
            # 通知订阅者
            for callback in self._subscribers:
                try:
                    callback(new_config)
                except Exception as e:
                    logger.error(f"配置变更回调错误: {e}")
            
            logger.info("配置已热重载")
            return True
        
        return False
    
    def _detect_critical_changes(self, old: Dict, new: Dict) -> List[str]:
        """检测关键配置变更"""
        critical_keys = [
            "DATABASE_URL",
            "REDIS_URL",
            "SECRET_KEY",
            "ENCRYPTION_KEY",
        ]
        
        changes = []
        for key in critical_keys:
            if old.get(key) != new.get(key):
                changes.append(key)
        
        return changes
    
    def subscribe(self, callback: Callable[[Dict], None]):
        """订阅配置变更（传递新配置）"""
        self._subscribers.append(callback)
```

**使用示例**：

```python
# 在服务启动时订阅配置变更
from app.core.config import subscribe_config_change

def on_config_changed(new_config: Dict):
    """配置变更回调"""
    logger.info("收到配置变更通知")
    
    # 重新初始化限流器
    rate_limit_config = new_config.get("RATE_LIMIT_ENDPOINTS")
    if rate_limit_config:
        update_rate_limiter(rate_limit_config)
    
    # 重新初始化缓存
    redis_url = new_config.get("REDIS_URL")
    if redis_url:
        reconnect_cache(redis_url)

subscribe_config_change(on_config_changed)
```

---

## 实施计划

### 实施顺序

| 顺序 | 问题 | 预计工作量 | 依赖 |
|------|------|------------|------|
| 1 | P1-4 健康检查误判 | 0.5h | 无 |
| 2 | P1-5 配置热重载 | 1h | 无 |
| 3 | P1-2 反爬虫管理器 | 2h | 无 |
| 4 | P1-3 任务追踪 | 2h | 无 |
| 5 | P1-1 搬砖卖出 | 3h | P1-2, P1-3 |

### 代码修改清单

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| `backend/app/services/steam_service.py` | 修改 | 修复健康检查逻辑 |
| `backend/app/core/config.py` | 修改 | 增强配置热重载 |
| `backend/app/core/anti_crawler.py` | 新增 | 反爬虫管理器 |
| `backend/app/core/task_registry.py` | 新增 | 任务注册表 |
| `backend/app/services/trading_service.py` | 修改 | 实现卖出流程 |

---

## 验证方法

### P1-4 健康检查

```bash
# 启动服务后检查健康端点
curl http://localhost:8000/health/ready
# 预期：steam_api 显示 unhealthy（如果API key无效）
```

### P1-5 配置热重载

```bash
# 修改 .env 文件
echo "MIN_PROFIT=2.0" >> backend/.env

# 等待30秒后检查日志
tail -f backend/logs/app.log | grep "配置已热重载"
```

### P1-2 反爬虫

```python
# 测试代码
from app.core.anti_crawler import get_anti_crawler

ac = get_anti_crawler()
await ac.wait_if_needed()
headers = ac.get_headers()
print(headers)
```

### P1-3 任务追踪

```bash
# 启动任务后查询
curl http://localhost:8000/api/v1/tasks/{task_id}
# 预期返回任务状态
```

### P1-1 搬砖卖出

```bash
# 触发搬砖流程
curl -X POST http://localhost:8000/api/v1/trading/arbitrage \
  -d '{"item_id": 1, "quantity": 1}'

# 检查日志
tail -f backend/logs/app.log | grep "listing_id"
```

---

## 总结

本轮解决方案针对5个P1问题制定了详细的实施计划：

1. **健康检查误判** - 简单修复，仅改一行代码
2. **配置热重载** - 确认现有实现，增强关键配置检测
3. **反爬虫管理器** - 新增独立模块，支持频率控制、UA轮换、代理
4. **任务追踪** - 新增任务注册表，支持状态查询、重试、取消
5. **搬砖卖出** - 实现完整的上架流程，调用Steam API

预计总工作量：8-10小时

---

*文档生成时间：2026-03-12*
*整理者：23号写手*
