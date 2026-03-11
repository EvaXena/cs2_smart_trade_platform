# -*- coding: utf-8 -*-
"""
价格监控服务（分布式版本）
支持多进程水平扩展（Redis 分布式锁）
"""
import asyncio
import logging
from typing import Dict, List, Optional, Callable
from datetime import datetime, timedelta

import aiohttp

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.item import Item, PriceHistory
from app.models.monitor import MonitorTask, MonitorLog
from app.services.buff_service import get_buff_client
from app.services.steam_service import get_steam_api
from app.core.config import settings
from app.core.redis_manager import get_redis

logger = logging.getLogger(__name__)


class DistributedLock:
    """Redis 分布式锁"""
    
    def __init__(self, redis_client, key: str, ttl: int = 300):
        self._redis = redis_client
        self._key = f"lock:{key}"
        self._ttl = ttl
        self._lock_id = None
    
    async def acquire(self, blocking: bool = True, timeout: int = 30) -> bool:
        """获取锁"""
        import uuid
        self._lock_id = str(uuid.uuid4())
        start_time = asyncio.get_event_loop().time()
        
        while True:
            # 尝试设置锁
            acquired = await self._redis.set(
                self._key,
                self._lock_id,
                nx=True,
                ex=self._ttl
            )
            
            if acquired:
                logger.debug(f"Lock acquired: {self._key}")
                return True
            
            if not blocking:
                return False
            
            # 检查超时
            if asyncio.get_event_loop().time() - start_time > timeout:
                logger.warning(f"Lock timeout: {self._key}")
                return False
            
            # 等待后重试
            await asyncio.sleep(0.5)
    
    async def release(self) -> bool:
        """释放锁"""
        if self._lock_id is None:
            return False
        
        # 使用 Lua 脚本确保原子性释放
        lua_script = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("del", KEYS[1])
        else
            return 0
        end
        """
        try:
            result = await self._redis.eval(lua_script, 1, self._key, self._lock_id)
            return result == 1
        except Exception as e:
            logger.error(f"Lock release error: {e}")
            return False
    
    async def extend(self, ttl: int = None) -> bool:
        """延长锁的 TTL"""
        if ttl is None:
            ttl = self._ttl
        
        lua_script = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("expire", KEYS[1], ARGV[2])
        else
            return 0
        end
        """
        try:
            result = await self._redis.eval(lua_script, 1, self._key, self._lock_id, ttl)
            return result == 1
        except Exception as e:
            logger.error(f"Lock extend error: {e}")
            return False
    
    async def __aenter__(self):
        await self.acquire()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.release()


class PriceMonitor:
    """价格监控服务（分布式版本）"""
    
    def __init__(self, db: AsyncSession, node_id: Optional[str] = None):
        self.db = db
        self.buff_client = get_buff_client()
        self.steam_api = get_steam_api()
        self.running = False
        self.monitor_tasks: Dict[int, MonitorTask] = {}
        self.alert_callbacks: List[Callable] = []
        # 节点 ID，用于分布式锁标识
        self.node_id = node_id or f"monitor-{id(self)}"
    
    @classmethod
    async def get_redis(cls):
        """获取 Redis 客户端（使用统一管理器）"""
        return await get_redis()
    
    @classmethod
    async def close_redis(cls):
        """关闭 Redis 连接（由全局管理器统一管理）"""
        pass  # 不再单独关闭，由 redis_manager 统一管理
    
    async def acquire_leader_lock(self, lock_name: str, ttl: int = 60) -> DistributedLock:
        """获取领导者锁"""
        redis_client = await self.get_redis()
        lock = DistributedLock(redis_client, lock_name, ttl)
        return lock
    
    async def start(self):
        """启动监控（分布式协调）"""
        # 尝试获取领导者锁
        lock = await self.acquire_leader_lock("price_monitor_leader", ttl=60)
        
        if await lock.acquire(blocking=False):
            self.running = True
            logger.info(f"价格监控服务已启动 (节点: {self.node_id})")
            
            # 启动各个监控任务
            asyncio.create_task(self.poll_buff_prices())
            asyncio.create_task(self.check_arbitrage())
            
            # 启动锁续期任务
            asyncio.create_task(self._lock_renewal(lock))
        else:
            logger.info(f"监控服务已在其他节点运行，等待任务分配 (节点: {self.node_id})")
            # 作为备用节点，可以执行其他任务
            self.running = True
    
    async def _lock_renewal(self, lock: DistributedLock):
        """定期续期领导者锁"""
        while self.running:
            await asyncio.sleep(30)  # 每30秒续期一次
            if self.running:
                await lock.extend(60)
    
    async def stop(self):
        """停止监控"""
        self.running = False
        logger.info(f"价格监控服务已停止 (节点: {self.node_id})")
    
    async def poll_buff_prices(self):
        """轮询 BUFF 价格（分布式版本）"""
        # 使用分布式锁防止多节点同时轮询
        lock = await self.acquire_leader_lock("buff_price_poll", ttl=300)
        
        while self.running:
            try:
                # 尝试获取锁
                if not await lock.acquire(blocking=False):
                    # 未获取到锁，等待后重试
                    await asyncio.sleep(60)
                    continue
                
                # 获取锁成功，执行轮询
                try:
                    # 获取需要监控的饰品
                    result = await self.db.execute(
                        select(Item).limit(100)
                    )
                    items = result.scalars().all()
                    
                    for item in items:
                        try:
                            # 获取 BUFF 价格
                            price_data = await self.buff_client.get_price_overview(
                                item.market_hash_name
                            )
                            
                            if price_data:
                                new_price = float(price_data.get("lowest_price", 0))
                                
                                # 只有价格变化时才更新和记录历史 (P1-问题6)
                                if item.current_price is None or abs(new_price - item.current_price) > 0.01:
                                    # 更新数据库
                                    item.current_price = new_price
                                    item.volume_24h = int(price_data.get("volume", 0))
                                    
                                    # 记录价格历史（仅价格变化时）
                                    history = PriceHistory(
                                        item_id=item.id,
                                        source="buff",
                                        price=new_price,
                                    )
                                    self.db.add(history)
                                
                                # 检查监控规则（价格即使没变化也要检查，可能有其他触发条件）
                                await self.check_monitors(item)
                        
                        except Exception as e:
                            logger.error(f"获取 {item.name} 价格失败: {e}")
                    
                    await self.db.commit()
                    
                finally:
                    # 释放锁
                    await lock.release()
                
            except Exception as e:
                logger.error(f"价格轮询错误: {e}")
            
            # 等待下一次轮询
            await asyncio.sleep(settings.PRICE_UPDATE_INTERVAL_HIGH)
    
    async def check_arbitrage(self):
        """检查搬砖机会"""
        while self.running:
            try:
                # 获取所有饰品
                result = await self.db.execute(
                    select(Item).where(
                        Item.current_price > 0,
                        Item.steam_lowest_price > 0
                    )
                )
                items = result.scalars().all()
                
                arbitrage_found = []
                
                for item in items:
                    # 计算搬砖利润
                    steam_sell = item.steam_lowest_price * 0.85
                    profit = steam_sell - item.current_price
                    
                    if profit >= settings.MIN_PROFIT:
                        arbitrage_found.append({
                            "item_id": item.id,
                            "name": item.name,
                            "buff_price": item.current_price,
                            "steam_price": item.steam_lowest_price,
                            "profit": profit,
                        })
                
                if arbitrage_found:
                    # 触发告警
                    for callback in self.alert_callbacks:
                        try:
                            callback(arbitrage_found)
                        except Exception as e:
                            logger.error(f"告警回调错误: {e}")
                
            except Exception as e:
                logger.error(f"套利检查错误: {e}")
            
            # 每分钟检查一次
            await asyncio.sleep(60)
    
    async def check_monitors(self, item: Item):
        """检查监控规则"""
        # 查询所有启用的监控任务
        result = await self.db.execute(
            select(MonitorTask).where(
                MonitorTask.enabled == True,
                MonitorTask.item_id == item.id
            )
        )
        tasks = result.scalars().all()
        
        for task in tasks:
            triggered = False
            message = ""
            
            if task.condition_type == "price_below":
                if item.current_price <= float(task.threshold):
                    triggered = True
                    message = f"{item.name} 价格低于 {task.threshold}，当前价格: {item.current_price}"
            
            elif task.condition_type == "price_above":
                if item.current_price >= float(task.threshold):
                    triggered = True
                    message = f"{item.name} 价格高于 {task.threshold}，当前价格: {item.current_price}"
            
            elif task.condition_type == "arbitrage":
                if item.current_price > 0 and item.steam_lowest_price > 0:
                    profit = item.steam_lowest_price * 0.85 - item.current_price
                    if profit >= float(task.threshold):
                        triggered = True
                        message = f"{item.name} 发现搬砖机会，利润: {profit}"
            
            if triggered:
                # 更新任务统计
                task.trigger_count += 1
                task.last_triggered = datetime.utcnow()
                
                # 记录日志
                log = MonitorLog(
                    task_id=task.id,
                    trigger_type="triggered",
                    message=message,
                    price_data=f'{{"price": {item.current_price}}}',
                )
                self.db.add(log)
                
                # 执行动作
                if task.action == "auto_buy":
                    # 执行自动买入
                    try:
                        from app.services.trading_service import TradingEngine
                        
                        trading_engine = TradingEngine(self.db)
                        
                        # 从任务配置中获取最大买入价格
                        max_price = float(task.threshold)
                        
                        # 执行买入（传递 user_id）
                        buy_result = await trading_engine.execute_buy(
                            item_id=item.id,
                            max_price=max_price,
                            user_id=task.user_id
                        )
                        
                        if buy_result.get("success"):
                            log.message += f" | 自动买入成功: {buy_result.get('order_id')}"
                        else:
                            log.message += f" | 自动买入失败: {buy_result.get('message')}"
                    except Exception as e:
                        log.message += f" | 自动买入异常: {str(e)}"
                
                await self.db.commit()
    
    async def create_monitor_task(
        self,
        name: str,
        item_id: int,
        condition_type: str,
        threshold: float,
        action: Optional[str] = None,
        user_id: int = None
    ) -> MonitorTask:
        """创建监控任务"""
        if user_id is None:
            raise ValueError("create_monitor_task 必须提供 user_id 参数")
        
        task = MonitorTask(
            name=name,
            item_id=item_id,
            condition_type=condition_type,
            threshold=threshold,
            action=action,
            user_id=user_id,
            enabled=True,
            status="idle",
        )
        
        self.db.add(task)
        await self.db.commit()
        await self.db.refresh(task)
        
        return task


# 全局监控实例（按节点区分）
_monitors: Dict[str, 'PriceMonitor'] = {}


def get_price_monitor(db: AsyncSession, node_id: Optional[str] = None) -> PriceMonitor:
    """获取价格监控实例（支持多节点）"""
    node_id = node_id or f"node-{id(db)}"
    
    if node_id not in _monitors:
        _monitors[node_id] = PriceMonitor(db, node_id)
    
    return _monitors[node_id]


async def cleanup_monitors():
    """清理监控实例"""
    global _monitors
    _monitors.clear()
    # Redis 连接由 redis_manager 统一管理，不需要在这里关闭
