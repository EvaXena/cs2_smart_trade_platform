# -*- coding: utf-8 -*-
"""
库存模型
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Numeric, DateTime, ForeignKey, Index, Float
from sqlalchemy.orm import relationship

from app.core.database import Base


class Inventory(Base):
    """库存模型"""
    __tablename__ = "inventory"

    id = Column(Integer, primary_key=True, index=True)
    
    # 用户
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    
    # 饰品
    item_id = Column(Integer, ForeignKey("items.id"), nullable=False, index=True)
    
    # Steam 资产信息
    asset_id = Column(String(100), nullable=True, index=True)  # Steam asset ID
    instance_id = Column(String(100), nullable=True)
    context_id = Column(Integer, default=2)  # CS2 库存 context_id=2
    class_id = Column(String(100), nullable=True)
    
    # 数量
    amount = Column(Integer, default=1)
    
    # 成本/售价
    cost_price = Column(Numeric(12, 2), nullable=True)  # 成本价
    price = Column(Numeric(12, 2), nullable=True)  # 售价/当前价格
    
    # 状态
    status = Column(String(20), default='available', index=True)  # available / listing / trading / sold
    
    # 磨损度
    float_value = Column(Float, nullable=True)
    paint_seed = Column(Integer, nullable=True)
    
    # 饰品原始数据 (JSON)
    raw_data = Column(String(2000), nullable=True)
    
    # 时间戳
    acquired_at = Column(DateTime, default=datetime.utcnow)  # 获取时间
    listed_at = Column(DateTime, nullable=True)  # 上架时间
    sold_at = Column(DateTime, nullable=True)    # 售出时间
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关联
    user = relationship("User", back_populates="inventory")
    item = relationship("Item", back_populates="inventory")

    # 索引
    __table_args__ = (
        Index("idx_inventory_user_status", "user_id", "status"),
        Index("idx_inventory_asset_id", "asset_id"),
    )

    def __repr__(self):
        return f"<Inventory user={self.user_id} item={self.item_id}>"


class Listing(Base):
    """市场上架记录"""
    __tablename__ = "listings"

    id = Column(Integer, primary_key=True, index=True)
    
    # 库存
    inventory_id = Column(Integer, ForeignKey("inventory.id"), nullable=False)
    
    # 上架信息
    listing_id = Column(String(100), unique=True, nullable=True)  # Steam listing ID
    price = Column(Numeric(12, 2), nullable=False)  # 上架价格
    
    # 平台
    platform = Column(String(20), nullable=False)  # 'steam' / 'buff'
    
    # 状态
    status = Column(String(20), default='listing', index=True)  # listing / sold / cancelled
    
    # 时间戳
    listed_at = Column(DateTime, default=datetime.utcnow)
    sold_at = Column(DateTime, nullable=True)
    cancelled_at = Column(DateTime, nullable=True)
    
    # 售出信息
    sold_price = Column(Numeric(12, 2), nullable=True)
    buyer_steam_id = Column(String(64), nullable=True)

    # 索引
    __table_args__ = (
        Index("idx_listings_inventory", "inventory_id"),
        Index("idx_listings_status", "status"),
    )
