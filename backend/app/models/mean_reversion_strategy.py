# -*- coding: utf-8 -*-
"""
均值回归策略数据库模型
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Numeric, DateTime, ForeignKey, Index, Float, Boolean, JSON
from sqlalchemy.orm import relationship

from app.core.database import Base


class MeanReversionStrategy(Base):
    """均值回归策略配置"""
    __tablename__ = "mean_reversion_strategies"

    id = Column(Integer, primary_key=True, index=True)
    
    # 用户
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    
    # 交易品种
    item_id = Column(Integer, ForeignKey("items.id"), nullable=False, index=True)
    
    # 策略名称
    name = Column(String(100), nullable=False)
    
    # 均值回归参数
    mean_period = Column(Integer, nullable=False, default=20)  # 均值周期
    mean_type = Column(String(10), nullable=False, default="EMA")  # 均值类型: MA/EMA
    
    # 交易阈值
    buy_threshold = Column(Float, nullable=False, default=-2.0)  # 买入偏离阈值(%)
    sell_threshold = Column(Float, nullable=False, default=2.0)  # 卖出偏离阈值(%)
    
    # 风控参数
    profit_percentage = Column(Float, nullable=False, default=3.0)  # 止盈百分比
    stop_loss_percentage = Column(Float, nullable=False, default=5.0)  # 止损百分比
    
    # 持仓
    position_size = Column(Integer, nullable=False, default=1)  # 持仓数量
    
    # 状态
    is_active = Column(Boolean, default=True, index=True)
    status = Column(String(20), default='pending', index=True)  # pending/running/paused/stopped
    
    # 当前价格锚点
    last_price = Column(Float, nullable=True)
    entry_price = Column(Float, nullable=True)  # 进场价格
    mean_price = Column(Float, nullable=True)  # 当前均值
    
    # 统计
    total_trades = Column(Integer, default=0)  # 总交易次数
    total_profit = Column(Float, default=0.0)  # 总收益
    winning_trades = Column(Integer, default=0)  # 盈利次数
    losing_trades = Column(Integer, default=0)  # 亏损次数
    
    # 策略状态 (JSON)
    strategy_state = Column(JSON, nullable=True)
    
    # 时间戳
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    stopped_at = Column(DateTime, nullable=True)

    # 关联
    user = relationship("User", backref="mean_reversion_strategies")
    item = relationship("Item", backref="mean_reversion_strategies")
    trades = relationship("MeanReversionTrade", back_populates="strategy", cascade="all, delete-orphan")

    # 索引
    __table_args__ = (
        Index("idx_mr_user_status", "user_id", "status"),
        Index("idx_mr_item_active", "item_id", "is_active"),
    )

    def __repr__(self):
        return f"<MeanReversionStrategy {self.name} {self.status}>"


class MeanReversionTrade(Base):
    """均值回归交易记录"""
    __tablename__ = "mean_reversion_trades"

    id = Column(Integer, primary_key=True, index=True)
    
    # 关联策略
    strategy_id = Column(Integer, ForeignKey("mean_reversion_strategies.id"), nullable=False, index=True)
    
    # 订单
    order_id = Column(String(100), nullable=True, index=True)
    
    # 交易方向
    side = Column(String(10), nullable=False)  # 'buy' / 'sell'
    
    # 价格和数量
    price = Column(Float, nullable=False)
    quantity = Column(Integer, default=1)
    
    # 偏离度
    deviation = Column(Float, nullable=True)  # 偏离均值百分比
    
    # 状态
    status = Column(String(20), default='pending', index=True)  # pending/completed/cancelled/failed
    
    # 盈亏
    profit = Column(Float, default=0.0)
    
    # 时间戳
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    # 关联
    strategy = relationship("MeanReversionStrategy", back_populates="trades")

    # 索引
    __table_args__ = (
        Index("idx_mr_trades_strategy", "strategy_id"),
    )

    def __repr__(self):
        return f"<MeanReversionTrade {self.side} {self.price}>"
