# -*- coding: utf-8 -*-
"""
网格交易数据库模型
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Numeric, DateTime, ForeignKey, Index, Float, Boolean, JSON
from sqlalchemy.orm import relationship

from app.core.database import Base


class GridStrategy(Base):
    """网格交易策略配置"""
    __tablename__ = "grid_strategies"

    id = Column(Integer, primary_key=True, index=True)
    
    # 用户
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    
    # 交易品种 (item_id)
    item_id = Column(Integer, ForeignKey("items.id"), nullable=False, index=True)
    
    # 策略名称
    name = Column(String(100), nullable=False)
    
    # 价格区间
    price_lower = Column(Float, nullable=False)  # 价格下界
    price_upper = Column(Float, nullable=False)  # 价格上界
    
    # 网格配置
    grid_count = Column(Integer, nullable=False, default=10)  # 网格数量
    quantity_per_grid = Column(Integer, nullable=False, default=1)  # 每格数量
    
    # 风控参数
    profit_percentage = Column(Float, nullable=False, default=1.0)  # 止盈百分比
    stop_loss_percentage = Column(Float, nullable=False, default=5.0)  # 止损百分比
    
    # 状态
    is_active = Column(Boolean, default=True, index=True)
    status = Column(String(20), default='pending', index=True)  # pending/running/paused/stopped/completed
    
    # 当前价格锚点
    last_price = Column(Float, nullable=True)
    entry_price = Column(Float, nullable=True)  # 进场价格
    
    # 统计
    total_trades = Column(Integer, default=0)  # 总交易次数
    total_profit = Column(Float, default=0.0)  # 总收益
    completed_grids = Column(Integer, default=0)  # 已完成格子数
    
    # 网格状态 (JSON)
    grid_state = Column(JSON, nullable=True)  # 网格状态
    
    # 时间戳
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    stopped_at = Column(DateTime, nullable=True)

    # 关联
    user = relationship("User", backref="grid_strategies")
    item = relationship("Item", backref="grid_strategies")
    trades = relationship("GridTrade", back_populates="strategy", cascade="all, delete-orphan")

    # 索引
    __table_args__ = (
        Index("idx_grid_user_status", "user_id", "status"),
        Index("idx_grid_item_active", "item_id", "is_active"),
    )

    def __repr__(self):
        return f"<GridStrategy {self.name} {self.status}>"


class GridTrade(Base):
    """网格交易记录"""
    __tablename__ = "grid_trades"

    id = Column(Integer, primary_key=True, index=True)
    
    # 关联策略
    strategy_id = Column(Integer, ForeignKey("grid_strategies.id"), nullable=False, index=True)
    
    # 订单
    order_id = Column(String(100), nullable=True, index=True)
    
    # 交易方向
    side = Column(String(10), nullable=False)  # 'buy' / 'sell'
    
    # 价格和数量
    price = Column(Float, nullable=False)
    quantity = Column(Integer, default=1)
    
    # 所属网格索引
    grid_index = Column(Integer, nullable=False)
    
    # 状态
    status = Column(String(20), default='pending', index=True)  # pending/completed/cancelled/failed
    
    # 盈亏
    profit = Column(Float, default=0.0)
    
    # 时间戳
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    # 关联
    strategy = relationship("GridStrategy", back_populates="trades")

    # 索引
    __table_args__ = (
        Index("idx_grid_trades_strategy", "strategy_id"),
    )

    def __repr__(self):
        return f"<GridTrade {self.side} {self.price}>"
