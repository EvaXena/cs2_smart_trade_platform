# -*- coding: utf-8 -*-
"""
任务注册表
用于追踪和管理搬砖任务的生命周期
"""
import asyncio
import logging
import time
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
import uuid

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    """任务状态"""
    PENDING = "pending"           # 待处理
    BUYING = "buying"            # 买入中
    WAITING_SETTLE = "waiting_settle"  # 等待到账
    SELLING = "selling"          # 卖出中
    COMPLETED = "completed"       # 已完成
    FAILED = "failed"            # 失败
    CANCELLED = "cancelled"      # 已取消


class TaskType(Enum):
    """任务类型"""
    ARBITRAGE = "arbitrage"      # 搬砖
    BUY = "buy"                   # 单纯买入
    SELL = "sell"                # 单纯卖出
    MONITOR = "monitor"          # 监控


@dataclass
class TaskStep:
    """任务步骤"""
    step: str
    status: str
    message: str
    timestamp: float = field(default_factory=time.time)
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ArbitrageTask:
    """搬砖任务"""
    task_id: str
    task_type: str
    item_id: int
    item_name: str
    quantity: int
    buy_price: float
    buy_platform: str
    sell_platform: str
    expected_sell_price: float = 0
    actual_sell_price: float = 0
    
    # 状态
    status: str = TaskStatus.PENDING.value
    
    # 时间戳
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    
    # 订单ID
    buy_order_id: Optional[str] = None
    sell_order_id: Optional[str] = None
    
    # 步骤记录
    steps: List[TaskStep] = field(default_factory=list)
    
    # 用户
    user_id: Optional[int] = None
    
    # 错误信息
    error_message: Optional[str] = None
    
    # 元数据
    metadata: Dict[str, Any] = field(default_factory=dict)


class TaskRegistry:
    """
    任务注册表
    
    功能：
    1. 任务创建和状态追踪
    2. 任务步骤记录
    3. 任务超时管理
    4. 任务统计
    """
    
    def __init__(self, task_ttl: int = 3600):
        """
        初始化任务注册表
        
        Args:
            task_ttl: 任务过期时间（秒），默认1小时
        """
        self._tasks: Dict[str, ArbitrageTask] = {}
        self._task_ttl = task_ttl
        self._lock = asyncio.Lock()
        
        # 统计
        self._stats = {
            "total_created": 0,
            "total_completed": 0,
            "total_failed": 0,
            "total_cancelled": 0,
        }
    
    async def create_task(
        self,
        task_type: TaskType,
        item_id: int,
        item_name: str,
        quantity: int,
        buy_price: float,
        buy_platform: str = "buff",
        sell_platform: str = "steam",
        user_id: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> ArbitrageTask:
        """
        创建任务
        
        Args:
            task_type: 任务类型
            item_id: 饰品ID
            item_name: 饰品名称
            quantity: 数量
            buy_price: 买入价格
            buy_platform: 买入平台
            sell_platform: 卖出平台
            user_id: 用户ID
            metadata: 额外数据
            
        Returns:
            创建的任务
        """
        async with self._lock:
            task_id = f"{task_type.value}_{uuid.uuid4().hex[:8]}"
            
            task = ArbitrageTask(
                task_id=task_id,
                task_type=task_type.value,
                item_id=item_id,
                item_name=item_name,
                quantity=quantity,
                buy_price=buy_price,
                buy_platform=buy_platform,
                sell_platform=sell_platform,
                user_id=user_id,
                metadata=metadata or {}
            )
            
            self._tasks[task_id] = task
            self._stats["total_created"] += 1
            
            # 记录初始步骤
            task.steps.append(TaskStep(
                step="created",
                status="success",
                message=f"任务已创建: {task_id}"
            ))
            
            logger.info(f"任务创建: {task_id}, item={item_name}, qty={quantity}, price={buy_price}")
            
            return task
    
    async def register(
        self,
        task_name: str,
        coro
    ) -> str:
        """
        注册任务协程
        
        Args:
            task_name: 任务名称
            coro: 协程函数
            
        Returns:
            任务ID
        """
        # 创建简单的任务来保存协程
        task_id = f"task_{uuid.uuid4().hex[:8]}"
        
        async with self._lock:
            task = ArbitrageTask(
                task_id=task_id,
                task_type="custom",
                item_id=0,
                item_name=task_name,
                quantity=1,
                buy_price=0,
                buy_platform="",
                sell_platform="",
                status=TaskStatus.PENDING.value
            )
            # 保存协程以便后续执行
            task._coro = coro
            
            self._tasks[task_id] = task
            self._stats["total_created"] += 1
            
            logger.info(f"任务已注册: {task_id}, name={task_name}")
            
            return task_id
    
    async def update_status(
        self,
        task_id: str,
        status: TaskStatus,
        message: str = "",
        data: Optional[Dict[str, Any]] = None
    ):
        """
        更新任务状态
        
        Args:
            task_id: 任务ID
            status: 新状态
            message: 状态消息
            data: 额外数据
        """
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                logger.warning(f"任务不存在: {task_id}")
                return
            
            old_status = task.status
            task.status = status.value
            task.updated_at = time.time()
            
            # 记录步骤
            step_name = status.value
            task.steps.append(TaskStep(
                step=step_name,
                status="success" if status not in [TaskStatus.FAILED, TaskStatus.CANCELLED] else "failed",
                message=message,
                data=data or {}
            ))
            
            # 更新统计
            if status == TaskStatus.COMPLETED:
                self._stats["total_completed"] += 1
                task.completed_at = time.time()
            elif status == TaskStatus.FAILED:
                self._stats["total_failed"] += 1
            elif status == TaskStatus.CANCELLED:
                self._stats["total_cancelled"] += 1
            
            logger.info(f"任务状态更新: {task_id}, {old_status} -> {status.value}, message={message}")
    
    async def set_buy_order(self, task_id: str, order_id: str):
        """设置买入订单ID"""
        async with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task.buy_order_id = order_id
                task.updated_at = time.time()
                task.steps.append(TaskStep(
                    step="buy_order_created",
                    status="success",
                    message=f"买入订单已创建: {order_id}",
                    data={"order_id": order_id}
                ))
    
    async def set_sell_order(
        self,
        task_id: str,
        order_id: str,
        sell_price: float = None
    ):
        """设置卖出订单ID"""
        async with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task.sell_order_id = order_id
                if sell_price:
                    task.actual_sell_price = sell_price
                task.updated_at = time.time()
                task.steps.append(TaskStep(
                    step="sell_order_created",
                    status="success",
                    message=f"卖出订单已创建: {order_id}",
                    data={"order_id": order_id, "price": sell_price}
                ))
    
    async def set_error(self, task_id: str, error_message: str):
        """设置错误信息"""
        async with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task.error_message = error_message
                task.updated_at = time.time()
                task.steps.append(TaskStep(
                    step="error",
                    status="failed",
                    message=error_message
                ))
    
    async def get_task(self, task_id: str) -> Optional[ArbitrageTask]:
        """获取任务"""
        return self._tasks.get(task_id)
    
    async def get_user_tasks(
        self,
        user_id: int,
        status: Optional[TaskStatus] = None,
        limit: int = 50
    ) -> List[ArbitrageTask]:
        """获取用户任务"""
        async with self._lock:
            tasks = [
                t for t in self._tasks.values()
                if t.user_id == user_id
            ]
            
            if status:
                tasks = [t for t in tasks if t.status == status.value]
            
            # 按更新时间排序
            tasks.sort(key=lambda t: t.updated_at, reverse=True)
            
            return tasks[:limit]
    
    async def get_pending_tasks(self) -> List[ArbitrageTask]:
        """获取待处理任务"""
        async with self._lock:
            return [
                t for t in self._tasks.values()
                if t.status in [TaskStatus.PENDING.value, TaskStatus.BUYING.value]
            ]
    
    async def cancel_task(self, task_id: str, reason: str = ""):
        """取消任务"""
        await self.update_status(
            task_id,
            TaskStatus.CANCELLED,
            message=reason or "任务被取消"
        )
    
    async def cleanup_expired(self):
        """清理过期任务"""
        async with self._lock:
            current_time = time.time()
            expired = [
                task_id for task_id, task in self._tasks.items()
                if current_time - task.updated_at > self._task_ttl
            ]
            
            for task_id in expired:
                del self._tasks[task_id]
            
            if expired:
                logger.info(f"清理过期任务: {len(expired)} 个")
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            **self._stats,
            "active_tasks": len(self._tasks),
            "by_status": self._count_by_status()
        }
    
    def _count_by_status(self) -> Dict[str, int]:
        """按状态统计"""
        counts = {}
        for task in self._tasks.values():
            counts[task.status] = counts.get(task.status, 0) + 1
        return counts
    
    async def get_task_history(
        self,
        hours: int = 24,
        limit: int = 100
    ) -> List[ArbitrageTask]:
        """获取历史任务"""
        async with self._lock:
            cutoff = time.time() - (hours * 3600)
            tasks = [
                t for t in self._tasks.values()
                if t.updated_at >= cutoff
            ]
            tasks.sort(key=lambda t: t.updated_at, reverse=True)
            return tasks[:limit]
    
    async def run(
        self,
        task_id: str,
        wait: bool = True,
        timeout: float = None
    ) -> Optional[Any]:
        """
        运行任务
        
        Args:
            task_id: 任务ID
            wait: 是否等待任务完成
            timeout: 超时时间（秒）
            
        Returns:
            任务结果（如果wait=True）
        """
        task = self._tasks.get(task_id)
        if not task:
            logger.warning(f"任务不存在: {task_id}")
            return None
        
        # 获取任务的协程函数并执行
        # 注意：实际执行需要在register时保存协程
        # 这里需要task对象包含可执行的协程
        if not hasattr(task, '_coro'):
            logger.warning(f"任务没有协程: {task_id}")
            return None
        
        async def execute_task():
            try:
                await self.update_status(task_id, TaskStatus.BUYING, "任务执行中")
                result = await task._coro
                await self.update_status(task_id, TaskStatus.COMPLETED, "任务完成", {"result": result})
                return result
            except Exception as e:
                logger.error(f"任务执行失败: {task_id}, error={e}")
                await self.update_status(task_id, TaskStatus.FAILED, str(e))
                raise
        
        async_task = asyncio.create_task(execute_task())
        
        if wait:
            try:
                if timeout:
                    return await asyncio.wait_for(async_task, timeout=timeout)
                return await async_task
            except asyncio.TimeoutError:
                logger.warning(f"任务执行超时: {task_id}")
                return None
        else:
            # 不等待，返回任务ID
            return task_id


# 全局实例
_task_registry: Optional[TaskRegistry] = None


class TaskRunner:
    """任务运行器"""
    
    def __init__(self, registry: TaskRegistry):
        self.registry = registry
        self._running_tasks: Dict[str, asyncio.Task] = {}
    
    async def run_task(self, task_id: str, coro):
        """运行任务"""
        task = asyncio.create_task(coro)
        self._running_tasks[task_id] = task
        return task
    
    async def wait_task(self, task_id: str, timeout: float = None):
        """等待任务完成"""
        task = self._running_tasks.get(task_id)
        if not task:
            return None
        try:
            if timeout:
                return await asyncio.wait_for(task, timeout=timeout)
            return await task
        except asyncio.TimeoutError:
            return None
    
    def cancel_task(self, task_id: str):
        """取消任务"""
        task = self._running_tasks.get(task_id)
        if task:
            task.cancel()
            return True
        return False


def get_task_registry() -> TaskRegistry:
    """获取任务注册表实例"""
    global _task_registry
    if _task_registry is None:
        _task_registry = TaskRegistry()
    return _task_registry
