# -*- coding: utf-8 -*-
"""
均值回归策略服务

策略逻辑：
1. 计算价格均值（MA/EMA）
2. 计算当前价格偏离度 = (当前价格 - 均值) / 均值 * 100%
3. 当偏离 > 买入阈值时，买入
4. 当偏离 < 卖出阈值时，卖出
5. 设置止盈止损
"""
import asyncio
import logging
from typing import Optional, Dict, List, Any
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.models.mean_reversion_strategy import MeanReversionStrategy, MeanReversionTrade
from app.models.item import Item
from app.services.trading_service import TradingEngine
from app.services.cache import cache_manager
from app.services.webhook_service import webhook_manager, WebhookEventType
from app.utils.indicators import MA, EMA
from app.core.response import ServiceResponse, success_response, error_response

logger = logging.getLogger(__name__)

# 缓存前缀
MR_CACHE_PREFIX = "mr_strategy:"
PRICE_HISTORY_PREFIX = "mr_price_history:"


class MeanReversionStrategyService:
    """均值回归策略服务类"""
    
    # 类级别的活跃策略字典
    _active_strategies: Dict[int, 'MeanReversionStrategyService'] = {}
    _locks: Dict[int, asyncio.Lock] = {}
    _locks_lock = asyncio.Lock()
    # Webhook 任务管理
    _active_webhook_tasks: Dict[str, asyncio.Task] = {}
    _webhook_tasks_lock = asyncio.Lock()
    
    # 价格历史缓存
    _price_history: Dict[int, List[float]] = {}
    _max_history_length = 200
    
    def __init__(self, db: AsyncSession, strategy_id: int = None):
        self.db = db
        self.strategy_id = strategy_id
        self.strategy: Optional[MeanReversionStrategy] = None
        self.trading_engine: Optional[TradingEngine] = None
        self._initialized = False
        self._position_opened = False  # 是否持有仓位
        
    @classmethod
    async def _get_lock(cls, strategy_id: int) -> asyncio.Lock:
        """获取策略锁"""
        async with cls._locks_lock:
            if strategy_id not in cls._locks:
                cls._locks[strategy_id] = asyncio.Lock()
            return cls._locks[strategy_id]
    
    @classmethod
    def get_active_strategy(cls, strategy_id: int) -> Optional['MeanReversionStrategyService']:
        """获取活跃策略实例"""
        return cls._active_strategies.get(strategy_id)
    
    @classmethod
    def register_active_strategy(cls, strategy_id: int, instance: 'MeanReversionStrategyService') -> None:
        """注册活跃策略"""
        cls._active_strategies[strategy_id] = instance
        logger.info(f"注册均值回归策略: {strategy_id}")
    
    @classmethod
    def unregister_active_strategy(cls, strategy_id: int) -> None:
        """注销活跃策略"""
        if strategy_id in cls._active_strategies:
            del cls._active_strategies[strategy_id]
            logger.info(f"注销均值回归策略: {strategy_id}")
    
    async def load_strategy(self, strategy_id: int) -> bool:
        """从数据库加载策略配置"""
        result = await self.db.execute(
            select(MeanReversionStrategy).where(MeanReversionStrategy.id == strategy_id)
        )
        self.strategy = result.scalar_one_or_none()
        
        if not self.strategy:
            logger.error(f"均值回归策略不存在: {strategy_id}")
            return False
        
        self.strategy_id = strategy_id
        
        # 恢复持仓状态
        if self.strategy.strategy_state:
            self._position_opened = self.strategy.strategy_state.get("position_opened", False)
        
        return True
    
    async def initialize(self) -> ServiceResponse:
        """初始化均值回归策略"""
        if not self.strategy:
            return error_response(message="策略未加载", code="STRATEGY_NOT_LOADED")
        
        if self._initialized:
            return success_response(message="策略已初始化")
        
        try:
            # 创建交易引擎实例
            self.trading_engine = TradingEngine(self.db)
            
            self._initialized = True
            
            # 注册到活跃策略
            MeanReversionStrategyService.register_active_strategy(self.strategy_id, self)
            
            # 更新策略状态
            self.strategy.status = "running"
            self.strategy.started_at = datetime.utcnow()
            await self.db.commit()
            
            logger.info(
                f"均值回归策略初始化成功: id={self.strategy_id}, "
                f"mean_period={self.strategy.mean_period}, "
                f"mean_type={self.strategy.mean_type}"
            )
            
            return success_response(
                data={
                    "strategy_id": self.strategy_id,
                    "mean_period": self.strategy.mean_period,
                    "mean_type": self.strategy.mean_type,
                    "buy_threshold": self.strategy.buy_threshold,
                    "sell_threshold": self.strategy.sell_threshold,
                },
                message="均值回归策略初始化成功"
            )
            
        except Exception as e:
            logger.error(f"初始化均值回归策略失败: {e}")
            return error_response(message=f"初始化失败: {str(e)}", code="INIT_FAILED")
    
    def _add_price_to_history(self, price: float) -> None:
        """添加价格到历史缓存"""
        if self.strategy_id not in self._price_history:
            self._price_history[self.strategy_id] = []
        
        self._price_history[self.strategy_id].append(price)
        
        # 保持历史长度不超过配置
        max_len = max(self.strategy.mean_period * 2, self._max_history_length)
        if len(self._price_history[self.strategy_id]) > max_len:
            self._price_history[self.strategy_id] = self._price_history[self.strategy_id][-max_len:]
    
    def _calculate_mean(self) -> Optional[float]:
        """计算当前均值"""
        if self.strategy_id not in self._price_history:
            return None
        
        prices = self._price_history[self.strategy_id]
        if len(prices) < self.strategy.mean_period:
            return None
        
        # 取最近mean_period个价格
        recent_prices = prices[-self.strategy.mean_period:]
        
        if self.strategy.mean_type == "EMA":
            ema_values = EMA(recent_prices, self.strategy.mean_period)
            return ema_values[-1] if ema_values else None
        else:
            return sum(recent_prices) / len(recent_prices)
    
    def _calculate_deviation(self, current_price: float, mean_price: float) -> float:
        """计算价格偏离度(%)"""
        return (current_price - mean_price) / mean_price * 100
    
    async def on_price_update(self, current_price: float) -> Dict[str, Any]:
        """价格更新回调 - 触发交易逻辑"""
        if not self._initialized or not self.strategy:
            return {"action": "ignored", "reason": "strategy_not_ready"}
        
        if not self.strategy.is_active or self.strategy.status != "running":
            return {"action": "ignored", "reason": "strategy_not_running"}
        
        # 获取策略锁，防止并发执行
        lock = await self._get_lock(self.strategy_id)
        async with lock:
            return await self._process_price_update(current_price)
    
    async def _process_price_update(self, current_price: float) -> Dict[str, Any]:
        """处理价格更新（需要加锁）"""
        
        # 更新最后价格
        self.strategy.last_price = current_price
        
        # 添加到价格历史
        self._add_price_to_history(current_price)
        
        # 计算均值
        mean_price = self._calculate_mean()
        
        if mean_price is None:
            await self.db.commit()
            return {
                "action": "waiting",
                "current_price": current_price,
                "message": f"等待足够数据，需要{self.strategy.mean_period}个价格点"
            }
        
        # 更新数据库中的均值
        self.strategy.mean_price = mean_price
        
        # 计算偏离度
        deviation = self._calculate_deviation(current_price, mean_price)
        
        # 检查是否触发止损
        if self._position_opened and self.strategy.entry_price:
            if self.stop_loss_triggered(current_price):
                await self._trigger_stop_loss(current_price)
                return {
                    "action": "stop_loss",
                    "current_price": current_price,
                    "mean_price": mean_price,
                    "deviation": deviation,
                    "message": "触发止损"
                }
            
            # 检查是否触发止盈
            if self.profit_target_triggered(current_price):
                result = await self._execute_sell(current_price, deviation)
                result["mean_price"] = mean_price
                return result
        
        # 交易逻辑
        if not self._position_opened:
            # 没有仓位，检查是否买入
            if deviation <= self.strategy.buy_threshold:
                result = await self._execute_buy(current_price, deviation)
                result["mean_price"] = mean_price
                result["deviation"] = deviation
                return result
        else:
            # 有仓位，检查是否卖出
            if deviation >= self.strategy.sell_threshold:
                result = await self._execute_sell(current_price, deviation)
                result["mean_price"] = mean_price
                result["deviation"] = deviation
                return result
        
        await self.db.commit()
        
        return {
            "action": "hold",
            "current_price": current_price,
            "mean_price": mean_price,
            "deviation": deviation,
            "position_opened": self._position_opened,
            "message": f"偏离度 {deviation:.2f}%，等待信号"
        }
    
    async def _execute_buy(self, current_price: float, deviation: float) -> Dict[str, Any]:
        """执行买入"""
        if not self.trading_engine:
            return {"action": "buy_failed", "reason": "trading_engine_not_ready"}
        
        if self._position_opened:
            return {"action": "skipped", "reason": "already_has_position"}
        
        try:
            # 调用交易引擎买入
            result = await self.trading_engine.execute_buy(
                item_id=self.strategy.item_id,
                max_price=current_price * 1.01,  # 允许1%溢价
                quantity=self.strategy.position_size,
                user_id=self.strategy.user_id,
            )
            
            if result.success:
                # 更新持仓状态
                self._position_opened = True
                self.strategy.entry_price = current_price
                
                # 创建交易记录
                trade = MeanReversionTrade(
                    strategy_id=self.strategy_id,
                    side="buy",
                    price=current_price,
                    quantity=self.strategy.position_size,
                    deviation=deviation,
                    status="completed",
                )
                self.db.add(trade)
                
                # 更新统计
                self.strategy.total_trades += 1
                
                # 保存状态
                await self._save_strategy_state()
                await self.db.commit()
                
                # 发送Webhook通知
                await self._send_webhook(
                    WebhookEventType.ORDER_CREATED,
                    {"side": "buy", "price": current_price, "deviation": deviation}
                )
                
                logger.info(
                    f"均值回归买入执行: strategy={self.strategy_id}, "
                    f"price={current_price}, deviation={deviation:.2f}%"
                )
                
                return {
                    "action": "buy",
                    "price": current_price,
                    "deviation": deviation,
                    "order_id": result.data.get("order_id"),
                    "message": f"买入成功，价格偏离均值 {deviation:.2f}%"
                }
            else:
                logger.warning(f"买入失败: {result.message}")
                return {"action": "buy_failed", "reason": result.message}
                
        except Exception as e:
            logger.error(f"买入执行异常: {e}")
            return {"action": "buy_failed", "reason": str(e)}
    
    async def _execute_sell(self, current_price: float, deviation: float) -> Dict[str, Any]:
        """执行卖出"""
        if not self.trading_engine:
            return {"action": "sell_failed", "reason": "trading_engine_not_ready"}
        
        if not self._position_opened or not self.strategy.entry_price:
            return {"action": "skipped", "reason": "no_position"}
        
        try:
            # 计算卖出价格（目标价格）
            target_price = self.strategy.mean_price * (1 + self.strategy.sell_threshold / 100)
            
            # 调用交易引擎卖出
            result = await self.trading_engine.execute_sell(
                item_id=self.strategy.item_id,
                min_price=target_price,
                quantity=self.strategy.position_size,
                user_id=self.strategy.user_id,
            )
            
            if result.success:
                # 计算利润
                profit = (current_price - self.strategy.entry_price) * self.strategy.position_size
                
                # 更新持仓状态
                self._position_opened = False
                
                # 创建交易记录
                trade = MeanReversionTrade(
                    strategy_id=self.strategy_id,
                    side="sell",
                    price=current_price,
                    quantity=self.strategy.position_size,
                    deviation=deviation,
                    status="completed",
                    profit=profit,
                    completed_at=datetime.utcnow(),
                )
                self.db.add(trade)
                
                # 更新统计
                self.strategy.total_trades += 1
                self.strategy.total_profit += profit
                
                if profit > 0:
                    self.strategy.winning_trades += 1
                else:
                    self.strategy.losing_trades += 1
                
                # 清除入场价
                entry_price = self.strategy.entry_price
                self.strategy.entry_price = None
                
                # 保存状态
                await self._save_strategy_state()
                await self.db.commit()
                
                # 发送Webhook通知
                await self._send_webhook(
                    WebhookEventType.ORDER_COMPLETED,
                    {"side": "sell", "price": current_price, "profit": profit, "deviation": deviation}
                )
                
                logger.info(
                    f"均值回归卖出执行: strategy={self.strategy_id}, "
                    f"price={current_price}, profit={profit}, deviation={deviation:.2f}%"
                )
                
                return {
                    "action": "sell",
                    "price": current_price,
                    "profit": profit,
                    "deviation": deviation,
                    "order_id": result.data.get("order_id"),
                    "message": f"卖出成功，盈利 {profit:.2f}"
                }
            else:
                logger.warning(f"卖出失败: {result.message}")
                return {"action": "sell_failed", "reason": result.message}
                
        except Exception as e:
            logger.error(f"卖出执行异常: {e}")
            return {"action": "sell_failed", "reason": str(e)}
    
    async def _save_strategy_state(self) -> None:
        """保存策略状态"""
        if not self.strategy:
            return
        
        self.strategy.strategy_state = {
            "position_opened": self._position_opened,
            "entry_price": self.strategy.entry_price,
        }
        self.strategy.updated_at = datetime.utcnow()
        await self.db.commit()
    
    def stop_loss_triggered(self, current_price: float) -> bool:
        """检查是否触发止损"""
        if not self.strategy or self.strategy.entry_price is None:
            return False
        
        loss_percentage = (self.strategy.entry_price - current_price) / self.strategy.entry_price * 100
        
        return loss_percentage >= self.strategy.stop_loss_percentage
    
    def profit_target_triggered(self, current_price: float) -> bool:
        """检查是否触发止盈"""
        if not self.strategy or self.strategy.entry_price is None:
            return False
        
        profit_percentage = (current_price - self.strategy.entry_price) / self.strategy.entry_price * 100
        
        return profit_percentage >= self.strategy.profit_percentage
    
    async def _trigger_stop_loss(self, current_price: float) -> None:
        """触发止损"""
        logger.warning(
            f"均值回归策略触发止损: strategy={self.strategy_id}, "
            f"entry_price={self.strategy.entry_price}, "
            f"current_price={current_price}, "
            f"loss_percentage={self.strategy.stop_loss_percentage}%"
        )
        
        # 执行卖出
        deviation = 0
        if self.strategy.mean_price:
            deviation = self._calculate_deviation(current_price, self.strategy.mean_price)
        
        await self._execute_sell(current_price, deviation)
        
        # 停止策略
        await self.stop()
        
        # 更新策略状态
        self.strategy.status = "stopped"
        self.strategy.is_active = False
        self.strategy.stopped_at = datetime.utcnow()
        
        await self.db.commit()
        
        # 发送止损通知
        await self._send_webhook(
            WebhookEventType.TRADE_FAILED,
            {"reason": "stop_loss", "entry_price": self.strategy.entry_price, "current_price": current_price}
        )
    
    async def pause(self) -> ServiceResponse:
        """暂停策略"""
        if not self.strategy:
            return error_response(message="策略未加载", code="STRATEGY_NOT_LOADED")
        
        self.strategy.status = "paused"
        await self.db.commit()
        
        # 从活跃策略中移除
        MeanReversionStrategyService.unregister_active_strategy(self.strategy_id)
        
        logger.info(f"均值回归策略已暂停: {self.strategy_id}")
        
        return success_response(message="策略已暂停")
    
    async def resume(self) -> ServiceResponse:
        """恢复策略"""
        if not self.strategy:
            return error_response(message="策略未加载", code="STRATEGY_NOT_LOADED")
        
        self.strategy.status = "running"
        await self.db.commit()
        
        # 重新注册到活跃策略
        MeanReversionStrategyService.register_active_strategy(self.strategy_id, self)
        
        logger.info(f"均值回归策略已恢复: {self.strategy_id}")
        
        return success_response(message="策略已恢复")
    
    async def stop(self) -> ServiceResponse:
        """停止策略"""
        if not self.strategy:
            return error_response(message="策略未加载", code="STRATEGY_NOT_LOADED")
        
        # 从活跃策略中移除
        MeanReversionStrategyService.unregister_active_strategy(self.strategy_id)
        
        # 更新状态
        self.strategy.status = "stopped"
        self.strategy.is_active = False
        self.strategy.stopped_at = datetime.utcnow()
        
        await self.db.commit()
        
        # 清理缓存
        await self._clear_cache()
        
        logger.info(f"均值回归策略已停止: {self.strategy_id}")
        
        return success_response(
            data={
                "total_trades": self.strategy.total_trades,
                "total_profit": float(self.strategy.total_profit),
                "winning_trades": self.strategy.winning_trades,
                "losing_trades": self.strategy.losing_trades,
            },
            message="策略已停止"
        )
    
    async def get_status(self) -> Dict[str, Any]:
        """获取策略状态"""
        if not self.strategy:
            return {}
        
        return {
            "id": self.strategy.id,
            "name": self.strategy.name,
            "item_id": self.strategy.item_id,
            "status": self.strategy.status,
            "is_active": self.strategy.is_active,
            "mean_period": self.strategy.mean_period,
            "mean_type": self.strategy.mean_type,
            "buy_threshold": self.strategy.buy_threshold,
            "sell_threshold": self.strategy.sell_threshold,
            "profit_percentage": self.strategy.profit_percentage,
            "stop_loss_percentage": self.strategy.stop_loss_percentage,
            "position_size": self.strategy.position_size,
            "last_price": self.strategy.last_price,
            "entry_price": self.strategy.entry_price,
            "mean_price": self.strategy.mean_price,
            "position_opened": self._position_opened,
            "total_trades": self.strategy.total_trades,
            "total_profit": float(self.strategy.total_profit),
            "winning_trades": self.strategy.winning_trades,
            "losing_trades": self.strategy.losing_trades,
            "created_at": self.strategy.created_at.isoformat() if self.strategy.created_at else None,
            "started_at": self.strategy.started_at.isoformat() if self.strategy.started_at else None,
            "stopped_at": self.strategy.stopped_at.isoformat() if self.strategy.stopped_at else None,
        }
    
    async def _send_webhook(self, event_type: WebhookEventType, data: Dict[str, Any]) -> None:
        """发送Webhook通知"""
        try:
            task = asyncio.create_task(
                webhook_manager.send_webhook(
                    event_type=event_type,
                    data=data,
                    user_id=self.strategy.user_id,
                    order_id=f"MR-{self.strategy_id}"
                )
            )
            # 保存任务引用以便管理
            task_key = f"mr_webhook_{self.strategy_id}_{event_type.value}"
            async with self._webhook_tasks_lock:
                self._active_webhook_tasks[task_key] = task
            # 任务完成后自动清理
            task.add_done_callback(
                lambda t: asyncio.create_task(self._remove_webhook_task(task_key))
            )
        except Exception as e:
            logger.warning(f"发送Webhook失败: {e}")
    
    async def _remove_webhook_task(self, task_key: str) -> None:
        """移除已完成的Webhook任务引用"""
        async with self._webhook_tasks_lock:
            if task_key in self._active_webhook_tasks:
                del self._active_webhook_tasks[task_key]
    
    async def _clear_cache(self) -> None:
        """清理缓存"""
        try:
            cache_manager.delete(f"{MR_CACHE_PREFIX}{self.strategy_id}")
            if self.strategy_id in self._price_history:
                del self._price_history[self.strategy_id]
        except Exception as e:
            logger.warning(f"清理缓存失败: {e}")


# ============ 策略管理函数 ============

async def create_mean_reversion_strategy(
    db: AsyncSession,
    user_id: int,
    item_id: int,
    name: str,
    mean_period: int = 20,
    mean_type: str = "EMA",
    buy_threshold: float = -2.0,
    sell_threshold: float = 2.0,
    profit_percentage: float = 3.0,
    stop_loss_percentage: float = 5.0,
    position_size: int = 1,
) -> MeanReversionStrategy:
    """创建均值回归策略"""
    
    # 验证item是否存在
    result = await db.execute(select(Item).where(Item.id == item_id))
    item = result.scalar_one_or_none()
    
    if not item:
        raise ValueError(f"饰品不存在: {item_id}")
    
    # 验证均值类型
    if mean_type not in ["MA", "EMA"]:
        raise ValueError("均值类型必须是 MA 或 EMA")
    
    # 创建策略
    strategy = MeanReversionStrategy(
        user_id=user_id,
        item_id=item_id,
        name=name,
        mean_period=mean_period,
        mean_type=mean_type,
        buy_threshold=buy_threshold,
        sell_threshold=sell_threshold,
        profit_percentage=profit_percentage,
        stop_loss_percentage=stop_loss_percentage,
        position_size=position_size,
        status="pending",
        is_active=True,
    )
    
    db.add(strategy)
    await db.commit()
    await db.refresh(strategy)
    
    logger.info(
        f"创建均值回归策略: id={strategy.id}, name={name}, "
        f"item_id={item_id}, mean_period={mean_period}, mean_type={mean_type}"
    )
    
    return strategy


async def get_mean_reversion_strategy(db: AsyncSession, strategy_id: int) -> Optional[MeanReversionStrategy]:
    """获取均值回归策略"""
    result = await db.execute(
        select(MeanReversionStrategy).where(MeanReversionStrategy.id == strategy_id)
    )
    return result.scalar_one_or_none()


async def get_user_mean_reversion_strategies(
    db: AsyncSession,
    user_id: int,
    status: Optional[str] = None,
    is_active: Optional[bool] = None,
) -> List[MeanReversionStrategy]:
    """获取用户的所有均值回归策略"""
    filters = [MeanReversionStrategy.user_id == user_id]
    
    if status:
        filters.append(MeanReversionStrategy.status == status)
    if is_active is not None:
        filters.append(MeanReversionStrategy.is_active == is_active)
    
    result = await db.execute(
        select(MeanReversionStrategy).where(and_(*filters)).order_by(MeanReversionStrategy.created_at.desc())
    )
    return result.scalars().all()


async def delete_mean_reversion_strategy(db: AsyncSession, strategy_id: int) -> bool:
    """删除均值回归策略"""
    result = await db.execute(
        select(MeanReversionStrategy).where(MeanReversionStrategy.id == strategy_id)
    )
    strategy = result.scalar_one_or_none()
    
    if not strategy:
        return False
    
    # 如果策略正在运行，先停止
    if strategy.status == "running":
        strategy_instance = MeanReversionStrategyService(db, strategy_id)
        await strategy_instance.load_strategy(strategy_id)
        await strategy_instance.stop()
    
    await db.delete(strategy)
    await db.commit()
    
    logger.info(f"删除均值回归策略: {strategy_id}")
    
    return True


async def update_mean_reversion_strategy(
    db: AsyncSession,
    strategy_id: int,
    user_id: int,
    name: Optional[str] = None,
    mean_period: Optional[int] = None,
    mean_type: Optional[str] = None,
    buy_threshold: Optional[float] = None,
    sell_threshold: Optional[float] = None,
    profit_percentage: Optional[float] = None,
    stop_loss_percentage: Optional[float] = None,
    position_size: Optional[int] = None,
    is_active: Optional[bool] = None,
) -> Optional[MeanReversionStrategy]:
    """更新均值回归策略"""
    result = await db.execute(
        select(MeanReversionStrategy).where(MeanReversionStrategy.id == strategy_id)
    )
    strategy = result.scalar_one_or_none()
    
    if not strategy:
        return None
    
    # 验证所有权
    if strategy.user_id != user_id:
        raise ValueError("无权更新此策略")
    
    # 只能更新pending状态的策略
    if strategy.status != "pending":
        raise ValueError("只能更新pending状态的策略")
    
    # 更新字段
    if name is not None:
        strategy.name = name
    if mean_period is not None:
        strategy.mean_period = mean_period
    if mean_type is not None:
        if mean_type not in ["MA", "EMA"]:
            raise ValueError("均值类型必须是 MA 或 EMA")
        strategy.mean_type = mean_type
    if buy_threshold is not None:
        strategy.buy_threshold = buy_threshold
    if sell_threshold is not None:
        strategy.sell_threshold = sell_threshold
    if profit_percentage is not None:
        strategy.profit_percentage = profit_percentage
    if stop_loss_percentage is not None:
        strategy.stop_loss_percentage = stop_loss_percentage
    if position_size is not None:
        strategy.position_size = position_size
    if is_active is not None:
        strategy.is_active = is_active
    
    strategy.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(strategy)
    
    logger.info(f"更新均值回归策略: {strategy_id}")
    
    return strategy
