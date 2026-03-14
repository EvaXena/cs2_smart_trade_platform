# -*- coding: utf-8 -*-
"""
风险管理器 - 独立风险控制模块

职责：
- 仓位大小检查
- 止损/止盈检查
- 风险规则配置
- 风险事件记录
- 与交易服务集成
"""
import asyncio
import json
import logging
from typing import Optional, Dict, List, Any, Tuple
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.config import settings
from app.core.redis_manager import get_redis
from app.models.order import Order
from app.models.inventory import Inventory
from app.models.item import Item

logger = logging.getLogger(__name__)



class RiskLevel(Enum):
    """风险等级"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RiskEventType(Enum):
    """风险事件类型"""
    POSITION_SIZE_EXCEEDED = "position_size_exceeded"
    STOP_LOSS_TRIGGERED = "stop_loss_triggered"
    TAKE_PROFIT_TRIGGERED = "take_profit_triggered"
    DAILY_LIMIT_EXCEEDED = "daily_limit_exceeded"
    SINGLE_TRADE_EXCEEDED = "single_trade_exceeded"
    CONCENTRATION_RISK = "concentration_risk"
    SUSPICIOUS_PATTERN = "suspicious_pattern"


@dataclass
class RiskRule:
    """风险规则配置"""
    name: str
    enabled: bool = True
    max_position_size: float = 0  # 最大持仓金额
    max_single_trade: float = 0  # 单笔最大交易金额
    max_daily_loss: float = 0  # 每日最大亏损
    max_daily_trade_amount: float = 0  # 每日最大交易金额
    stop_loss_percent: float = 0  # 止损百分比
    take_profit_percent: float = 0  # 止盈百分比
    max_position_concentration: float = 0.3  # 单品种最大持仓占比
    max_open_orders: int = 0  # 最大挂单数


@dataclass
class RiskEvent:
    """风险事件记录"""
    event_type: RiskEventType
    risk_level: RiskLevel
    user_id: int
    item_id: Optional[int] = None
    details: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)




# ==================== 风险检查器基类 ====================

class RiskCheckerBase:
    """风险检查器基类"""
    
    def __init__(self, risk_manager: 'RiskManager'):
        self.risk_manager = risk_manager
        self._enabled = True
    
    @property
    def enabled(self) -> bool:
        """检查器是否启用"""
        return self._enabled
    
    @enabled.setter
    def enabled(self, value: bool):
        self._enabled = value
    
    async def check(
        self,
        user_id: int,
        **kwargs
    ) -> Tuple[bool, Optional[RiskEvent]]:
        """
        执行风险检查
        
        Args:
            user_id: 用户ID
            **kwargs: 子类需要的额外参数
        
        Returns:
            (是否通过检查, 风险事件)
        """
        raise NotImplementedError("子类必须实现check方法")
    
    def _create_event(
        self,
        event_type: RiskEventType,
        risk_level: RiskLevel,
        user_id: int,
        details: str,
        item_id: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> RiskEvent:
        """创建风险事件"""
        return RiskEvent(
            event_type=event_type,
            risk_level=risk_level,
            user_id=user_id,
            item_id=item_id,
            details=details,
            metadata=metadata or {}
        )


class PriceDeviationChecker(RiskCheckerBase):
    """价格偏离检查器"""
    
    DEFAULT_THRESHOLD = 15.0  # 15%
    
    def __init__(self, risk_manager: 'RiskManager', threshold: float = DEFAULT_THRESHOLD):
        super().__init__(risk_manager)
        self.threshold = threshold
    
    async def check(
        self,
        user_id: int,
        item_id: int,
        proposed_price: float,
        **kwargs
    ) -> Tuple[bool, Optional[RiskEvent]]:
        """检查价格偏离是否过大"""
        if not self._enabled:
            return True, None
        
        try:
            market_price = await self._get_market_price(item_id)
            if not market_price or market_price <= 0:
                return True, None
            
            deviation = abs(proposed_price - market_price) / market_price * 100
            
            if deviation > self.threshold:
                event = self._create_event(
                    event_type=RiskEventType.SUSPICIOUS_PATTERN,
                    risk_level=RiskLevel.HIGH,
                    user_id=user_id,
                    item_id=item_id,
                    details=f"价格偏离过大: 偏离 {deviation:.1f}% (阈值: {self.threshold}%)",
                    metadata={
                        "proposed_price": proposed_price,
                        "market_price": market_price,
                        "deviation": deviation,
                        "threshold": self.threshold,
                        "checker": "price_deviation"
                    }
                )
                logger.warning(
                    f"价格偏离检查失败: user_id={user_id}, item_id={item_id}, "
                    f"proposed={proposed_price}, market={market_price}, deviation={deviation}%"
                )
                return False, event
            
            return True, None
        except Exception as e:
            logger.error(f"价格偏离检查异常: {e}")
            return True, None
    
    async def _get_market_price(self, item_id: int) -> Optional[float]:
        """获取物品市场价格"""
        try:
            result = await self.risk_manager.db.execute(
                select(Item.steam_lowest_price).where(Item.id == item_id)
            )
            price = result.scalar_one_or_none()
            return float(price) if price else None
        except Exception as e:
            logger.error(f"获取市场价格失败: {e}")
            return None


class WashTradeChecker(RiskCheckerBase):
    """刷单检测器"""
    
    DEFAULT_MIN_TRADES = 5
    DEFAULT_TIME_WINDOW = 300  # 5分钟
    DEFAULT_MAX_TRADES = 20
    
    def __init__(
        self,
        risk_manager: 'RiskManager',
        min_trades: int = DEFAULT_MIN_TRADES,
        time_window: int = DEFAULT_TIME_WINDOW,
        max_trades: int = DEFAULT_MAX_TRADES
    ):
        super().__init__(risk_manager)
        self.min_trades = min_trades
        self.time_window = time_window
        self.max_trades = max_trades
    
    async def check(
        self,
        user_id: int,
        **kwargs
    ) -> Tuple[bool, Optional[RiskEvent]]:
        """检测刷单模式"""
        if not self._enabled:
            return True, None
        
        try:
            trade_count = await self._get_recent_trade_count(user_id)
            
            if trade_count >= self.max_trades:
                event = self._create_event(
                    event_type=RiskEventType.SUSPICIOUS_PATTERN,
                    risk_level=RiskLevel.CRITICAL,
                    user_id=user_id,
                    details=f"检测到刷单模式: {trade_count} 笔交易/{self.time_window//60}分钟",
                    metadata={
                        "trade_count": trade_count,
                        "time_window": self.time_window,
                        "max_trades": self.max_trades,
                        "checker": "wash_trade"
                    }
                )
                logger.warning(
                    f"刷单检测: user_id={user_id}, count={trade_count}, "
                    f"window={self.time_window}s"
                )
                return False, event
            
            if trade_count >= self.min_trades:
                logger.info(f"交易频繁提醒: user_id={user_id}, count={trade_count}")
            
            return True, None
        except Exception as e:
            logger.error(f"刷单检测异常: {e}")
            return True, None
    
    async def _get_recent_trade_count(self, user_id: int) -> int:
        """获取最近时间窗口内的交易次数"""
        try:
            time_threshold = datetime.utcnow() - timedelta(seconds=self.time_window)
            result = await self.risk_manager.db.execute(
                select(func.count(Order.id))
                .where(Order.user_id == user_id, Order.created_at >= time_threshold)
            )
            count = result.scalar()
            return int(count) if count else 0
        except Exception as e:
            logger.error(f"获取交易次数失败: {e}")
            return 0


class HighFrequencyChecker(RiskCheckerBase):
    """高频交易检测器"""
    
    DEFAULT_TIME_WINDOW = 60  # 1分钟
    DEFAULT_MAX_TRADES = 10
    
    def __init__(
        self,
        risk_manager: 'RiskManager',
        time_window: int = DEFAULT_TIME_WINDOW,
        max_trades: int = DEFAULT_MAX_TRADES
    ):
        super().__init__(risk_manager)
        self.time_window = time_window
        self.max_trades = max_trades
    
    async def check(
        self,
        user_id: int,
        **kwargs
    ) -> Tuple[bool, Optional[RiskEvent]]:
        """检测高频交易"""
        if not self._enabled:
            return True, None
        
        try:
            trade_count = await self._get_recent_trade_count(user_id)
            
            if trade_count >= self.max_trades:
                event = self._create_event(
                    event_type=RiskEventType.SUSPICIOUS_PATTERN,
                    risk_level=RiskLevel.HIGH,
                    user_id=user_id,
                    details=f"高频交易检测: {trade_count} 笔交易/{self.time_window}秒",
                    metadata={
                        "trade_count": trade_count,
                        "time_window": self.time_window,
                        "max_trades": self.max_trades,
                        "checker": "high_frequency"
                    }
                )
                logger.warning(f"高频交易检测: user_id={user_id}, count={trade_count}")
                return False, event
            
            return True, None
        except Exception as e:
            logger.error(f"高频交易检测异常: {e}")
            return True, None
    
    async def _get_recent_trade_count(self, user_id: int) -> int:
        """获取最近时间窗口内的交易次数"""
        try:
            time_threshold = datetime.utcnow() - timedelta(seconds=self.time_window)
            result = await self.risk_manager.db.execute(
                select(func.count(Order.id))
                .where(Order.user_id == user_id, Order.created_at >= time_threshold)
            )
            count = result.scalar()
            return int(count) if count else 0
        except Exception as e:
            logger.error(f"获取交易次数失败: {e}")
            return 0


class RiskManager:
    """风险管理器"""
    
    # Redis键前缀
    _RISK_EVENTS_KEY = "risk:events:{user_id}"
    _USER_POSITIONS_KEY = "risk:positions:{user_id}"
    _DAILY_STATS_KEY = "risk:daily:{user_id}:{date}"
    _RISK_FLAGS_KEY = "risk:flags:{user_id}"
    
    def __init__(self, db: AsyncSession, checker_config: Dict[str, Dict[str, Any]] = None):
        self.db = db
        self._rules = self._load_default_rules()
        self._redis = None
        # 初始化风险检查器，支持配置化
        self._init_checkers(checker_config)
    
    def _init_checkers(self, checker_config: Dict[str, Dict[str, Any]] = None):
        """初始化风险检查器
        
        Args:
            checker_config: 检查器配置字典，格式如：
                {
                    "price_deviation": {"threshold": 15.0},
                    "wash_trade": {"enabled": True},
                    "high_frequency": {"max_frequency_per_minute": 10}
                }
        """
        if checker_config is None:
            checker_config = {}
        
        self.checkers: Dict[str, RiskCheckerBase] = {}
        
        # 价格偏离检查器
        price_config = checker_config.get("price_deviation", {})
        self.checkers["price_deviation"] = PriceDeviationChecker(
            self, 
            threshold=price_config.get("threshold", 15.0)
        )
        
        # 刷单检查器
        wash_config = checker_config.get("wash_trade", {})
        self.checkers["wash_trade"] = WashTradeChecker(self)
        
        # 高频交易检查器
        hf_config = checker_config.get("high_frequency", {})
        self.checkers["high_frequency"] = HighFrequencyChecker(
            self,
            time_window=hf_config.get("time_window", 60),
            max_trades=hf_config.get("max_trades", 10)
        )
    
    def _load_default_rules(self) -> Dict[str, RiskRule]:
        """加载默认风险规则"""
        return {
            "position_size": RiskRule(
                name="position_size",
                enabled=True,
                max_position_size=settings.MAX_SINGLE_TRADE * 5,  # 5倍单笔限额
            ),
            "single_trade": RiskRule(
                name="single_trade",
                enabled=True,
                max_single_trade=settings.MAX_SINGLE_TRADE,
            ),
            "daily_limit": RiskRule(
                name="daily_limit",
                enabled=True,
                max_daily_trade_amount=settings.MAX_DAILY_LIMIT,
            ),
            "stop_loss": RiskRule(
                name="stop_loss",
                enabled=True,
                stop_loss_percent=10.0,  # 10%止损
            ),
            "take_profit": RiskRule(
                name="take_profit",
                enabled=True,
                take_profit_percent=30.0,  # 30%止盈
            ),
            "concentration": RiskRule(
                name="concentration",
                enabled=True,
                max_position_concentration=0.3,  # 30%单品种上限
            ),
        }
    
    async def _get_redis(self):
        """获取Redis客户端"""
        if self._redis is None:
            try:
                self._redis = await get_redis()
            except Exception as e:
                logger.warning(f"Redis连接失败，使用内存存储: {e}")
                self._redis = None
        return self._redis
    
    # ==================== 风险检查接口 ====================
    
    async def check_trade_risk(
        self,
        user_id: int,
        item_id: int,
        price: float,
        quantity: int = 1,
        side: str = "buy"
    ) -> Tuple[bool, List[RiskEvent]]:
        """
        执行交易前风险检查
        
        Args:
            user_id: 用户ID
            item_id: 物品ID
            price: 价格
            quantity: 数量
            side: 买入/卖出
        
        Returns:
            (是否通过检查, 风险事件列表)
        """
        events = []
        
        # 1. 检查单笔交易限额
        passed, event = await self._check_single_trade_limit(user_id, price, quantity)
        if not passed:
            events.append(event)
        
        # 2. 检查每日限额
        passed, event = await self._check_daily_limit(user_id, price * quantity)
        if not passed:
            events.append(event)
        
        # 3. 检查持仓限额
        passed, event = await self._check_position_limit(user_id, item_id, price * quantity)
        if not passed:
            events.append(event)
        
        # 4. 检查止损/止盈（仅卖出时）
        if side == "sell":
            passed, event = await self._check_stop_loss(user_id, item_id, price)
            if not passed:
                events.append(event)
            
            passed, event = await self._check_take_profit(user_id, item_id, price)
            if not passed:
                events.append(event)
        
        # 5. 检查持仓集中度
        passed, event = await self._check_concentration_risk(user_id, item_id, price * quantity)
        if not passed:
            events.append(event)
        
        # 6. 检查价格偏离（买入时）
        if side == "buy":
            price_checker = self.checkers.get("price_deviation")
            if price_checker and price_checker.enabled:
                passed, event = await price_checker.check(
                    user_id=user_id,
                    item_id=item_id,
                    proposed_price=price
                )
                if not passed:
                    events.append(event)
        
        # 7. 检查刷单/高频交易模式
        wash_checker = self.checkers.get("wash_trade")
        if wash_checker and wash_checker.enabled:
            passed, event = await wash_checker.check(user_id=user_id)
            if not passed:
                events.append(event)
        
        high_freq_checker = self.checkers.get("high_frequency")
        if high_freq_checker and high_freq_checker.enabled:
            passed, event = await high_freq_checker.check(user_id=user_id)
            if not passed:
                events.append(event)
        
        # 如果有任何高风险或严重风险事件，拒绝交易
        has_critical = any(e.risk_level == RiskLevel.CRITICAL for e in events)
        
        # 记录所有风险事件
        for event in events:
            await self._record_risk_event(event)
        
        return not has_critical, events
    
    async def check_position_risk(
        self,
        user_id: int,
        item_id: int
    ) -> Dict[str, Any]:
        """
        检查持仓风险状态
        
        Args:
            user_id: 用户ID
            item_id: 物品ID
        
        Returns:
            持仓风险状态
        """
        # 获取当前持仓
        position = await self._get_user_position(user_id, item_id)
        
        # 获取成本价
        cost_basis = await self._get_cost_basis(user_id, item_id)
        
        # 计算当前盈亏
        if position and cost_basis:
            current_value = position.get("quantity", 0) * position.get("avg_price", 0)
            cost = position.get("quantity", 0) * cost_basis
            unrealized_pnl = current_value - cost
            pnl_percent = (unrealized_pnl / cost * 100) if cost > 0 else 0
        else:
            unrealized_pnl = 0
            pnl_percent = 0
        
        # 检查是否触发止损
        stop_loss_triggered = False
        if cost_basis and pnl_percent <= -self._rules["stop_loss"].stop_loss_percent:
            stop_loss_triggered = True
        
        # 检查是否触发止盈
        take_profit_triggered = False
        if cost_basis and pnl_percent >= self._rules["take_profit"].take_profit_percent:
            take_profit_triggered = True
        
        return {
            "has_position": position is not None,
            "quantity": position.get("quantity", 0) if position else 0,
            "avg_price": position.get("avg_price", 0) if position else 0,
            "cost_basis": cost_basis,
            "current_value": current_value if position else 0,
            "unrealized_pnl": unrealized_pnl,
            "pnl_percent": pnl_percent,
            "stop_loss_triggered": stop_loss_triggered,
            "take_profit_triggered": take_profit_triggered,
            "stop_loss_threshold": -self._rules["stop_loss"].stop_loss_percent,
            "take_profit_threshold": self._rules["take_profit"].take_profit_percent,
        }
    
    # ==================== 规则检查方法 ====================
    
    async def _check_single_trade_limit(
        self,
        user_id: int,
        price: float,
        quantity: int
    ) -> Tuple[bool, Optional[RiskEvent]]:
        """检查单笔交易限额"""
        rule = self._rules.get("single_trade")
        if not rule or not rule.enabled:
            return True, None
        
        total = price * quantity
        if total > rule.max_single_trade:
            event = RiskEvent(
                event_type=RiskEventType.SINGLE_TRADE_EXCEEDED,
                risk_level=RiskLevel.HIGH,
                user_id=user_id,
                details=f"单笔交易金额 {total:.2f} 超过限额 {rule.max_single_trade:.2f}",
                metadata={"amount": total, "limit": rule.max_single_trade}
            )
            logger.warning(f"单笔交易限额检查失败: user_id={user_id}, amount={total}")
            return False, event
        
        return True, None
    
    async def _check_daily_limit(
        self,
        user_id: int,
        amount: float
    ) -> Tuple[bool, Optional[RiskEvent]]:
        """检查每日交易限额"""
        rule = self._rules.get("daily_limit")
        if not rule or not rule.enabled:
            return True, None
        
        # 获取当日已交易金额
        daily_amount = await self._get_daily_trade_amount(user_id)
        new_total = daily_amount + amount
        
        if new_total > rule.max_daily_trade_amount:
            event = RiskEvent(
                event_type=RiskEventType.DAILY_LIMIT_EXCEEDED,
                risk_level=RiskLevel.CRITICAL,
                user_id=user_id,
                details=f"当日交易金额 {new_total:.2f} 超过限额 {rule.max_daily_trade_amount:.2f}",
                metadata={
                    "current_amount": daily_amount,
                    "new_amount": amount,
                    "total": new_total,
                    "limit": rule.max_daily_trade_amount
                }
            )
            logger.warning(f"每日交易限额检查失败: user_id={user_id}, amount={new_total}")
            return False, event
        
        return True, None
    
    async def _check_position_limit(
        self,
        user_id: int,
        item_id: int,
        amount: float
    ) -> Tuple[bool, Optional[RiskEvent]]:
        """检查持仓限额"""
        rule = self._rules.get("position_size")
        if not rule or not rule.enabled:
            return True, None
        
        # 获取当前总持仓
        current_position = await self._get_total_position(user_id)
        new_total = current_position + amount
        
        if new_total > rule.max_position_size:
            event = RiskEvent(
                event_type=RiskEventType.POSITION_SIZE_EXCEEDED,
                risk_level=RiskLevel.HIGH,
                user_id=user_id,
                item_id=item_id,
                details=f"总持仓 {new_total:.2f} 超过限额 {rule.max_position_size:.2f}",
                metadata={
                    "current_position": current_position,
                    "new_amount": amount,
                    "total": new_total,
                    "limit": rule.max_position_size
                }
            )
            logger.warning(f"持仓限额检查失败: user_id={user_id}, position={new_total}")
            return False, event
        
        return True, None
    
    async def _check_concentration_risk(
        self,
        user_id: int,
        item_id: int,
        amount: float
    ) -> Tuple[bool, Optional[RiskEvent]]:
        """检查持仓集中度风险"""
        rule = self._rules.get("concentration")
        if not rule or not rule.enabled:
            return True, None
        
        # 获取当前总持仓
        total_position = await self._get_total_position(user_id)
        
        # 如果没有持仓，直接通过
        if total_position <= 0:
            return True, None
        
        # 计算新增后的单品种占比
        item_position = await self._get_item_position(user_id, item_id)
        new_item_value = item_position + amount
        
        concentration = new_item_value / (total_position + amount)
        
        if concentration > rule.max_position_concentration:
            event = RiskEvent(
                event_type=RiskEventType.CONCENTRATION_RISK,
                risk_level=RiskLevel.MEDIUM,
                user_id=user_id,
                item_id=item_id,
                details=f"单品种持仓占比 {concentration*100:.1f}% 超过限额 {rule.max_position_concentration*100:.1f}%",
                metadata={
                    "item_position": new_item_value,
                    "total_position": total_position + amount,
                    "concentration": concentration,
                    "limit": rule.max_position_concentration
                }
            )
            logger.warning(f"集中度风险检查失败: user_id={user_id}, concentration={concentration}")
            return False, event
        
        return True, None
    
    async def _check_stop_loss(
        self,
        user_id: int,
        item_id: int,
        current_price: float
    ) -> Tuple[bool, Optional[RiskEvent]]:
        """检查是否触发止损"""
        rule = self._rules.get("stop_loss")
        if not rule or not rule.enabled:
            return True, None
        
        # 获取持仓信息
        position = await self._get_user_position(user_id, item_id)
        if not position:
            return True, None
        
        cost_basis = await self._get_cost_basis(user_id, item_id)
        if not cost_basis:
            return True, None
        
        # 计算亏损百分比
        pnl_percent = (current_price - cost_basis) / cost_basis * 100
        
        if pnl_percent <= -rule.stop_loss_percent:
            event = RiskEvent(
                event_type=RiskEventType.STOP_LOSS_TRIGGERED,
                risk_level=RiskLevel.CRITICAL,
                user_id=user_id,
                item_id=item_id,
                details=f"触发止损: 亏损 {abs(pnl_percent):.1f}% (阈值: {rule.stop_loss_percent}%)",
                metadata={
                    "current_price": current_price,
                    "cost_basis": cost_basis,
                    "pnl_percent": pnl_percent,
                    "threshold": -rule.stop_loss_percent
                }
            )
            logger.warning(f"止损触发: user_id={user_id}, item_id={item_id}, pnl={pnl_percent}%")
            return False, event
        
        return True, None
    
    async def _check_take_profit(
        self,
        user_id: int,
        item_id: int,
        current_price: float
    ) -> Tuple[bool, Optional[RiskEvent]]:
        """检查是否触发止盈"""
        rule = self._rules.get("take_profit")
        if not rule or not rule.enabled:
            return True, None
        
        # 获取持仓信息
        position = await self._get_user_position(user_id, item_id)
        if not position:
            return True, None
        
        cost_basis = await self._get_cost_basis(user_id, item_id)
        if not cost_basis:
            return True, None
        
        # 计算盈利百分比
        pnl_percent = (current_price - cost_basis) / cost_basis * 100
        
        if pnl_percent >= rule.take_profit_percent:
            event = RiskEvent(
                event_type=RiskEventType.TAKE_PROFIT_TRIGGERED,
                risk_level=RiskLevel.LOW,
                user_id=user_id,
                item_id=item_id,
                details=f"触发止盈: 盈利 {pnl_percent:.1f}% (阈值: {rule.take_profit_percent}%)",
                metadata={
                    "current_price": current_price,
                    "cost_basis": cost_basis,
                    "pnl_percent": pnl_percent,
                    "threshold": rule.take_profit_percent
                }
            )
            logger.info(f"止盈触发: user_id={user_id}, item_id={item_id}, pnl={pnl_percent}%")
            return False, event
        
        return True, None
    
    # ==================== 数据查询方法 ====================
    
    async def _get_total_position(self, user_id: int) -> float:
        """获取用户总持仓金额"""
        try:
            redis_client = await self._get_redis()
            if redis_client:
                key = self._USER_POSITIONS_KEY.format(user_id=user_id)
                data = await redis_client.hgetall(key)
                if data:
                    return sum(float(v) for v in data.values())
            
            # 回退到数据库查询
            result = await self.db.execute(
                select(func.sum(Inventory.quantity * Inventory.cost_basis))
                .where(Inventory.user_id == user_id)
            )
            total = result.scalar()
            return float(total) if total else 0
        except Exception as e:
            logger.error(f"获取总持仓失败: {e}")
            return 0
    
    async def _get_item_position(self, user_id: int, item_id: int) -> float:
        """获取用户单品种持仓金额"""
        try:
            redis_client = await self._get_redis()
            if redis_client:
                key = self._USER_POSITIONS_KEY.format(user_id=user_id)
                position = await redis_client.hget(key, str(item_id))
                return float(position) if position else 0
            
            # 回退到数据库查询
            result = await self.db.execute(
                select(func.sum(Inventory.quantity * Inventory.cost_basis))
                .where(Inventory.user_id == user_id, Inventory.item_id == item_id)
            )
            total = result.scalar()
            return float(total) if total else 0
        except Exception as e:
            logger.error(f"获取单品种持仓失败: {e}")
            return 0
    
    async def _get_user_position(self, user_id: int, item_id: int) -> Optional[Dict]:
        """获取用户持仓详情"""
        try:
            result = await self.db.execute(
                select(Inventory).where(
                    Inventory.user_id == user_id,
                    Inventory.item_id == item_id
                )
            )
            inv = result.scalar_one_or_none()
            if inv:
                return {
                    "quantity": inv.quantity,
                    "avg_price": inv.cost_basis
                }
            return None
        except Exception as e:
            logger.error(f"获取持仓详情失败: {e}")
            return None
    
    async def _get_cost_basis(self, user_id: int, item_id: int) -> Optional[float]:
        """获取持仓成本价"""
        position = await self._get_user_position(user_id, item_id)
        return position.get("avg_price") if position else None
    
    async def _get_daily_trade_amount(self, user_id: int) -> float:
        """获取当日交易金额"""
        today = datetime.utcnow().strftime("%Y-%m-%d")
        try:
            redis_client = await self._get_redis()
            if redis_client:
                key = self._DAILY_STATS_KEY.format(user_id=user_id, date=today)
                amount = await redis_client.get(key)
                return float(amount) if amount else 0
            
            # 回退到数据库查询
            start_of_day = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            result = await self.db.execute(
                select(func.sum(Order.price * Order.quantity))
                .where(
                    Order.user_id == user_id,
                    Order.created_at >= start_of_day,
                    Order.side == "buy"
                )
            )
            total = result.scalar()
            return float(total) if total else 0
        except Exception as e:
            logger.error(f"获取当日交易金额失败: {e}")
            return 0
    
    # ==================== 持仓更新方法 ====================
    
    async def update_position(
        self,
        user_id: int,
        item_id: int,
        quantity: int,
        price: float,
        side: str
    ) -> None:
        """更新持仓"""
        try:
            redis_client = await self._get_redis()
            if redis_client:
                key = self._USER_POSITIONS_KEY.format(user_id=user_id)
                current = await redis_client.hget(key, str(item_id))
                current_value = float(current) if current else 0
                
                if side == "buy":
                    new_value = current_value + (quantity * price)
                else:
                    new_value = max(0, current_value - (quantity * price))
                
                await redis_client.hset(key, str(item_id), str(new_value))
                
                # 更新每日交易金额
                if side == "buy":
                    today = datetime.utcnow().strftime("%Y-%m-%d")
                    daily_key = self._DAILY_STATS_KEY.format(user_id=user_id, date=today)
                    await redis_client.incrby(daily_key, quantity * price)
                    # 设置过期时间为48小时
                    await redis_client.expire(daily_key, 48 * 3600)
        except Exception as e:
            logger.error(f"更新持仓失败: {e}")
    
    # ==================== 风险事件记录 ====================
    
    async def _record_risk_event(self, event: RiskEvent) -> None:
        """记录风险事件"""
        try:
            redis_client = await self._get_redis()
            if redis_client:
                key = self._RISK_EVENTS_KEY.format(user_id=event.user_id)
                event_data = {
                    "type": event.event_type.value,
                    "level": event.risk_level.value,
                    "timestamp": event.timestamp.isoformat(),
                    "details": event.details,
                    "metadata": str(event.metadata)
                }
                await redis_client.lpush(key, str(event_data))
                await redis_client.ltrim(key, 0, 99)  # 保留最近100条
                await redis_client.expire(key, 7 * 24 * 3600)  # 7天过期
        except Exception as e:
            logger.error(f"记录风险事件失败: {e}")
    
    async def get_risk_events(
        self,
        user_id: int,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """获取风险事件列表"""
        try:
            redis_client = await self._get_redis()
            if redis_client:
                key = self._RISK_EVENTS_KEY.format(user_id=user_id)
                events = await redis_client.lrange(key, 0, limit - 1)
                return [json.loads(e) for e in events]  # 使用JSON解析替代eval
            return []
        except Exception as e:
            logger.error(f"获取风险事件失败: {e}")
            return []
    
    async def clear_risk_flags(self, user_id: int) -> None:
        """清除风险标志"""
        try:
            redis_client = await self._get_redis()
            if redis_client:
                key = self._RISK_FLAGS_KEY.format(user_id=user_id)
                await redis_client.delete(key)
        except Exception as e:
            logger.error(f"清除风险标志失败: {e}")
    
    # ==================== 规则管理方法 ====================
    
    def update_rule(self, rule_name: str, **kwargs) -> bool:
        """更新风险规则"""
        if rule_name in self._rules:
            rule = self._rules[rule_name]
            for key, value in kwargs.items():
                if hasattr(rule, key):
                    setattr(rule, key, value)
            return True
        return False
    
    def get_rules(self) -> Dict[str, Dict]:
        """获取所有风险规则"""
        return {
            name: {
                "enabled": rule.enabled,
                "max_position_size": rule.max_position_size,
                "max_single_trade": rule.max_single_trade,
                "max_daily_trade_amount": rule.max_daily_trade_amount,
                "stop_loss_percent": rule.stop_loss_percent,
                "take_profit_percent": rule.take_profit_percent,
                "max_position_concentration": rule.max_position_concentration,
            }
            for name, rule in self._rules.items()
        }
    
    # ==================== 检查器管理方法 ====================
    
    def get_checkers(self) -> Dict[str, Dict]:
        """获取所有检查器状态"""
        return {
            name: {
                "enabled": checker.enabled,
                "type": type(checker).__name__
            }
            for name, checker in self.checkers.items()
        }
    
    def enable_checker(self, checker_name: str) -> bool:
        """启用检查器"""
        if checker_name in self.checkers:
            self.checkers[checker_name].enabled = True
            return True
        return False
    
    def disable_checker(self, checker_name: str) -> bool:
        """禁用检查器"""
        if checker_name in self.checkers:
            self.checkers[checker_name].enabled = False
            return True
        return False
    
    def configure_checker(self, checker_name: str, **kwargs) -> bool:
        """配置检查器参数"""
        if checker_name not in self.checkers:
            return False
        
        checker = self.checkers[checker_name]
        for key, value in kwargs.items():
            if hasattr(checker, key):
                setattr(checker, key, value)
        return True


# ==================== 便捷函数 ====================

async def get_risk_manager(db: AsyncSession) -> RiskManager:
    """获取风险管理器实例"""
    return RiskManager(db)
