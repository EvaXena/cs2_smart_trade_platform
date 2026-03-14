# -*- coding: utf-8 -*-
"""
网格交易策略服务

在价格区间内设置多个买卖点位，当价格下跌时分批买入，当价格上涨时分批卖出。
"""
import asyncio
import logging
from typing import Optional, Dict, List, Any, Tuple
from datetime import datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.models.grid_strategy import GridStrategy, GridTrade
from app.models.item import Item
from app.models.order import Order
from app.services.trading_service import TradingEngine
from app.services.cache import cache_manager
from app.services.webhook_service import webhook_manager, WebhookEventType
from app.core.config import settings
from app.core.response import ServiceResponse, success_response, error_response

logger = logging.getLogger(__name__)

# 缓存前缀
GRID_CACHE_PREFIX = "grid_strategy:"
GRID_STATE_PREFIX = "grid_state:"


class GridTradingStrategy:
    """网格交易策略服务类"""
    
    # 类级别的活跃策略字典
    _active_strategies: Dict[int, 'GridTradingStrategy'] = {}
    _locks: Dict[int, asyncio.Lock] = {}
    _locks_lock = asyncio.Lock()
    
    def __init__(self, db: AsyncSession, strategy_id: int = None):
        self.db = db
        self.strategy_id = strategy_id
        self.strategy: Optional[GridStrategy] = None
        self.grid_prices: List[float] = []
        self.grid_states: List[Dict[str, Any]] = []  # 每格的状态
        self.trading_engine: Optional[TradingEngine] = None
        self._initialized = False
        
    @classmethod
    async def _get_lock(cls, strategy_id: int) -> asyncio.Lock:
        """获取策略锁"""
        async with cls._locks_lock:
            if strategy_id not in cls._locks:
                cls._locks[strategy_id] = asyncio.Lock()
            return cls._locks[strategy_id]
    
    @classmethod
    def get_active_strategy(cls, strategy_id: int) -> Optional['GridTradingStrategy']:
        """获取活跃策略实例"""
        return cls._active_strategies.get(strategy_id)
    
    @classmethod
    def register_active_strategy(cls, strategy_id: int, instance: 'GridTradingStrategy') -> None:
        """注册活跃策略"""
        cls._active_strategies[strategy_id] = instance
        logger.info(f"注册网格策略: {strategy_id}")
    
    @classmethod
    def unregister_active_strategy(cls, strategy_id: int) -> None:
        """注销活跃策略"""
        if strategy_id in cls._active_strategies:
            del cls._active_strategies[strategy_id]
            logger.info(f"注销网格策略: {strategy_id}")
    
    async def load_strategy(self, strategy_id: int) -> bool:
        """从数据库加载策略配置"""
        result = await self.db.execute(
            select(GridStrategy).where(GridStrategy.id == strategy_id)
        )
        self.strategy = result.scalar_one_or_none()
        
        if not self.strategy:
            logger.error(f"网格策略不存在: {strategy_id}")
            return False
        
        self.strategy_id = strategy_id
        return True
    
    async def initialize(self) -> ServiceResponse:
        """初始化网格策略"""
        if not self.strategy:
            return error_response(message="策略未加载", code="STRATEGY_NOT_LOADED")
        
        if self._initialized:
            return success_response(message="策略已初始化")
        
        try:
            # 初始化网格价格
            self.calculate_grid_prices()
            
            # 初始化网格状态
            await self._initialize_grid_state()
            
            # 创建交易引擎实例
            self.trading_engine = TradingEngine(self.db)
            
            self._initialized = True
            
            # 注册到活跃策略
            GridTradingStrategy.register_active_strategy(self.strategy_id, self)
            
            # 更新策略状态
            self.strategy.status = "running"
            self.strategy.started_at = datetime.utcnow()
            await self.db.commit()
            
            logger.info(
                f"网格策略初始化成功: id={self.strategy_id}, "
                f"price_range=[{self.strategy.price_lower}, {self.strategy.price_upper}], "
                f"grid_count={self.strategy.grid_count}"
            )
            
            return success_response(
                data={
                    "strategy_id": self.strategy_id,
                    "grid_count": self.strategy.grid_count,
                    "grid_prices": self.grid_prices,
                },
                message="网格策略初始化成功"
            )
            
        except Exception as e:
            logger.error(f"初始化网格策略失败: {e}")
            return error_response(message=f"初始化失败: {str(e)}", code="INIT_FAILED")
    
    def calculate_grid_prices(self) -> List[float]:
        """计算每格价格"""
        if not self.strategy:
            return []
        
        price_lower = float(self.strategy.price_lower)
        price_upper = float(self.strategy.price_upper)
        grid_count = self.strategy.grid_count
        
        if grid_count <= 0 or price_upper <= price_lower:
            raise ValueError("网格参数无效")
        
        # 计算每格价格间距
        price_step = (price_upper - price_lower) / (grid_count - 1) if grid_count > 1 else 0
        
        # 生成网格价格（从低到高）
        self.grid_prices = [
            round(price_lower + i * price_step, 2)
            for i in range(grid_count)
        ]
        
        logger.debug(f"计算网格价格: {self.grid_prices}")
        return self.grid_prices
    
    async def _initialize_grid_state(self) -> None:
        """初始化网格状态"""
        self.grid_states = []
        
        for i, price in enumerate(self.grid_prices):
            # 如果有保存的状态，从保存的状态恢复
            if self.strategy.grid_state and str(i) in self.strategy.grid_state:
                state = self.strategy.grid_state[str(i)]
            else:
                state = {
                    "index": i,
                    "price": price,
                    "filled": False,  # 是否已买入
                    "sold": False,    # 是否已卖出
                    "buy_order_id": None,
                    "sell_order_id": None,
                    "buy_price": None,
                    "sell_price": None,
                    "profit": 0.0,
                }
            self.grid_states.append(state)
        
        # 保存状态到数据库
        await self._save_grid_state()
    
    async def _save_grid_state(self) -> None:
        """保存网格状态到数据库"""
        if not self.strategy:
            return
        
        state_dict = {}
        for state in self.grid_states:
            state_dict[str(state["index"])] = state
        
        self.strategy.grid_state = state_dict
        self.strategy.updated_at = datetime.utcnow()
        await self.db.commit()
    
    def get_grid_index_by_price(self, price: float) -> int:
        """根据价格获取对应的网格索引"""
        if not self.grid_prices:
            return -1
        
        # 找到最接近价格的那个网格
        closest_index = 0
        min_diff = abs(price - self.grid_prices[0])
        
        for i, grid_price in enumerate(self.grid_prices):
            diff = abs(price - grid_price)
            if diff < min_diff:
                min_diff = diff
                closest_index = i
        
        return closest_index
    
    async def on_price_update(self, current_price: float) -> Dict[str, Any]:
        """价格更新回调 - 触发交易逻辑
        
        当价格下跌到某个网格时买入，当价格上涨到某个网格时卖出
        """
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
        actions = []
        
        # 更新最后价格
        self.strategy.last_price = current_price
        
        # 检查是否触发止损
        if self.stop_loss_triggered(current_price):
            await self._trigger_stop_loss(current_price)
            actions.append({"action": "stop_loss", "price": current_price})
            return {"actions": actions}
        
        # 遍历所有网格，检查是否触发交易
        for i, state in enumerate(self.grid_states):
            if state["filled"] and not state["sold"]:
                # 已买入，检查是否触发卖出
                grid_sell_price = self.grid_prices[i] * (1 + self.strategy.profit_percentage / 100)
                if current_price >= grid_sell_price:
                    result = await self._execute_sell(i, current_price)
                    actions.append(result)
                    
            elif not state["filled"]:
                # 未买入，检查是否触发买入
                grid_buy_price = self.grid_prices[i] * (1 - 0.5 / 100)  # 略低于网格价格买入
                if current_price <= grid_buy_price:
                    result = await self._execute_buy(i, current_price)
                    actions.append(result)
        
        # 保存状态
        await self._save_grid_state()
        
        return {"actions": actions, "current_price": current_price}
    
    async def _execute_buy(self, grid_index: int, current_price: float) -> Dict[str, Any]:
        """执行买入"""
        if not self.trading_engine:
            return {"action": "buy_failed", "reason": "trading_engine_not_ready"}
        
        state = self.grid_states[grid_index]
        
        if state["filled"]:
            return {"action": "skipped", "reason": "already_filled"}
        
        try:
            # 调用交易引擎买入
            result = await self.trading_engine.execute_buy(
                item_id=self.strategy.item_id,
                max_price=current_price * 1.01,  # 允许1%溢价
                quantity=self.strategy.quantity_per_grid,
                user_id=self.strategy.user_id,
            )
            
            if result.success:
                # 更新网格状态
                state["filled"] = True
                state["buy_price"] = current_price
                state["buy_order_id"] = result.data.get("order_id")
                
                # 创建交易记录
                trade = GridTrade(
                    strategy_id=self.strategy_id,
                    side="buy",
                    price=current_price,
                    quantity=self.strategy.quantity_per_grid,
                    grid_index=grid_index,
                    status="completed",
                )
                self.db.add(trade)
                
                # 更新统计
                self.strategy.total_trades += 1
                self.strategy.completed_grids += 1
                
                if self.strategy.entry_price is None:
                    self.strategy.entry_price = current_price
                
                await self.db.commit()
                
                # 发送Webhook通知
                await self._send_webhook(
                    WebhookEventType.ORDER_CREATED,
                    {"side": "buy", "grid_index": grid_index, "price": current_price}
                )
                
                logger.info(
                    f"网格买入执行: strategy={self.strategy_id}, "
                    f"grid={grid_index}, price={current_price}"
                )
                
                return {
                    "action": "buy",
                    "grid_index": grid_index,
                    "price": current_price,
                    "order_id": result.data.get("order_id"),
                }
            else:
                logger.warning(f"买入失败: {result.message}")
                return {"action": "buy_failed", "reason": result.message}
                
        except Exception as e:
            logger.error(f"买入执行异常: {e}")
            return {"action": "buy_failed", "reason": str(e)}
    
    async def _execute_sell(self, grid_index: int, current_price: float) -> Dict[str, Any]:
        """执行卖出"""
        if not self.trading_engine:
            return {"action": "sell_failed", "reason": "trading_engine_not_ready"}
        
        state = self.grid_states[grid_index]
        
        if not state["filled"] or state["sold"]:
            return {"action": "skipped", "reason": "not_ready_to_sell"}
        
        try:
            # 计算卖出价格（网格价格 + 利润）
            sell_price = self.grid_prices[grid_index] * (1 + self.strategy.profit_percentage / 100)
            
            # 调用交易引擎卖出
            result = await self.trading_engine.execute_sell(
                item_id=self.strategy.item_id,
                min_price=sell_price,
                quantity=self.strategy.quantity_per_grid,
                user_id=self.strategy.user_id,
            )
            
            if result.success:
                # 计算利润
                profit = (sell_price - state["buy_price"]) * self.strategy.quantity_per_grid
                
                # 更新网格状态
                state["sold"] = True
                state["sell_price"] = sell_price
                state["sell_order_id"] = result.data.get("order_id")
                state["profit"] = profit
                
                # 创建交易记录
                trade = GridTrade(
                    strategy_id=self.strategy_id,
                    side="sell",
                    price=sell_price,
                    quantity=self.strategy.quantity_per_grid,
                    grid_index=grid_index,
                    status="completed",
                    profit=profit,
                    completed_at=datetime.utcnow(),
                )
                self.db.add(trade)
                
                # 更新统计
                self.strategy.total_trades += 1
                self.strategy.total_profit += profit
                
                await self.db.commit()
                
                # 发送Webhook通知
                await self._send_webhook(
                    WebhookEventType.ORDER_COMPLETED,
                    {"side": "sell", "grid_index": grid_index, "price": sell_price, "profit": profit}
                )
                
                logger.info(
                    f"网格卖出执行: strategy={self.strategy_id}, "
                    f"grid={grid_index}, price={sell_price}, profit={profit}"
                )
                
                return {
                    "action": "sell",
                    "grid_index": grid_index,
                    "price": sell_price,
                    "profit": profit,
                    "order_id": result.data.get("order_id"),
                }
            else:
                logger.warning(f"卖出失败: {result.message}")
                return {"action": "sell_failed", "reason": result.message}
                
        except Exception as e:
            logger.error(f"卖出执行异常: {e}")
            return {"action": "sell_failed", "reason": str(e)}
    
    def calculate_profit(self) -> float:
        """计算当前收益"""
        if not self.strategy:
            return 0.0
        
        total_profit = 0.0
        
        for state in self.grid_states:
            if state["sold"]:
                total_profit += state.get("profit", 0.0)
        
        return total_profit
    
    def stop_loss_triggered(self, current_price: float) -> bool:
        """检查是否触发止损"""
        if not self.strategy or self.strategy.entry_price is None:
            return False
        
        loss_percentage = (self.strategy.entry_price - current_price) / self.strategy.entry_price * 100
        
        return loss_percentage >= self.strategy.stop_loss_percentage
    
    async def _trigger_stop_loss(self, current_price: float) -> None:
        """触发止损"""
        logger.warning(
            f"网格策略触发止损: strategy={self.strategy_id}, "
            f"entry_price={self.strategy.entry_price}, "
            f"current_price={current_price}, "
            f"loss_percentage={self.strategy.stop_loss_percentage}%"
        )
        
        # 停止策略
        await self.stop()
        
        # 更新策略状态
        self.strategy.status = "stopped"
        self.strategy.is_active = False
        self.strategy.stopped_at = datetime.utcnow()
        
        # 计算已实现亏损
        total_loss = self.calculate_profit()  # 负数表示亏损
        
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
        GridTradingStrategy.unregister_active_strategy(self.strategy_id)
        
        logger.info(f"网格策略已暂停: {self.strategy_id}")
        
        return success_response(message="策略已暂停")
    
    async def resume(self) -> ServiceResponse:
        """恢复策略"""
        if not self.strategy:
            return error_response(message="策略未加载", code="STRATEGY_NOT_LOADED")
        
        self.strategy.status = "running"
        await self.db.commit()
        
        # 重新注册到活跃策略
        GridTradingStrategy.register_active_strategy(self.strategy_id, self)
        
        logger.info(f"网格策略已恢复: {self.strategy_id}")
        
        return success_response(message="策略已恢复")
    
    async def stop(self) -> ServiceResponse:
        """停止策略"""
        if not self.strategy:
            return error_response(message="策略未加载", code="STRATEGY_NOT_LOADED")
        
        # 从活跃策略中移除
        GridTradingStrategy.unregister_active_strategy(self.strategy_id)
        
        # 更新状态
        self.strategy.status = "stopped"
        self.strategy.is_active = False
        self.strategy.stopped_at = datetime.utcnow()
        
        await self.db.commit()
        
        # 清理缓存
        await self._clear_cache()
        
        logger.info(f"网格策略已停止: {self.strategy_id}")
        
        return success_response(
            data={
                "total_trades": self.strategy.total_trades,
                "total_profit": float(self.strategy.total_profit),
                "completed_grids": self.strategy.completed_grids,
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
            "price_lower": self.strategy.price_lower,
            "price_upper": self.strategy.price_upper,
            "grid_count": self.strategy.grid_count,
            "quantity_per_grid": self.strategy.quantity_per_grid,
            "profit_percentage": self.strategy.profit_percentage,
            "stop_loss_percentage": self.strategy.stop_loss_percentage,
            "last_price": self.strategy.last_price,
            "entry_price": self.strategy.entry_price,
            "total_trades": self.strategy.total_trades,
            "total_profit": float(self.strategy.total_profit),
            "completed_grids": self.strategy.completed_grids,
            "grid_prices": self.grid_prices,
            "grid_states": self.grid_states,
            "created_at": self.strategy.created_at.isoformat() if self.strategy.created_at else None,
            "started_at": self.strategy.started_at.isoformat() if self.strategy.started_at else None,
            "stopped_at": self.strategy.stopped_at.isoformat() if self.strategy.stopped_at else None,
        }
    
    async def _send_webhook(self, event_type: WebhookEventType, data: Dict[str, Any]) -> None:
        """发送Webhook通知"""
        try:
            asyncio.create_task(
                webhook_manager.send_webhook(
                    event_type=event_type,
                    data=data,
                    user_id=self.strategy.user_id,
                    order_id=f"GRID-{self.strategy_id}"
                )
            )
        except Exception as e:
            logger.warning(f"发送Webhook失败: {e}")
    
    async def _clear_cache(self) -> None:
        """清理缓存"""
        try:
            cache_manager.delete(f"{GRID_CACHE_PREFIX}{self.strategy_id}")
            cache_manager.delete(f"{GRID_STATE_PREFIX}{self.strategy_id}")
        except Exception as e:
            logger.warning(f"清理缓存失败: {e}")


# ============ 策略管理函数 ============

async def create_grid_strategy(
    db: AsyncSession,
    user_id: int,
    item_id: int,
    name: str,
    price_lower: float,
    price_upper: float,
    grid_count: int = 10,
    quantity_per_grid: int = 1,
    profit_percentage: float = 1.0,
    stop_loss_percentage: float = 5.0,
) -> GridStrategy:
    """创建网格交易策略"""
    
    # 验证item是否存在
    result = await db.execute(select(Item).where(Item.id == item_id))
    item = result.scalar_one_or_none()
    
    if not item:
        raise ValueError(f"饰品不存在: {item_id}")
    
    # 创建策略
    strategy = GridStrategy(
        user_id=user_id,
        item_id=item_id,
        name=name,
        price_lower=price_lower,
        price_upper=price_upper,
        grid_count=grid_count,
        quantity_per_grid=quantity_per_grid,
        profit_percentage=profit_percentage,
        stop_loss_percentage=stop_loss_percentage,
        status="pending",
        is_active=True,
    )
    
    db.add(strategy)
    await db.commit()
    await db.refresh(strategy)
    
    logger.info(
        f"创建网格策略: id={strategy.id}, name={name}, "
        f"item_id={item_id}, price_range=[{price_lower}, {price_upper}], "
        f"grid_count={grid_count}"
    )
    
    return strategy


async def get_grid_strategy(db: AsyncSession, strategy_id: int) -> Optional[GridStrategy]:
    """获取网格策略"""
    result = await db.execute(
        select(GridStrategy).where(GridStrategy.id == strategy_id)
    )
    return result.scalar_one_or_none()


async def get_user_grid_strategies(
    db: AsyncSession,
    user_id: int,
    status: Optional[str] = None,
    is_active: Optional[bool] = None,
) -> List[GridStrategy]:
    """获取用户的所有网格策略"""
    filters = [GridStrategy.user_id == user_id]
    
    if status:
        filters.append(GridStrategy.status == status)
    if is_active is not None:
        filters.append(GridStrategy.is_active == is_active)
    
    result = await db.execute(
        select(GridStrategy).where(and_(*filters)).order_by(GridStrategy.created_at.desc())
    )
    return result.scalars().all()


async def delete_grid_strategy(db: AsyncSession, strategy_id: int) -> bool:
    """删除网格策略"""
    result = await db.execute(
        select(GridStrategy).where(GridStrategy.id == strategy_id)
    )
    strategy = result.scalar_one_or_none()
    
    if not strategy:
        return False
    
    # 如果策略正在运行，先停止
    if strategy.status == "running":
        strategy_instance = GridTradingStrategy(db, strategy_id)
        await strategy_instance.load_strategy(strategy_id)
        await strategy_instance.stop()
    
    await db.delete(strategy)
    await db.commit()
    
    logger.info(f"删除网格策略: {strategy_id}")
    
    return True


async def update_grid_strategy(
    db: AsyncSession,
    strategy_id: int,
    user_id: int,
    name: Optional[str] = None,
    price_lower: Optional[float] = None,
    price_upper: Optional[float] = None,
    grid_count: Optional[int] = None,
    quantity_per_grid: Optional[int] = None,
    profit_percentage: Optional[float] = None,
    stop_loss_percentage: Optional[float] = None,
    is_active: Optional[bool] = None,
) -> Optional[GridStrategy]:
    """更新网格策略"""
    result = await db.execute(
        select(GridStrategy).where(GridStrategy.id == strategy_id)
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
    if price_lower is not None:
        strategy.price_lower = price_lower
    if price_upper is not None:
        strategy.price_upper = price_upper
    if grid_count is not None:
        strategy.grid_count = grid_count
    if quantity_per_grid is not None:
        strategy.quantity_per_grid = quantity_per_grid
    if profit_percentage is not None:
        strategy.profit_percentage = profit_percentage
    if stop_loss_percentage is not None:
        strategy.stop_loss_percentage = stop_loss_percentage
    if is_active is not None:
        strategy.is_active = is_active
    
    strategy.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(strategy)
    
    logger.info(f"更新网格策略: {strategy_id}")
    
    return strategy
