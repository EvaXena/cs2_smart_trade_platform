# -*- coding: utf-8 -*-
"""
策略回测引擎
"""
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Callable
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


@dataclass
class PriceData:
    """价格数据"""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass
class Trade:
    """交易记录"""
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    side: str  # 'buy' / 'sell'
    quantity: int
    profit: float = 0.0
    commission: float = 0.0


@dataclass
class Position:
    """持仓"""
    entry_time: datetime
    entry_price: float
    quantity: int
    side: str = "buy"


@dataclass
class BacktestResult:
    """回测结果"""
    # 基本信息
    start_date: datetime
    end_date: datetime
    initial_capital: float
    final_capital: float
    
    # 收益率
    total_return: float = 0.0  # 总收益率
    annual_return: float = 0.0  # 年化收益率
    
    # 风险指标
    max_drawdown: float = 0.0  # 最大回撤
    max_drawdown_pct: float = 0.0  # 最大回撤百分比
    
    # 收益指标
    sharpe_ratio: float = 0.0  # 夏普比率
    sortino_ratio: float = 0.0  # 索提诺比率
    
    # 交易统计
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0  # 胜率
    avg_win: float = 0.0  # 平均盈利
    avg_loss: float = 0.0  # 平均亏损
    profit_factor: float = 0.0  # 盈利因子
    
    # 时间统计
    total_days: int = 0
    avg_trade_duration: float = 0.0  # 平均持仓时间(天)
    
    # 交易列表
    trades: List[Trade] = field(default_factory=list)
    
    # 每日权益
    equity_curve: List[Dict[str, Any]] = field(default_factory=list)


class BacktestEngine:
    """回测引擎"""
    
    def __init__(
        self,
        initial_capital: float = 10000.0,
        commission: float = 0.005,  # 手续费率 0.5%
        slippage: float = 0.001,    # 滑点 0.1%
        position_size: float = 1.0,  # 仓位比例
    ):
        """
        初始化回测引擎
        
        Args:
            initial_capital: 初始资金
            commission: 手续费率
            slippage: 滑点率
            position_size: 仓位比例 (0.1 - 1.0)
        """
        self.initial_capital = initial_capital
        self.commission = commission
        self.slippage = slippage
        self.position_size = max(0.1, min(1.0, position_size))
        
        self.data: List[PriceData] = []
        self.results: Optional[BacktestResult] = None
    
    def load_data(self, data: List[PriceData]) -> None:
        """加载历史价格数据"""
        self.data = sorted(data, key=lambda x: x.timestamp)
        logger.info(f"加载回测数据: {len(self.data)} 条")
    
    def load_data_from_list(
        self,
        timestamps: List[datetime],
        opens: List[float],
        highs: List[float],
        lows: List[float],
        closes: List[float],
        volumes: List[float] = None
    ) -> None:
        """从列表加载数据"""
        if volumes is None:
            volumes = [0.0] * len(timestamps)
        
        self.data = [
            PriceData(
                timestamp=t,
                open=o,
                high=h,
                low=l,
                close=c,
                volume=v
            )
            for t, o, h, l, c, v in zip(timestamps, opens, highs, lows, closes, volumes)
        ]
        self.data = sorted(self.data, key=lambda x: x.timestamp)
        logger.info(f"加载回测数据: {len(self.data)} 条")
    
    def run(
        self,
        strategy_func: Callable,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        **strategy_params
    ) -> BacktestResult:
        """
        运行回测
        
        Args:
            strategy_func: 策略函数，接收 (current_price, history, **params) 返回交易信号
                          信号: 'buy', 'sell', 'hold'
            start_date: 回测开始日期
            end_date: 回测结束日期
            strategy_params: 策略参数
        
        Returns:
            BacktestResult: 回测结果
        """
        if not self.data:
            raise ValueError("请先加载数据")
        
        # 过滤日期范围
        data = self.data
        if start_date:
            data = [d for d in data if d.timestamp >= start_date]
        if end_date:
            data = [d for d in data if d.timestamp <= end_date]
        
        if not data:
            raise ValueError("没有符合日期范围的数据")
        
        # 初始化
        capital = self.initial_capital
        position: Optional[Position] = None
        trades: List[Trade] = []
        equity_curve = []
        peak_capital = capital
        max_drawdown = 0.0
        
        # 策略状态
        strategy_state = {}
        
        logger.info(f"开始回测: {len(data)} 条数据")
        
        # 遍历数据
        for i, bar in enumerate(data):
            current_price = bar.close
            history = data[:i+1]  # 包含当前的历史数据
            
            # 获取交易信号
            try:
                signal = strategy_func(
                    current_price=current_price,
                    history=history,
                    position=position,
                    **strategy_params
                )
            except Exception as e:
                logger.warning(f"策略执行错误: {e}")
                signal = 'hold'
            
            # 执行交易
            if signal == 'buy' and position is None:
                # 买入
                buy_price = current_price * (1 + self.slippage)  # 滑点买入
                cost = buy_price * self.position_size * self.commission  # 手续费
                
                if capital >= buy_price * self.position_size + cost:
                    capital -= buy_price * self.position_size + cost
                    position = Position(
                        entry_time=bar.timestamp,
                        entry_price=buy_price,
                        quantity=int(self.position_size),
                        side="buy"
                    )
                    logger.debug(f"买入: {bar.timestamp}, 价格: {buy_price:.2f}")
            
            elif signal == 'sell' and position is not None:
                # 卖出
                sell_price = current_price * (1 - self.slippage)  # 滑点卖出
                revenue = sell_price * position.quantity
                cost = revenue * self.commission  # 手续费
                
                profit = (sell_price - position.entry_price) * position.quantity - cost
                capital += revenue - cost
                
                trades.append(Trade(
                    entry_time=position.entry_time,
                    exit_time=bar.timestamp,
                    entry_price=position.entry_price,
                    exit_price=sell_price,
                    side="sell",
                    quantity=position.quantity,
                    profit=profit,
                    commission=cost
                ))
                
                logger.debug(f"卖出: {bar.timestamp}, 价格: {sell_price:.2f}, 盈利: {profit:.2f}")
                position = None
            
            # 更新权益
            current_value = capital
            if position:
                current_value += current_price * position.quantity
            
            # 计算回撤
            if current_value > peak_capital:
                peak_capital = current_value
            
            drawdown = (peak_capital - current_value) / peak_capital
            if drawdown > max_drawdown:
                max_drawdown = drawdown
            
            equity_curve.append({
                "timestamp": bar.timestamp,
                "capital": capital,
                "position_value": current_price * position.quantity if position else 0,
                "total_value": current_value,
                "drawdown": drawdown
            })
        
        # 平仓
        if position:
            last_bar = data[-1]
            sell_price = last_bar.close * (1 - self.slippage)
            cost = sell_price * position.quantity * self.commission
            profit = (sell_price - position.entry_price) * position.quantity - cost
            capital += sell_price * position.quantity - cost
            
            trades.append(Trade(
                entry_time=position.entry_time,
                exit_time=last_bar.timestamp,
                entry_price=position.entry_price,
                exit_price=sell_price,
                side="sell",
                quantity=position.quantity,
                profit=profit,
                commission=cost
            ))
        
        # 计算结果
        final_capital = capital
        total_return = (final_capital - self.initial_capital) / self.initial_capital
        
        # 计算年化收益率
        days = (data[-1].timestamp - data[0].timestamp).days
        years = days / 365.0 if days > 0 else 1
        annual_return = (1 + total_return) ** (1 / years) - 1
        
        # 计算夏普比率（假设无风险利率为0）
        if len(equity_curve) > 1:
            returns = []
            for i in range(1, len(equity_curve)):
                ret = (equity_curve[i]["total_value"] - equity_curve[i-1]["total_value"]) / equity_curve[i-1]["total_value"]
                returns.append(ret)
            
            if returns and len(returns) > 1:
                avg_return = sum(returns) / len(returns)
                std_return = (sum((r - avg_return) ** 2 for r in returns) / len(returns)) ** 0.5
                sharpe_ratio = (avg_return / std_return * (252 ** 0.5)) if std_return > 0 else 0
            else:
                sharpe_ratio = 0
        else:
            sharpe_ratio = 0
        
        # 交易统计
        winning_trades = [t for t in trades if t.profit > 0]
        losing_trades = [t for t in trades if t.profit <= 0]
        
        win_rate = len(winning_trades) / len(trades) if trades else 0
        avg_win = sum(t.profit for t in winning_trades) / len(winning_trades) if winning_trades else 0
        avg_loss = sum(t.profit for t in losing_trades) / len(losing_trades) if losing_trades else 0
        
        total_wins = sum(t.profit for t in winning_trades)
        total_losses = abs(sum(t.profit for t in losing_trades))
        profit_factor = total_wins / total_losses if total_losses > 0 else float('inf') if total_wins > 0 else 0
        
        # 平均持仓时间
        if trades:
            total_duration = sum((t.exit_time - t.entry_time).days for t in trades)
            avg_duration = total_duration / len(trades)
        else:
            avg_duration = 0
        
        # 构建结果
        self.results = BacktestResult(
            start_date=data[0].timestamp,
            end_date=data[-1].timestamp,
            initial_capital=self.initial_capital,
            final_capital=final_capital,
            total_return=total_return,
            annual_return=annual_return,
            max_drawdown=max_drawdown,
            max_drawdown_pct=max_drawdown * 100,
            sharpe_ratio=sharpe_ratio,
            total_trades=len(trades),
            winning_trades=len(winning_trades),
            losing_trades=len(losing_trades),
            win_rate=win_rate,
            avg_win=avg_win,
            avg_loss=avg_loss,
            profit_factor=profit_factor,
            total_days=days,
            avg_trade_duration=avg_duration,
            trades=trades,
            equity_curve=equity_curve,
        )
        
        logger.info(f"回测完成: 总收益率 {total_return*100:.2f}%, 交易次数 {len(trades)}")
        
        return self.results
    
    def get_results(self) -> Optional[BacktestResult]:
        """获取回测结果"""
        return self.results


# ============ 预设策略函数 ============

def mean_reversion_strategy(
    current_price: float,
    history: List[PriceData],
    position: Optional[Position] = None,
    mean_period: int = 20,
    mean_type: str = "EMA",
    buy_threshold: float = -2.0,
    sell_threshold: float = 2.0,
    **kwargs
) -> str:
    """
    均值回归策略函数
    
    Args:
        current_price: 当前价格
        history: 历史价格数据
        position: 当前持仓
        mean_period: 均值周期
        mean_type: 均值类型 (MA/EMA)
        buy_threshold: 买入偏离阈值(%)
        sell_threshold: 卖出偏离阈值(%)
    
    Returns:
        信号: 'buy', 'sell', 'hold'
    """
    if len(history) < mean_period:
        return 'hold'
    
    # 计算均值
    closes = [b.close for b in history[-mean_period:]]
    
    if mean_type == "EMA":
        from app.utils.indicators import EMA
        means = EMA(closes, mean_period)
        mean_price = means[-1] if means else closes[-1]
    else:
        mean_price = sum(closes) / len(closes)
    
    # 计算偏离度
    deviation = (current_price - mean_price) / mean_price * 100
    
    # 交易逻辑
    if position is None:
        # 没有持仓，满足买入条件则买入
        if deviation <= buy_threshold:
            return 'buy'
    else:
        # 有持仓，满足卖出条件则卖出
        if deviation >= sell_threshold:
            return 'sell'
    
    return 'hold'


def grid_strategy(
    current_price: float,
    history: List[PriceData],
    position: Optional[Position] = None,
    price_lower: float = 100.0,
    price_upper: float = 200.0,
    grid_count: int = 10,
    profit_percentage: float = 1.0,
    **kwargs
) -> str:
    """
    网格策略函数
    
    Args:
        current_price: 当前价格
        history: 历史价格数据
        position: 当前持仓
        price_lower: 价格下界
        price_upper: 价格上界
        grid_count: 网格数量
        profit_percentage: 止盈百分比
    
    Returns:
        信号: 'buy', 'sell', 'hold'
    """
    if price_upper <= price_lower or grid_count <= 0:
        return 'hold'
    
    # 计算网格
    price_step = (price_upper - price_lower) / (grid_count - 1)
    grid_prices = [price_lower + i * price_step for i in range(grid_count)]
    
    # 找到当前价格所在的网格
    grid_index = 0
    min_diff = abs(current_price - grid_prices[0])
    for i, gp in enumerate(grid_prices):
        diff = abs(current_price - gp)
        if diff < min_diff:
            min_diff = diff
            grid_index = i
    
    if position is None:
        # 没有持仓，低于网格价格买入
        buy_price = grid_prices[grid_index] * (1 - 0.5 / 100)
        if current_price <= buy_price:
            return 'buy'
    else:
        # 有持仓，达到止盈位卖出
        target_price = grid_prices[grid_index] * (1 + profit_percentage / 100)
        if current_price >= target_price:
            return 'sell'
    
    return 'hold'


def trend_following_strategy(
    current_price: float,
    history: List[PriceData],
    position: Optional[Position] = None,
    fast_ma: int = 10,
    slow_ma: int = 30,
    **kwargs
) -> str:
    """
    趋势跟踪策略（双均线）
    
    Args:
        current_price: 当前价格
        history: 历史价格数据
        position: 当前持仓
        fast_ma: 快线周期
        slow_ma: 慢线周期
    
    Returns:
        信号: 'buy', 'sell', 'hold'
    """
    if len(history) < slow_ma:
        return 'hold'
    
    # 计算均线
    closes = [b.close for b in history]
    
    from app.utils.indicators import MA
    
    fast_ma_values = MA(closes, fast_ma)
    slow_ma_values = MA(closes, slow_ma)
    
    if fast_ma_values[-1] is None or slow_ma_values[-1] is None:
        return 'hold'
    
    # 上一根K线的位置
    if len(fast_ma_values) >= 2 and len(slow_ma_values) >= 2:
        prev_fast = fast_ma_values[-2]
        prev_slow = slow_ma_values[-2]
        
        curr_fast = fast_ma_values[-1]
        curr_slow = slow_ma_values[-1]
        
        if prev_fast <= prev_slow and curr_fast > curr_slow:
            # 金叉，买入
            if position is None:
                return 'buy'
        
        elif prev_fast >= prev_slow and curr_fast < curr_slow:
            # 死叉，卖出
            if position is not None:
                return 'sell'
    
    return 'hold'
