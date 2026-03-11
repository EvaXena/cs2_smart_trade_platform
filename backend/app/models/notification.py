# -*- coding: utf-8 -*-
"""
通知模型
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, Enum as SQLEnum, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum

from app.core.database import Base


class NotificationType(str, enum.Enum):
    """通知类型"""
    ORDER = "order"           # 订单通知
    PRICE_ALERT = "price"     # 价格提醒
    INVENTORY = "inventory"   # 库存通知
    MONITOR = "monitor"       # 监控通知
    SYSTEM = "system"         # 系统通知
    TRADE = "trade"           # 交易通知


class NotificationPriority(str, enum.Enum):
    """通知优先级"""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class NotificationStatus(str, enum.Enum):
    """通知状态"""
    UNREAD = "unread"
    READ = "read"
    ARCHIVED = "archived"


class Notification(Base):
    """通知表"""
    __tablename__ = "notifications"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # 用户ID - 外键关联
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    
    # 通知类型
    notification_type = Column(
        SQLEnum(NotificationType),
        nullable=False,
        default=NotificationType.SYSTEM
    )
    
    # 优先级
    priority = Column(
        SQLEnum(NotificationPriority),
        nullable=False,
        default=NotificationPriority.NORMAL
    )
    
    # 状态
    status = Column(
        SQLEnum(NotificationStatus),
        nullable=False,
        default=NotificationStatus.UNREAD
    )
    
    # 标题
    title = Column(String(255), nullable=False)
    
    # 内容
    content = Column(Text, nullable=False)
    
    # 相关数据（JSON格式存储）
    data = Column(Text, nullable=True)
    
    # 是否已读
    is_read = Column(Boolean, default=False, nullable=False)
    
    # 时间戳
    created_at = Column(DateTime, default=func.now(), nullable=False)
    read_at = Column(DateTime, nullable=True)
    
    # 关联关系
    user = relationship("User", back_populates="notifications")
    
    def __repr__(self):
        return f"<Notification {self.id}: {self.title}>"
